from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import App
from core.logs.models import AppLogManager, LogCategory


# Comandos permitidos para segurança (whitelist)
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
}

# Prefixos permitidos (para comandos com argumentos variáveis)
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
    """Verifica se o comando é permitido (whitelist + prefixos)."""
    command = command.strip()

    # Comando exato na whitelist
    if command in ALLOWED_COMMANDS:
        return True

    # Prefixo permitido
    for prefix in ALLOWED_PREFIXES:
        if command.startswith(prefix):
            # Bloqueia comandos perigosos mesmo com prefixo válido
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


class RunCommandMixin:
    """Mixin para execução de comandos dentro do container de um app via Celery."""

    @shared_task(bind=True)
    def run_command(self, app_id: int, command: str) -> dict:
        """
        Executa um comando dentro do container do app no Dokku.
        Equivale a: dokku run <app> <command>
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            app = App.objects.get(id=app_id)
        except App.DoesNotExist:
            return {'status': 'error', 'message': f'App {app_id} not found'}

        if not app.name_dokku:
            return {'status': 'error', 'message': 'App sem name_dokku configurado'}

        # Validação de segurança
        if not is_command_allowed(command):
            return {
                'status': 'error',
                'message': f'Comando não permitido: {command}',
            }

        # Salva task_id
        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()

        try:
            task.update_state(
                state='PROGRESS',
                meta={'current': 10, 'total': 100, 'status': f'Executando: {command}'},
            )
            logger.info(
                f'Executando comando: {command}',
                category=LogCategory.SYSTEM,
                progress=10,
            )

            # Executa com streaming para acompanhar output em tempo real
            line_count = [0]
            all_output = []

            def on_log_line(line: str):
                if not line.strip():
                    return
                line_count[0] += 1
                all_output.append(line)
                progress = min(10 + (line_count[0] * 2), 90)
                logger.dokku(line, category=LogCategory.SYSTEM, progress=int(progress))

            output = dokku_adapter.run_in_app_streaming(
                app_name=app.name_dokku,
                command=command,
            )

            for line in output:
                on_log_line(line)

            full_output = '\n'.join(all_output)

            # Verifica se houve erro
            if 'Failed' in full_output or 'Error' in full_output.split('\n')[-1:][0] if all_output else '':
                logger.warning(
                    f'Comando finalizado com possíveis erros ({line_count[0]} linhas)',
                    category=LogCategory.SYSTEM,
                    progress=100,
                )
            else:
                logger.success(
                    f'Comando executado com sucesso! ({line_count[0]} linhas de output)',
                    category=LogCategory.SYSTEM,
                    progress=100,
                )

            return {
                'status': 'success',
                'app_id': app.id,  # type: ignore
                'command': command,
                'output': full_output,
                'lines': line_count[0],
            }

        except Exception as e:
            logger.error(
                f'Erro ao executar comando: {str(e)}',
                category=LogCategory.SYSTEM,
                metadata={'error_type': type(e).__name__, 'command': command},
            )
            raise
