"""Adapter do Garage (armazenamento de objetos compatível com S3).

Cada serviço S3 do Fabroku vira, no Garage:
  - um bucket com alias global = nome do serviço;
  - uma chave de acesso com o MESMO nome, com leitura/escrita só nesse bucket
    (a chave não pode criar buckets nem ver os de outros alunos);
  - uma cota de tamanho e de número de objetos no bucket.

Fala com a API de administração v2 do Garage (`/v2/...`, token Bearer). Para
esvaziar um bucket antes de apagá-lo usa a própria API S3 com a chave do
bucket (assinatura AWS SigV4 feita aqui, para não depender do boto3).
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
from dataclasses import dataclass
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

import requests
from django.conf import settings

S3_XML_NS = '{http://s3.amazonaws.com/doc/2006-03-01/}'
EMPTY_SHA256 = hashlib.sha256(b'').hexdigest()
HTTP_NOT_FOUND = 404
HTTP_ERROR = 400


class GarageError(RuntimeError):
    """Falha ao falar com o Garage."""


@dataclass(frozen=True)
class S3Credentials:
    access_key_id: str
    secret_access_key: str
    bucket: str
    endpoint: str
    region: str

    @property
    def host(self) -> str:
        return urlsplit(self.endpoint).netloc

    def url(self) -> str:
        """URL única no estilo DATABASE_URL: https://KEY:SECRET@host/bucket."""
        scheme = urlsplit(self.endpoint).scheme or 'https'
        return f'{scheme}://{self.access_key_id}:{self.secret_access_key}@{self.host}/{self.bucket}'


