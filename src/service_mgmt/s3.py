"""Serviço "Armazenamento S3": bucket + chave restrita no Garage, injetados no app como variáveis.

Ao contrário de Postgres/Redis, não há plugin do Dokku: o bucket vive no Garage
(VM s3) e o "link" é só gravar as variáveis no config do app.

Variáveis gravadas no app:
  - `<env_key>` (padrão `S3_URL`): https://CHAVE:SEGREDO@host/bucket, no estilo DATABASE_URL;
  - só para o primeiro S3 do app (env_key == S3_URL), também os nomes que o boto3 e o
    django-storages leem sozinhos: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
    AWS_STORAGE_BUCKET_NAME, AWS_S3_ENDPOINT_URL, AWS_ENDPOINT_URL_S3, AWS_S3_REGION_NAME,
    AWS_DEFAULT_REGION e AWS_S3_ADDRESSING_STYLE=path.

No Service: `container_name` = bucket, `user` = id da chave, `password` = segredo,
`host` = host do endpoint, `port` = 443.
"""
from __future__ import annotations

from django.conf import settings

from applications.ports.i_dokku import IDokkuPort
from infrastructure.adapters.garage import GarageAdapter, S3Credentials
from service_mgmt.service_types import ServiceRuntime

BUCKET_NAME_MAX_LENGTH = 63
BUCKET_NAME_MIN_LENGTH = 3

AWS_ENV_KEYS = (
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',
    'AWS_STORAGE_BUCKET_NAME',
    'AWS_S3_ENDPOINT_URL',
    'AWS_ENDPOINT_URL_S3',
    'AWS_S3_REGION_NAME',
    'AWS_DEFAULT_REGION',
    'AWS_S3_ADDRESSING_STYLE',
)


def bucket_name(name: str) -> str:
    """Nome de bucket válido no S3 (3–63 caracteres, a-z 0-9 e hífen)."""
    name = name[:BUCKET_NAME_MAX_LENGTH].strip('-')
    if len(name) < BUCKET_NAME_MIN_LENGTH:
        name = f'{name}-s3'.strip('-')
    return name


def provision(storage: GarageAdapter, name: str) -> S3Credentials:
    return storage.ensure_bucket(
        name,
        max_size_bytes=settings.FABROKU_S3_QUOTA_MB * 1024 * 1024 if settings.FABROKU_S3_QUOTA_MB else None,
        max_objects=settings.FABROKU_S3_MAX_OBJECTS or None,
    )


def credentials_from_service(service) -> S3Credentials:
    return S3Credentials(
        access_key_id=service.user,
        secret_access_key=service.password,
        bucket=service.container_name,
        endpoint=settings.FABROKU_S3_ENDPOINT.rstrip('/'),
        region=settings.FABROKU_S3_REGION,
    )


def env_keys(env_key: str, runtime: ServiceRuntime) -> list[str]:
    keys = [env_key]
    if env_key == runtime.env_key:
        keys += list(AWS_ENV_KEYS)
    return keys


def env_vars(creds: S3Credentials, env_key: str, runtime: ServiceRuntime) -> dict[str, str]:
    variables = {env_key: creds.url()}
    if env_key == runtime.env_key:
        variables.update({
            'AWS_ACCESS_KEY_ID': creds.access_key_id,
            'AWS_SECRET_ACCESS_KEY': creds.secret_access_key,
            'AWS_STORAGE_BUCKET_NAME': creds.bucket,
            'AWS_S3_ENDPOINT_URL': creds.endpoint,
            'AWS_ENDPOINT_URL_S3': creds.endpoint,
            'AWS_S3_REGION_NAME': creds.region,
            'AWS_DEFAULT_REGION': creds.region,
            'AWS_S3_ADDRESSING_STYLE': 'path',
        })
    return variables


def link(  # noqa: PLR0913
    dokku: IDokkuPort, app, creds: S3Credentials, env_key: str, runtime: ServiceRuntime, *, no_restart: bool = True
) -> str:
    """Grava as variáveis no Dokku e espelha em app.variables (o aluno vê no painel)."""
    variables = env_vars(creds, env_key, runtime)
    output = dokku.set_config(app.name_dokku, variables, no_restart=no_restart)
    app.variables = {**(app.variables if isinstance(app.variables, dict) else {}), **variables}
    app.save(update_fields=['variables'])
    return output


def unlink(dokku: IDokkuPort, app, env_key: str, runtime: ServiceRuntime, *, no_restart: bool = True) -> str:
    keys = env_keys(env_key, runtime)
    output = ''
    if app.name_dokku:
        output = dokku.unset_config(app.name_dokku, keys, no_restart=no_restart)
    if isinstance(app.variables, dict) and any(k in app.variables for k in keys):
        app.variables = {k: v for k, v in app.variables.items() if k not in keys}
        app.save(update_fields=['variables'])
    return output
