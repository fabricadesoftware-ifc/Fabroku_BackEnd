import shlex
from datetime import timedelta
from pathlib import PurePosixPath
from typing import cast

from celery import Task, shared_task
from django.conf import settings
from django.utils import timezone

from core.adapters import DokkuAdapter
from core.apps.models import App, AppRunArtifact, AppRunArtifactKind
from core.logs.models import AppLogManager, LogCategory

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


class RunDataMixin:
    """Tasks para import/export de dados Django via CLI."""

    @shared_task(bind=True)
    def run_migrate(self, app_id: int, manage_path: str, noinput: bool, user_id: int) -> dict:
        task = cast(Task, self)
        task_id = task.request.id

        try:
            app = App.objects.get(id=app_id, deleted_at__isnull=True)
        except App.DoesNotExist as e:
            raise RuntimeError(f'App {app_id} not found') from e

        if not app.name_dokku:
            raise RuntimeError('App sem name_dokku configurado.')

        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()
        command = build_migrate_command(manage_path, noinput=noinput)

        try:
            task.update_state(
                state='PROGRESS',
                meta={'current': 10, 'total': 100, 'status': 'Executando migrations Django'},
            )
            logger.info(
                'Executando migrations Django.',
                category=LogCategory.DATABASE,
                progress=10,
                metadata={'command': command, 'manage_path': manage_path, 'noinput': noinput},
            )

            output = dokku_adapter.run_in_app(app_name=app.name_dokku, command=command)

            if output.strip():
                for line in output.splitlines()[:100]:
                    logger.dokku(line, category=LogCategory.DATABASE, progress=60)

            if command_output_failed(output):
                app.error_type = 'MigrateExecutionError'
                app.error_details = output[:4000]
                app.save(update_fields=['error_type', 'error_details'])
                logger.error(
                    'migrate finalizado com erro.',
                    category=LogCategory.DATABASE,
                    progress=100,
                    metadata={'command': command},
                )
                raise RuntimeError(output)

            app.error_type = None
            app.error_details = None
            app.save(update_fields=['error_type', 'error_details'])
            logger.success('migrate executado com sucesso.', category=LogCategory.DATABASE, progress=100)
            return {
                'status': 'success',
                'message': 'migrate executado com sucesso.',
                'app_id': app.id,
                'command': command,
                'output': output,
                'lines': len(output.splitlines()) if output else 0,
            }
        except Exception as e:
            if not app.error_details:
                app.error_type = type(e).__name__
                app.error_details = str(e)
                app.save(update_fields=['error_type', 'error_details'])
            logger.error(
                f'Erro ao executar migrate: {e}',
                category=LogCategory.DATABASE,
                metadata={'error_type': type(e).__name__, 'command': command},
            )
            raise
        finally:
            cleanup_expired_run_artifacts()

    @shared_task(bind=True)
    def run_loaddata(self, app_id: int, fixture_path: str, manage_path: str, user_id: int) -> dict:
        task = cast(Task, self)
        task_id = task.request.id

        try:
            app = App.objects.get(id=app_id, deleted_at__isnull=True)
        except App.DoesNotExist as e:
            raise RuntimeError(f'App {app_id} not found') from e

        if not app.name_dokku:
            raise RuntimeError('App sem name_dokku configurado.')

        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()
        command = build_loaddata_command(manage_path, fixture_path)

        try:
            task.update_state(
                state='PROGRESS',
                meta={'current': 10, 'total': 100, 'status': f'Executando loaddata com {fixture_path}'},
            )
            logger.info(
                f'Executando loaddata com fixture {fixture_path}',
                category=LogCategory.DATABASE,
                progress=10,
                metadata={'command': command, 'fixture_path': fixture_path},
            )

            output = dokku_adapter.run_in_app(app_name=app.name_dokku, command=command)

            if output.strip():
                for line in output.splitlines()[:100]:
                    logger.dokku(line, category=LogCategory.DATABASE, progress=60)

            if command_output_failed(output):
                app.error_type = 'LoaddataExecutionError'
                app.error_details = output[:4000]
                app.save(update_fields=['error_type', 'error_details'])
                logger.error(
                    'loaddata finalizado com erro.',
                    category=LogCategory.DATABASE,
                    progress=100,
                    metadata={'command': command},
                )
                raise RuntimeError(output)

            app.error_type = None
            app.error_details = None
            app.save(update_fields=['error_type', 'error_details'])
            logger.success('loaddata executado com sucesso.', category=LogCategory.DATABASE, progress=100)
            return {
                'status': 'success',
                'message': f'loaddata executado com sucesso: {fixture_path}',
                'app_id': app.id,
                'command': command,
                'lines': len(output.splitlines()) if output else 0,
            }
        except Exception as e:
            if not app.error_details:
                app.error_type = type(e).__name__
                app.error_details = str(e)
                app.save(update_fields=['error_type', 'error_details'])
            logger.error(
                f'Erro ao executar loaddata: {e}',
                category=LogCategory.DATABASE,
                metadata={'error_type': type(e).__name__, 'command': command},
            )
            raise
        finally:
            cleanup_expired_run_artifacts()

    @shared_task(bind=True)
    def run_dumpdata(
        self,
        app_id: int,
        manage_path: str,
        dump_args: list[str],
        output_filename: str,
        user_id: int,
    ) -> dict:
        task = cast(Task, self)
        task_id = task.request.id

        try:
            app = App.objects.get(id=app_id, deleted_at__isnull=True)
        except App.DoesNotExist as e:
            raise RuntimeError(f'App {app_id} not found') from e

        if not app.name_dokku:
            raise RuntimeError('App sem name_dokku configurado.')

        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()
        command = build_dumpdata_command(manage_path, dump_args)

        try:
            task.update_state(
                state='PROGRESS',
                meta={'current': 10, 'total': 100, 'status': 'Gerando dumpdata no container'},
            )
            logger.info(
                f'Executando dumpdata para {output_filename}',
                category=LogCategory.DATABASE,
                progress=10,
                metadata={'command': command, 'filename': output_filename},
            )

            output = dokku_adapter.run_in_app(app_name=app.name_dokku, command=command)
            if command_output_failed(output):
                app.error_type = 'DumpdataExecutionError'
                app.error_details = output[:4000]
                app.save(update_fields=['error_type', 'error_details'])
                logger.error(
                    'dumpdata finalizado com erro.',
                    category=LogCategory.DATABASE,
                    progress=100,
                    metadata={'command': command},
                )
                raise RuntimeError(output)

            content = output.encode('utf-8')
            max_size = int(getattr(settings, 'CLI_RUN_ARTIFACT_MAX_BYTES', 50 * 1024 * 1024))
            if len(content) > max_size:
                raise RuntimeError(f'dumpdata excedeu o limite de {max_size} bytes.')

            artifact = AppRunArtifact.objects.create(
                app=app,
                created_by_id=user_id,
                kind=AppRunArtifactKind.DUMP_DATA_EXPORT,
                filename=output_filename,
                content_type='application/json',
                size=len(content),
                content=content,
                expires_at=get_run_artifact_expires_at(),
            )

            app.error_type = None
            app.error_details = None
            app.save(update_fields=['error_type', 'error_details'])
            logger.success(
                f'dumpdata gerado com sucesso ({len(content)} bytes).',
                category=LogCategory.DATABASE,
                progress=100,
                metadata={'artifact_id': str(artifact.id), 'filename': output_filename, 'size': len(content)},
            )

            return {
                'status': 'success',
                'message': f'dumpdata gerado com sucesso: {output_filename}',
                'app_id': app.id,
                'command': command,
                'artifact': {
                    'id': str(artifact.id),
                    'filename': artifact.filename,
                    'size': artifact.size,
                    'download_url': f'/api/apps/apps/{app.id}/artifacts/{artifact.id}/download/',
                },
            }
        except Exception as e:
            if not app.error_details:
                app.error_type = type(e).__name__
                app.error_details = str(e)
                app.save(update_fields=['error_type', 'error_details'])
            logger.error(
                f'Erro ao executar dumpdata: {e}',
                category=LogCategory.DATABASE,
                metadata={'error_type': type(e).__name__, 'command': command},
            )
            raise
        finally:
            cleanup_expired_run_artifacts()
