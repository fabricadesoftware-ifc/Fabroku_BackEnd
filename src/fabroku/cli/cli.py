from __future__ import annotations

import json
import sys
from typing import Optional

import click
from dotenv import load_dotenv

from fabroku.application.use_cases import (
    CreateAppUseCase,
    DeleteAppUseCase,
    DeployAppUseCase,
    InstallPluginUseCase,
    CreatePostgresUseCase,
    LinkPostgresUseCase,
    CreateRabbitMQUseCase,
    LinkRabbitMQUseCase,
    ConfigSetUseCase,
    ProxyPortsSetUseCase,
    ProxyPortsAddUseCase,
    ProxyPortsClearUseCase,
)
from fabroku.infrastructure.adapters.dokku_shell_adapter import DokkuShellAdapter


# Carrega variáveis de ambiente do arquivo .env, se existir.
load_dotenv()


def _build_default_services():
    dokku = DokkuShellAdapter()
    return {
        "dokku": dokku,
        "create": CreateAppUseCase(dokku),
        "deploy": DeployAppUseCase(dokku),
        "delete": DeleteAppUseCase(dokku),
        "plugin_install": InstallPluginUseCase(dokku),
        "pg_create": CreatePostgresUseCase(dokku),
        "pg_link": LinkPostgresUseCase(dokku),
        "rmq_create": CreateRabbitMQUseCase(dokku),
        "rmq_link": LinkRabbitMQUseCase(dokku),
        "config_set": ConfigSetUseCase(dokku),
        "ports_set": ProxyPortsSetUseCase(dokku),
        "ports_add": ProxyPortsAddUseCase(dokku),
        "ports_clear": ProxyPortsClearUseCase(dokku),
    }


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="Fabroku")
def cli() -> None:
    """
    Fabroku - CLI de abstração para Dokku.

    - Não chama Dokku diretamente da CLI: usa casos de uso e serviços do domínio.
    - Para integração com Django, forneça um adapter que implemente a port `DokkuService`.
    """


@cli.command("create-app")
@click.argument("app_name", type=str)
@click.option("--initial-env", type=str, default=None, help="JSON com variáveis de ambiente iniciais")
def create_app_cmd(app_name: str, initial_env: Optional[str]) -> None:
    """Cria uma aplicação no Dokku."""
    services = _build_default_services()
    create_use_case = services["create"]

    env_vars = None
    if initial_env:
        try:
            env_vars = json.loads(initial_env)
        except json.JSONDecodeError as exc:  # pragma: no cover - validação simples de CLI
            click.echo(f"Formato de JSON inválido para --initial-env: {exc}", err=True)
            raise SystemExit(2)

    result = create_use_case.execute(app_name=app_name, initial_environment=env_vars)
    click.echo(result.message)


@cli.command("deploy")
@click.argument("app_name", type=str)
@click.option("--git-url", type=str, help="URL do repositório Git para deploy (se aplicável)")
@click.option("--image", type=str, help="Imagem Docker (ex: usuario/repo:tag)")
@click.option("--buildpack", type=str, default=None, help="Buildpack a ser usado (opcional)")
def deploy_cmd(app_name: str, git_url: Optional[str], image: Optional[str], buildpack: Optional[str]) -> None:
    """Realiza o deploy de uma aplicação no Dokku."""
    services = _build_default_services()
    deploy_use_case = services["deploy"]
    result = deploy_use_case.execute(
        app_name=app_name,
        git_url=git_url,
        image=image,
        buildpack=buildpack,
    )
    click.echo(result.message)


@cli.command("delete-app")
@click.argument("app_name", type=str)
@click.option("--force/--no-force", default=True, help="Força a exclusão sem prompt (padrão: --force)")
def delete_app_cmd(app_name: str, force: bool) -> None:
    """Deleta uma aplicação no Dokku."""
    services = _build_default_services()
    delete_use_case = services["delete"]
    result = delete_use_case.execute(app_name=app_name, force=force)
    click.echo(result.message)


@cli.group("plugin")
def plugin_group() -> None:
    """Gerencia plugins do Dokku."""


