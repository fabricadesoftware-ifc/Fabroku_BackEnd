import shlex
from datetime import timedelta
from pathlib import PurePosixPath

from django.utils import timezone

from applications.models import AppRunArtifact

ARTIFACT_TTL_HOURS = 24
DANGEROUS_DUMP_ARG_PARTS = ('&&', '||', ';', '|', '>', '<', '`', '$(', '\n', '\r', '\x00')
BLOCKED_DUMP_ARGS = {'--output', '-o'}
SAFE_RUN_PATH_CHARS = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/')


def validate_safe_run_path_chars(value: str, field_name: str):
    if any(char not in SAFE_RUN_PATH_CHARS for char in value):
        raise ValueError(f'{field_name} aceita apenas letras, numeros, ".", "_", "-" e "/".')


def cleanup_expired_run_artifacts():
    AppRunArtifact.objects.filter(expires_at__lt=timezone.now()).delete()


def get_run_artifact_expires_at():
    return timezone.now() + timedelta(hours=ARTIFACT_TTL_HOURS)


def validate_manage_path(manage_path: str | None) -> str:
    normalized = (manage_path or 'manage.py').strip().replace('\\', '/')
    if not normalized:
        raise ValueError('manage_path nao pode ser vazio.')
    if normalized.startswith(('/', '~')) or ':' in normalized:
        raise ValueError('manage_path deve ser relativo ao app.')
    validate_safe_run_path_chars(normalized, 'manage_path')

    path = PurePosixPath(normalized)
    if '..' in path.parts:
        raise ValueError('manage_path nao pode conter "..".')
    if path.name != 'manage.py':
        raise ValueError('manage_path deve apontar para um arquivo manage.py.')

    return str(path)


def validate_dump_args(raw_args) -> list[str]:
    if raw_args in (None, ''):
        return []
    if not isinstance(raw_args, list):
        raise ValueError('dump_args deve ser uma lista de argumentos.')
    if len(raw_args) > 50:
        raise ValueError('dump_args excede o limite de 50 argumentos.')

    args = []
    for raw_arg in raw_args:
        arg = str(raw_arg)
        if not arg:
            raise ValueError('dump_args nao pode conter argumento vazio.')
        if arg in BLOCKED_DUMP_ARGS or arg.startswith('--output='):
            raise ValueError('dumpdata nao aceita --output; use --output na CLI.')
        if any(part in arg for part in DANGEROUS_DUMP_ARG_PARTS):
            raise ValueError(f'Argumento de dumpdata nao permitido: {arg}')
        args.append(arg)

    return args


def build_dumpdata_command(manage_path: str, dump_args: list[str]) -> str:
    parts = ['python', manage_path, 'dumpdata', *dump_args]
    return ' '.join(shlex.quote(part) for part in parts)


def validate_loaddata_fixture_path(fixture_path: str | None) -> str:
    normalized = (fixture_path or '').strip().replace('\\', '/')
    if not normalized:
        raise ValueError('fixture_path nao pode ser vazio.')
    if normalized.startswith(('/', '~')) or ':' in normalized:
        raise ValueError('fixture_path deve ser relativo ao app.')
    if any(part in normalized for part in ('\n', '\r', '\x00')):
        raise ValueError('fixture_path contem caracteres invalidos.')
    validate_safe_run_path_chars(normalized, 'fixture_path')

    path = PurePosixPath(normalized)
    if '..' in path.parts:
        raise ValueError('fixture_path nao pode conter "..".')
    if path.name in ('', '.', '..'):
        raise ValueError('fixture_path deve apontar para um arquivo JSON.')
    if not path.name.lower().endswith('.json'):
        raise ValueError('fixture_path deve apontar para um arquivo .json.')

    return str(path)


def build_loaddata_command(manage_path: str, fixture_path: str) -> str:
    parts = ['python', manage_path, 'loaddata', fixture_path]
    return ' '.join(shlex.quote(part) for part in parts)


def build_migrate_command(manage_path: str, noinput: bool = False) -> str:
    parts = ['python', manage_path, 'migrate']
    if noinput:
        parts.append('--noinput')
    return ' '.join(shlex.quote(part) for part in parts)


def command_output_failed(output: str) -> bool:
    normalized = (output or '').lower()
    return (
        normalized.startswith('failed to execute command:')
        or normalized.startswith('ssh connection error:')
        or '[ssh error]' in normalized
        or 'traceback (most recent call last):' in normalized
        or 'commanderror' in normalized
    )


