import time
from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import App
from core.logs.models import AppLogManager, LogCategory

# Comandos permitidos para seguranca (whitelist)
ALLOWED_COMMANDS = {
    'python manage.py migrate',
    'python manage.py collectstatic --noinput',
    'python manage.py createsuperuser --noinput',
    'python manage.py showmigrations',
    'npm run migrate',
    'npx prisma migrate deploy',
    'npx prisma db push',
    'node ace migration:run',
    'php artisan migrate',
    'php artisan migrate --force',
    'rails db:migrate',
    'bundle exec rails db:migrate',
    'python manage.py loaddata'
}

# Prefixos permitidos (para comandos com argumentos variaveis)
ALLOWED_PREFIXES = (
    'python manage.py ',
    'npm run ',
    'npx prisma ',
    'node ace ',
    'php artisan ',
    'rails ',
    'bundle exec ',
)


def is_command_allowed(command: str) -> bool:
    """Verifica se o comando e permitido (whitelist + prefixos)."""
    command = command.strip()

    if command in ALLOWED_COMMANDS:
        return True

    for prefix in ALLOWED_PREFIXES:
        if command.startswith(prefix):
            dangerous = [
                'rm ',
                'del ',
                '&&',
                '||',
                ';',
                '|',
                '>',
                '<',
                '`',
                '$(',
            ]
            if not any(d in command for d in dangerous):
                return True

    return False


def _command_output_has_error(output: str) -> bool:
    normalized = (output or '').lower()
    error_markers = [
        '[error]',
        '[ssh error]',
        'failed to execute command',
        'traceback (most recent call last):',
        'commanderror',
        ' error:',
        'cannot link to a non running container',
    ]
    return any(marker in normalized for marker in error_markers)


class RunCommandMixin:
    """Mixin para execucao de comandos dentro do container de um app via Celery."""

    @shared_task(bind=True)
    def run_command(self, app_id: int, command: str) -> dict:
        """
        Executa um comando dentro do container do app no Dokku.
        Equivale a: dokku run <app> <command>
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            app = App.objects.get(id=app_id, deleted_at__isnull=True)
        except App.DoesNotExist:
            return {'status': 'error', 'message': f'App {app_id} not found'}

        if not app.name_dokku:
            return {'status': 'error', 'message': 'App sem name_dokku configurado'}

        if not is_command_allowed(command):
            return {
                'status': 'error',
                'message': f'Comando nao permitido: {command}',
            }

        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()

        try:
            from core.apps.models import Service  # noqa: PLC0415

            linked_services = Service.objects.filter(app=app, deleted_at__isnull=True)
            for svc in linked_services:
                if svc.container_name and svc.service_type == 'postgres':
                    out = dokku_adapter.start_database(svc.container_name)
                    if 'failed' in out.lower():
                        if 'sethostname' in out.lower() or 'invalid argument' in out.lower():
                            logger.info(
                                'Container travado por hostname invalido (runc), removendo...',
                                category=LogCategory.SYSTEM,
                                progress=5,
                            )
                            dokku_adapter.remove_postgres_container(svc.container_name)
                            time.sleep(2)
                            out = dokku_adapter.start_database(svc.container_name)
                        elif 'already in use' in out.lower() or 'conflict' in out.lower():
                            logger.info(
                                'Container em conflito, tentando postgres:stop antes de start...',
                                category=LogCategory.SYSTEM,
                                progress=5,
                            )
                            dokku_adapter.stop_database(svc.container_name)
                            time.sleep(2)
                            out = dokku_adapter.start_database(svc.container_name)
                        if 'failed' in out.lower():
                            msg = f'postgres:start {svc.container_name} retornou erro: {out}'
                            if 'sethostname' in out.lower():
                                msg += ' Remova o banco e crie um novo (nome curto compativel com runc).'
                            logger.warning(msg, category=LogCategory.SYSTEM, progress=5)
                    time.sleep(3)

            task.update_state(
                state='PROGRESS',
                meta={'current': 10, 'total': 100, 'status': f'Executando: {command}'},
            )
            logger.info(
                f'Executando comando: {command}',
                category=LogCategory.SYSTEM,
                progress=10,
            )

            line_count = [0]
            all_output = []
            max_attempts = 2
            full_output = ''

            def on_log_line(line: str):
                if not line.strip():
                    return
                line_count[0] += 1
                all_output.append(line)
                progress = min(10 + (line_count[0] * 2), 90)
                logger.dokku(line, category=LogCategory.SYSTEM, progress=int(progress))

            for attempt in range(max_attempts):
                line_count[0] = 0
                all_output.clear()

                output = dokku_adapter.run_in_app_streaming(
                    app_name=app.name_dokku,
                    command=command,
                )

                for line in output:
                    on_log_line(line)

                full_output = '\n'.join(all_output)

                if (
                    attempt < max_attempts - 1
                    and 'cannot link to a non running container' in full_output.lower()
                ):
                    logger.warning(
                        'Container do banco pode nao estar pronto. Tentando stop+start e tentando novamente...',
                        category=LogCategory.SYSTEM,
                        progress=10,
                    )
                    for svc in linked_services:
                        if svc.container_name and svc.service_type == 'postgres':
                            dokku_adapter.stop_database(svc.container_name)
                            time.sleep(2)
                            dokku_adapter.start_database(svc.container_name)
                    time.sleep(5)
                    continue

                break

            if _command_output_has_error(full_output):
                error_output = full_output.strip() or f'Falha ao executar comando: {command}'
                app.error_type = 'CommandExecutionError'
                app.error_details = error_output
                app.save(update_fields=['error_type', 'error_details'])
                logger.error(
                    f'Comando finalizado com erro: {command}',
                    category=LogCategory.SYSTEM,
                    progress=100,
                    metadata={'command': command, 'output': error_output[:2000]},
                )
                raise RuntimeError(error_output)

            app.error_type = None
            app.error_details = None
            app.save(update_fields=['error_type', 'error_details'])

            logger.success(
                f'Comando executado com sucesso! ({line_count[0]} linhas de output)',
                category=LogCategory.SYSTEM,
                progress=100,
            )

            return {
                'status': 'success',
                'message': f'Comando executado com sucesso: {command}',
                'app_id': app.id,  # type: ignore
                'command': command,
                'output': full_output,
                'lines': line_count[0],
            }

        except Exception as e:
            if not app.error_details:
                app.error_type = type(e).__name__
                app.error_details = str(e)
                app.save(update_fields=['error_type', 'error_details'])
            logger.error(
                f'Erro ao executar comando: {str(e)}',
                category=LogCategory.SYSTEM,
                metadata={'error_type': type(e).__name__, 'command': command},
            )
            raise
