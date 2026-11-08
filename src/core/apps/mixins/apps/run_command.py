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


# Subcomandos que abrem um interpretador/REPL ou avaliam codigo arbitrario a partir
# de um argumento. Com eles o prefixo "python manage.py " deixaria passar qualquer
# coisa (ex.: `python manage.py shell -c "<codigo>"`).
BLOCKED_TOKENS = frozenset({
    'shell',
    'shell_plus',
    'dbshell',
    'runscript',
    'runserver',
    'console',
    'runner',
    'tinker',
    'repl',
    'exec',
    'eval',
    '-c',
    '-e',
    '--command',
})

# O comando entra sem aspas em `dokku run <app> <comando>`: nada de quebra de linha,
# NUL ou metacaracteres de shell.
DANGEROUS_FRAGMENTS = (
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
    '${',
    '\n',
    '\r',
    '\x00',
)


def is_command_allowed(command: str) -> bool:
    """Verifica se o comando e permitido (whitelist + prefixos).

    Isto limita o que a API aceita, nao e isolamento: o comando roda dentro do
    container do proprio app, cujo codigo o usuario ja controla. Serve para evitar
    que a plataforma vire um "shell remoto" generico e para manter a auditoria util.
    """
    command = command.strip()

    if any(fragment in command for fragment in DANGEROUS_FRAGMENTS):
        return False

    if command in ALLOWED_COMMANDS:
        return True

    tokens = command.split()
    if any(token in BLOCKED_TOKENS for token in tokens):
        return False

    return any(command.startswith(prefix) for prefix in ALLOWED_PREFIXES)