class GarageAdapter:
    """Cliente mínimo da API de administração v2 do Garage."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        admin_url: str | None = None,
        admin_token: str | None = None,
        s3_endpoint: str | None = None,
        region: str | None = None,
        timeout: float = 20,
        session: requests.Session | None = None,
    ):
        self.admin_url = (admin_url or settings.GARAGE_ADMIN_URL).rstrip('/')
        self.admin_token = admin_token or settings.GARAGE_ADMIN_TOKEN
        self.s3_endpoint = (s3_endpoint or settings.FABROKU_S3_ENDPOINT).rstrip('/')
        self.region = region or settings.FABROKU_S3_REGION
        self.timeout = timeout
        self.session = session or requests.Session()
        if not self.admin_url or not self.admin_token:
            raise GarageError('Armazenamento S3 não configurado (GARAGE_ADMIN_URL/GARAGE_ADMIN_TOKEN).')

    # ------------------------------------------------------------------ admin API
    def _admin(self, method: str, endpoint: str, *, params: dict | None = None, body: dict | None = None,
               allow_404: bool = False):
        try:
            response = self.session.request(
                method,
                f'{self.admin_url}/v2/{endpoint}',
                params=params,
                json=body,
                headers={'Authorization': f'Bearer {self.admin_token}'},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise GarageError(f'Garage indisponível: {exc.__class__.__name__}') from exc
        if allow_404 and response.status_code == HTTP_NOT_FOUND:
            return None
        if response.status_code >= HTTP_ERROR:
            try:
                detail = response.json().get('message') or response.text
            except ValueError:
                detail = response.text
            raise GarageError(f'Garage {endpoint} falhou ({response.status_code}): {detail[:300]}')
        if not response.content or response.content.strip() == b'null':
            return None
        return response.json()

    def get_bucket(self, name: str) -> dict | None:
        return self._admin('GET', 'GetBucketInfo', params={'globalAlias': name}, allow_404=True)

    def _get_key_by_name(self, name: str) -> dict | None:
        # `search` também casa por prefixo; confirmamos o nome exato.
        info = self._admin('GET', 'GetKeyInfo', params={'search': name, 'showSecretKey': 'true'}, allow_404=True)
        if info and info.get('name') == name:
            return info
        return None

    def ensure_bucket(self, name: str, *, max_size_bytes: int | None, max_objects: int | None) -> S3Credentials:
        """Cria (ou reaproveita, num retry) bucket + chave restrita + cota. Idempotente."""
        bucket = self.get_bucket(name) or self._admin('POST', 'CreateBucket', body={'globalAlias': name})
        key = self._get_key_by_name(name) or self._admin('POST', 'CreateKey', body={'name': name})
        if not key.get('secretAccessKey'):
            key = self._admin('GET', 'GetKeyInfo', params={'id': key['accessKeyId'], 'showSecretKey': 'true'})

        self._admin('POST', 'AllowBucketKey', body={
            'bucketId': bucket['id'],
            'accessKeyId': key['accessKeyId'],
            'permissions': {'read': True, 'write': True, 'owner': False},
        })
        self._admin('POST', 'UpdateBucket', params={'id': bucket['id']}, body={
            'quotas': {'maxSize': max_size_bytes, 'maxObjects': max_objects},
        })
        return S3Credentials(
            access_key_id=key['accessKeyId'],
            secret_access_key=key['secretAccessKey'],
            bucket=name,
            endpoint=self.s3_endpoint,
            region=self.region,
        )

    def delete_bucket(self, name: str) -> str:
        """Esvazia e apaga o bucket e a chave criada para ele. Idempotente."""
        bucket = self.get_bucket(name)
        key = self._get_key_by_name(name)
        if not bucket:
            if key:
                self._admin('POST', 'DeleteKey', params={'id': key['accessKeyId']})
            return f'bucket {name} já não existia'

        removed = 0
        if bucket.get('objects') and key:
            creds = S3Credentials(key['accessKeyId'], key['secretAccessKey'], name, self.s3_endpoint, self.region)
            removed = S3Client(creds, timeout=self.timeout, session=self.session).delete_all_objects()
        self._admin('POST', 'CleanupIncompleteUploads', body={'bucketId': bucket['id'], 'olderThanSecs': 0})
        if key:
            self._admin('POST', 'DeleteKey', params={'id': key['accessKeyId']})
        self._admin('POST', 'DeleteBucket', params={'id': bucket['id']})
        return f'bucket {name} apagado ({removed} objetos removidos)'


class S3Client:
    """Só o necessário da API S3 (listar e apagar objetos), com assinatura SigV4."""

    def __init__(self, creds: S3Credentials, *, timeout: float = 20, session: requests.Session | None = None):
        self.creds = creds
        self.timeout = timeout
        self.session = session or requests.Session()

    def _signature(self, date: str, amz_date: str, scope: str, canonical_request: str) -> str:
        string_to_sign = '\n'.join(
            ['AWS4-HMAC-SHA256', amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
        )
        signing_key = f'AWS4{self.creds.secret_access_key}'.encode()
        for part in (date, self.creds.region, 's3', 'aws4_request'):
            signing_key = hmac.new(signing_key, part.encode(), hashlib.sha256).digest()
        return hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    def _signed_request(self, method: str, path: str, query: dict[str, str] | None = None,
                        now: datetime.datetime | None = None) -> requests.Response:
        now = now or datetime.datetime.now(datetime.UTC)
        amz_date = now.strftime('%Y%m%dT%H%M%SZ')
        date = now.strftime('%Y%m%d')
        host = self.creds.host
        canonical_uri = quote(path, safe='/-_.~')
        query = query or {}
        canonical_query = '&'.join(
            f'{quote(k, safe="-_.~")}={quote(v, safe="-_.~")}' for k, v in sorted(query.items())
        )
        headers = {'host': host, 'x-amz-content-sha256': EMPTY_SHA256, 'x-amz-date': amz_date}
        signed_headers = ';'.join(sorted(headers))
        canonical_headers = ''.join(f'{k}:{headers[k]}\n' for k in sorted(headers))
        canonical_request = '\n'.join(
            [method, canonical_uri, canonical_query, canonical_headers, signed_headers, EMPTY_SHA256]
        )
        scope = f'{date}/{self.creds.region}/s3/aws4_request'
        signature = self._signature(date, amz_date, scope, canonical_request)
        headers['Authorization'] = (
            f'AWS4-HMAC-SHA256 Credential={self.creds.access_key_id}/{scope}, '
            f'SignedHeaders={signed_headers}, Signature={signature}'
        )
        url = f'{self.creds.endpoint}{canonical_uri}' + (f'?{canonical_query}' if canonical_query else '')
        try:
            return self.session.request(method, url, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise GarageError(f'S3 indisponível: {exc.__class__.__name__}') from exc

    def list_keys(self) -> list[str]:
        keys: list[str] = []
        token = None
        while True:
            query = {'list-type': '2', 'max-keys': '1000'}
            if token:
                query['continuation-token'] = token
            response = self._signed_request('GET', f'/{self.creds.bucket}', query)
            if response.status_code != 200:  # noqa: PLR2004
                raise GarageError(f'ListObjectsV2 falhou ({response.status_code}): {response.text[:300]}')
            root = ElementTree.fromstring(response.content)  # noqa: S314 - resposta do nosso próprio Garage
            keys += [el.text for el in root.iter(f'{S3_XML_NS}Key') if el.text]
            truncated = (root.findtext(f'{S3_XML_NS}IsTruncated') or '').lower() == 'true'
            token = root.findtext(f'{S3_XML_NS}NextContinuationToken')
            if not truncated or not token:
                return keys

    def delete_all_objects(self) -> int:
        removed = 0
        while keys := self.list_keys():
            for key in keys:
                response = self._signed_request('DELETE', f'/{self.creds.bucket}/{key}')
                if response.status_code not in {200, 204, 404}:
                    raise GarageError(f'DeleteObject {key} falhou ({response.status_code})')
                removed += 1
        return removed
