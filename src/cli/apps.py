"""
Comando `fabroku apps` — Listar apps do usuário.
"""

import click

from .api import APIError, FabrokuAPI
from .config import is_authenticated


@click.command()
@click.option('--project', '-p', default=None, help='Filtrar por ID do projeto.')
def apps(project):
    """Listar seus apps na plataforma Fabroku."""
    if not is_authenticated():
        click.echo('❌ Você precisa fazer login primeiro.')
        click.echo(f'   Use: {click.style("fabroku login", bold=True)}')
        raise SystemExit(1)

    api = FabrokuAPI()

    try:
        app_list = api.list_apps()
    except APIError as e:
        if e.status_code == 401:  # noqa: PLR2004
            click.echo('❌ Token expirado ou inválido. Faça login novamente.')
            click.echo(f'   Use: {click.style("fabroku login", bold=True)}')
        else:
            click.echo(f'❌ Erro na API: {e.detail}')
        raise SystemExit(1)

    # Filtra por projeto se especificado
    if project:
        app_list = [a for a in app_list if str(a.get('project')) == str(project)]

    if not app_list:
        click.echo('Nenhum app encontrado.')
        if project:
            click.echo(f'   (filtrado por projeto: {project})')
        return

    # Exibe tabela
    click.echo(f'\n{"ID":<6} {"Nome":<25} {"Status":<12} {"Domínio":<30} {"Projeto"}')
    click.echo('─' * 90)

    for app in app_list:
        status = app.get('status', 'STOPPED')
        status_color = {
            'RUNNING': 'green',
            'STOPPED': 'red',
            'ERROR': 'red',
            'STARTING': 'yellow',
            'DEPLOYING': 'cyan',
            'DELETING': 'magenta',
        }.get(status, 'white')

        status_formatted = f'{status:<12}'
        click.echo(
            f'{str(app.get("id", "")):<6} '
            f'{app.get("name", ""):<25} '
            f'{click.style(status_formatted, fg=status_color)} '
            f'{(app.get("domain") or "-"):<30} '
            f'{str(app.get("project", ""))}'
        )

    click.echo(f'\n📦 Total: {len(app_list)} app(s)')
