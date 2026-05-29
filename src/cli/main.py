"""
Fabroku CLI — Ponto de entrada principal.

Uso:
    fabroku login          Autenticar via GitHub
    fabroku logout         Encerrar sessão
    fabroku verify         Verificar arquivos de deploy
    fabroku apps           Listar apps
    fabroku whoami         Verificar usuário logado
"""

import click

from .api import APIError, FabrokuAPI
from .auth import login, logout
from .config import is_authenticated, load_config
from .verify import verify


@click.group()
@click.version_option(version='0.1.0', prog_name='fabroku')
def cli():
    """🚀 Fabroku CLI — Ferramenta de deploy para o Fabroku PaaS."""
    pass


# Registra comandos
cli.add_command(login)
cli.add_command(logout)
cli.add_command(verify)

# Import lazy para evitar circular
from .apps import apps  # noqa: E402

cli.add_command(apps)


@cli.command()
def whoami():
    """Verificar o usuário autenticado."""
    if not is_authenticated():
        click.echo('❌ Não autenticado.')
        click.echo(f'   Use: {click.style("fabroku login", bold=True)}')
        raise SystemExit(1)

    config = load_config()
    click.echo(f'👤 Logado como: {click.style(config.get("user", "?"), fg="green", bold=True)}')
    click.echo(f'   API: {config.get("api_url")}')

    # Verifica se o token ainda é válido
    try:
        api = FabrokuAPI()
        user_data = api.get_user_me()
        click.echo(f'   Email: {user_data.get("email")}')
        if user_data.get('is_fabric'):
            click.echo(f'   🏭 Perfil privilegiado')
        if user_data.get('is_superuser'):
            click.echo(f'   🔑 Administrador')
        click.echo(f'   ✅ Token válido')
    except APIError as e:
        if e.status_code == 401:  # noqa: PLR2004
            click.echo(f'   ❌ Token expirado ou inválido')
        else:
            click.echo(f'   ⚠️  Erro ao verificar: {e.detail}')


def main():
    cli()


if __name__ == '__main__':
    main()
