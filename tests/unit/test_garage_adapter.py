"""GarageAdapter com uma sessão HTTP de mentira (sem rede)."""
import datetime

import pytest

from infrastructure.adapters.garage import GarageAdapter, GarageError, S3Client, S3Credentials


class FakeResponse:
    def __init__(self, status=200, data=None, text=''):
        self.status_code = status
        self._data = data
        self.text = text
        self.content = b'' if data is None and not text else (text.encode() or b'x')

    def json(self):
        return self._data


class FakeSession:
    """Responde à API de admin v2 a partir de um estado em memória."""

    def __init__(self):
        self.buckets = {}
        self.keys = {}
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):  # noqa: PLR0911, PLR0913
        endpoint = url.rsplit('/v2/', 1)[-1]
        self.calls.append(endpoint)
        assert headers['Authorization'] == 'Bearer tok'
        params = params or {}
        if endpoint == 'GetBucketInfo':
            bucket = self.buckets.get(params.get('globalAlias'))
            return FakeResponse(200, bucket) if bucket else FakeResponse(404, {'message': 'no'}, 'no')
        if endpoint == 'CreateBucket':
            self.buckets[json['globalAlias']] = {'id': f"id-{json['globalAlias']}", 'objects': 0}
            return FakeResponse(200, self.buckets[json['globalAlias']])
        if endpoint == 'GetKeyInfo':
            key = self.keys.get(params.get('search')) or next(
                (k for k in self.keys.values() if k['accessKeyId'] == params.get('id')), None
            )
            return FakeResponse(200, key) if key else FakeResponse(404, {'message': 'no'}, 'no')
        if endpoint == 'CreateKey':
            self.keys[json['name']] = {'accessKeyId': f"GK{json['name']}", 'secretAccessKey': 's', 'name': json['name']}
            return FakeResponse(200, self.keys[json['name']])
        if endpoint in {'AllowBucketKey', 'UpdateBucket', 'CleanupIncompleteUploads'}:
            return FakeResponse(200, {})
        if endpoint == 'DeleteKey':
            self.keys = {n: k for n, k in self.keys.items() if k['accessKeyId'] != params['id']}
            return FakeResponse(200)
        if endpoint == 'DeleteBucket':
            self.buckets = {n: b for n, b in self.buckets.items() if b['id'] != params['id']}
            return FakeResponse(200)
        return FakeResponse(500, {'message': 'inesperado'}, 'inesperado')


def adapter(session):
    return GarageAdapter(admin_url='http://garage', admin_token='tok', s3_endpoint='https://s3.test',
                         region='garage', session=session)


def test_ensure_bucket_is_idempotent_and_restricts_key():
    session = FakeSession()
    first = adapter(session).ensure_bucket('blog-1', max_size_bytes=10, max_objects=5)
    second = adapter(session).ensure_bucket('blog-1', max_size_bytes=10, max_objects=5)

    assert first == second
    assert first.url() == 'https://GKblog-1:s@s3.test/blog-1'
    assert session.calls.count('CreateBucket') == 1 and session.calls.count('CreateKey') == 1
    assert 'AllowBucketKey' in session.calls and 'UpdateBucket' in session.calls


def test_delete_bucket_removes_key_and_bucket_and_is_idempotent():
    session = FakeSession()
    adapter(session).ensure_bucket('blog-1', max_size_bytes=None, max_objects=None)

    adapter(session).delete_bucket('blog-1')
    assert not session.buckets and not session.keys
    assert 'já não existia' in adapter(session).delete_bucket('blog-1')


def test_admin_error_is_raised_with_message():
    class Broken(FakeSession):
        def request(self, *args, **kwargs):
            return FakeResponse(403, {'message': 'Invalid bearer'}, 'Invalid bearer')

    with pytest.raises(GarageError, match='Invalid bearer'):
        adapter(Broken()).get_bucket('x')


def test_missing_configuration_fails_fast(settings):
    settings.GARAGE_ADMIN_TOKEN = None
    with pytest.raises(GarageError):
        GarageAdapter(admin_url='http://garage')


def test_sigv4_matches_aws_reference_shape():
    """Assinatura determinística: mesma entrada, mesma assinatura, e cabeçalhos certos."""
    captured = {}

    class Capture:
        def request(self, method, url, headers=None, timeout=None):
            captured.update(method=method, url=url, headers=headers)
            return FakeResponse(204)

    creds = S3Credentials('GKabc', 'segredo', 'blog-1', 'https://s3.test', 'garage')
    when = datetime.datetime(2026, 11, 20, 12, 0, tzinfo=datetime.UTC)
    S3Client(creds, session=Capture())._signed_request('DELETE', '/blog-1/pasta/a b+c.txt', now=when)

    assert captured['url'] == 'https://s3.test/blog-1/pasta/a%20b%2Bc.txt'
    auth = captured['headers']['Authorization']
    assert auth.startswith('AWS4-HMAC-SHA256 Credential=GKabc/20261120/garage/s3/aws4_request, ')
    assert 'SignedHeaders=host;x-amz-content-sha256;x-amz-date' in auth
    assert captured['headers']['x-amz-date'] == '20261120T120000Z'
