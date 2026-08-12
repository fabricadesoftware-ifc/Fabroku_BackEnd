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