@plugin_group.command("install")
@click.argument("plugin_git_url", type=str)
@click.option("--name", type=str, default=None, help="Nome do plugin (opcional)")
def plugin_install_cmd(plugin_git_url: str, name: Optional[str]) -> None:
    services = _build_default_services()
    use_case = services["plugin_install"]
    result = use_case.execute(plugin_git_url=plugin_git_url, name=name)
    click.echo(result.message)


@cli.group("postgres")
def postgres_group() -> None:
    """Gerencia serviço Postgres no Dokku."""


@postgres_group.command("create")
@click.argument("service_name", type=str)
@click.option("--option", "options", multiple=True, help="Opções extras para criação (pode repetir)")
def postgres_create_cmd(service_name: str, options: tuple[str, ...]) -> None:
    services = _build_default_services()
    use_case = services["pg_create"]
    result = use_case.execute(service_name=service_name, options=list(options) or None)
    click.echo(result.message)


@postgres_group.command("link")
@click.argument("service_name", type=str)
@click.argument("app_name", type=str)
def postgres_link_cmd(service_name: str, app_name: str) -> None:
    services = _build_default_services()
    use_case = services["pg_link"]
    result = use_case.execute(service_name=service_name, app_name=app_name)
    click.echo(result.message)


@cli.group("rabbitmq")
def rabbitmq_group() -> None:
    """Gerencia serviço RabbitMQ no Dokku."""


@rabbitmq_group.command("create")
@click.argument("service_name", type=str)
@click.option("--option", "options", multiple=True, help="Opções extras para criação (pode repetir)")
def rabbitmq_create_cmd(service_name: str, options: tuple[str, ...]) -> None:
    services = _build_default_services()
    use_case = services["rmq_create"]
    result = use_case.execute(service_name=service_name, options=list(options) or None)
    click.echo(result.message)


@rabbitmq_group.command("link")
@click.argument("service_name", type=str)
@click.argument("app_name", type=str)
def rabbitmq_link_cmd(service_name: str, app_name: str) -> None:
    services = _build_default_services()
    use_case = services["rmq_link"]
    result = use_case.execute(service_name=service_name, app_name=app_name)
    click.echo(result.message)


@cli.group("config")
def config_group() -> None:
    """Gerencia variáveis de ambiente da app."""


@config_group.command("set")
@click.argument("app_name", type=str)
@click.option("--env", "env_items", multiple=True, help="Par chave=valor (pode repetir)")
def config_set_cmd(app_name: str, env_items: tuple[str, ...]) -> None:
    services = _build_default_services()
    use_case = services["config_set"]
    env_vars: dict[str, str] = {}
    for item in env_items:
        if "=" not in item:
            click.echo(f"Ignorando item inválido: {item}", err=True)
            continue
        k, v = item.split("=", 1)
        env_vars[k] = v
    result = use_case.execute(app_name=app_name, env_vars=env_vars)
    click.echo(result.message)


@cli.group("ports")
def ports_group() -> None:
    """Gerencia mapeamentos de portas (dokku proxy)."""


@ports_group.command("set")
@click.argument("app_name", type=str)
@click.option("--map", "mappings", multiple=True, help="Ex.: http:80:5000 (pode repetir)")
def ports_set_cmd(app_name: str, mappings: tuple[str, ...]) -> None:
    services = _build_default_services()
    use_case = services["ports_set"]
    result = use_case.execute(app_name=app_name, mappings=list(mappings))
    click.echo(result.message)


@ports_group.command("add")
@click.argument("app_name", type=str)
@click.option("--map", "mappings", multiple=True, help="Ex.: http:80:5000 (pode repetir)")
def ports_add_cmd(app_name: str, mappings: tuple[str, ...]) -> None:
    services = _build_default_services()
    use_case = services["ports_add"]
    result = use_case.execute(app_name=app_name, mappings=list(mappings))
    click.echo(result.message)


@ports_group.command("clear")
@click.argument("app_name", type=str)
def ports_clear_cmd(app_name: str) -> None:
    services = _build_default_services()
    use_case = services["ports_clear"]
    result = use_case.execute(app_name=app_name)
    click.echo(result.message)


def main() -> int:
    try:
        cli(standalone_mode=True)
        return 0
    except SystemExit as exc:  # Click usa SystemExit
        return int(getattr(exc, "code", 1))


