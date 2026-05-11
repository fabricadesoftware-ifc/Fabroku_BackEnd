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


def build_loaddata_command(manage_path: str, tmp_path: str) -> str:
    script = '\n'.join([
        'set -e',
        f'tmp={shlex.quote(tmp_path)}',
        'cleanup() { rm -f "$tmp"; }',
        'trap cleanup EXIT',
        'cat > "$tmp"',
        f'python {shlex.quote(manage_path)} loaddata "$tmp"',
    ])
    return f'sh -lc {shlex.quote(script)}'


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
    def run_loaddata(self, app_id: int, artifact_id: str, manage_path: str, user_id: int) -> dict:
        task = cast(Task, self)
        task_id = task.request.id

        try:
            app = App.objects.get(id=app_id, deleted_at__isnull=True)
            artifact = AppRunArtifact.objects.get(
                id=artifact_id,
                app=app,
                created_by_id=user_id,
                kind=AppRunArtifactKind.LOAD_DATA_UPLOAD,
            )
        except (App.DoesNotExist, AppRunArtifact.DoesNotExist) as e:
            raise RuntimeError('App ou artefato de loaddata nao encontrado.') from e

        if not app.name_dokku:
            raise RuntimeError('App sem name_dokku configurado.')

        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()
        logical_command = f'python {manage_path} loaddata <fixture>'

        try:
            fixture_text = bytes(artifact.content).decode('utf-8')

            task.update_state(
                state='PROGRESS',
                meta={'current': 10, 'total': 100, 'status': f'Enviando fixture {artifact.filename}'},
            )
            logger.info(
                f'Executando loaddata com fixture {artifact.filename} ({artifact.size} bytes)',
                category=LogCategory.DATABASE,
                progress=10,
                metadata={'command': logical_command, 'filename': artifact.filename, 'size': artifact.size},
            )

            tmp_path = f'/tmp/fabroku-loaddata-{artifact.id}.json'
            output = dokku_adapter.run_in_app_with_stdin(
                app_name=app.name_dokku,
                command=build_loaddata_command(manage_path, tmp_path),
                stdin_data=fixture_text,
            )

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
                    metadata={'command': logical_command},
                )
                raise RuntimeError(output)

            app.error_type = None
            app.error_details = None
            app.save(update_fields=['error_type', 'error_details'])
            logger.success('loaddata executado com sucesso.', category=LogCategory.DATABASE, progress=100)
            return {
                'status': 'success',
                'message': f'loaddata executado com sucesso: {artifact.filename}',
                'app_id': app.id,
                'command': logical_command,
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
                metadata={'error_type': type(e).__name__, 'command': logical_command},
            )
            raise
        finally:
            artifact.delete()
            cleanup_expired_run_artifacts()

    @shared_task(bind=True)
    def run_dumpdata(self, app_id: int, manage_path: str, dump_args: list[str], output_filename: str, user_id: int) -> dict:
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
