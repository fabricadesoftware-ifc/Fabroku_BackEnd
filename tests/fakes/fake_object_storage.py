"""Garage (S3) de mentira para os testes: buckets e chaves em memória."""
from infrastructure.adapters.garage import S3Credentials


class FakeObjectStorage:
    def __init__(self, endpoint: str = 'https://s3.test', region: str = 'garage'):
        self.endpoint = endpoint
        self.region = region
        self.buckets: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []

    def get_bucket(self, name: str) -> dict | None:
        self.calls.append(('get_bucket', name))
        return self.buckets.get(name)

    def ensure_bucket(self, name: str, *, max_size_bytes: int | None, max_objects: int | None) -> S3Credentials:
        self.calls.append(('ensure_bucket', name))
        bucket = self.buckets.setdefault(name, {
            'key_id': f'GK{len(self.buckets) + 1:024d}',
            'secret': f'segredo-{name}',
            'objects': 0,
        })
        bucket['quota'] = (max_size_bytes, max_objects)
        return S3Credentials(bucket['key_id'], bucket['secret'], name, self.endpoint, self.region)

    def delete_bucket(self, name: str) -> str:
        self.calls.append(('delete_bucket', name))
        self.buckets.pop(name, None)
        return f'bucket {name} apagado'
