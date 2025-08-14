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
	SmartDeployUseCase,
	ListAppsUseCase,
)
from fabroku.infrastructure.adapters.dokku_shell_adapter import DokkuShellAdapter
from fabroku.application.use_cases.auth import AuthService
from fabroku.infrastructure.session import load_session, save_session, clear_session
from fabroku.infrastructure.user_store import get_or_create_user_tag


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

		"ports_clear": ProxyPortsClearUseCase(dokku),
		"smart_deploy": SmartDeployUseCase(dokku),
		"apps_list": ListAppsUseCase(dokku),
	}


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="Fabroku")
def cli() -> None:
	"""
	Fabroku - CLI de abstração para Dokku.

	- Não chama Dokku diretamente da CLI: usa casos de uso e serviços do domínio.
	- Para integração com Django, forneça um adapter que implemente a port `DokkuService`.
	"""


@cli.group("auth")
def auth_group() -> None:
	pass


@auth_group.command("register")
def auth_register_cmd() -> None:
	click.echo("Cadastro de usuário")
	name = click.prompt("Nome", type=str)
	email = click.prompt("Email", type=str)
	password = click.prompt("Senha", hide_input=True, confirmation_prompt=True)
	service = AuthService()
	user = service.register(name=name, email=email, password=password)
	click.echo(f"Usuário criado: {user.name} <{user.email}>")


@auth_group.command("login")
def auth_login_cmd() -> None:
	click.echo("Login")
	email = click.prompt("Email", type=str)
	password = click.prompt("Senha", hide_input=True)
	service = AuthService()
	user = service.login(email=email, password=password)
	if not user:
		click.echo("Credenciais inválidas", err=True)
		raise SystemExit(1)
	save_session(email=user.email)
	click.echo(f"Autenticado como {user.name} <{user.email}>")


@auth_group.command("whoami")
def auth_whoami_cmd() -> None:
	session = load_session()
	if not session:
		click.echo("Não autenticado")
		return
	service = AuthService()
	user = service.get_user(session.email)
	if not user:
		click.echo("Sessão inválida")
		return
	click.echo(f"{user.name} <{user.email}>")


@auth_group.command("logout")
def auth_logout_cmd() -> None:
	clear_session()
	click.echo("Sessão encerrada")


@cli.group("apps")
def apps_group() -> None:
	pass


@apps_group.command("list")
@click.option("--tag", type=str, default=None, help="Filtra por FABROKU_TAG; padrão: tag do usuário autenticado")
@click.option("--all", "include_all", is_flag=True, default=False, help="Lista todas as apps (ignora filtro de owner)")
def apps_list_cmd(tag: Optional[str], include_all: bool) -> None:
	session = load_session()
	if not include_all and not tag:
		if not session:
			click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
			raise SystemExit(1)
		tag = get_or_create_user_tag(session.email)
	services = _build_default_services()
	use_case: ListAppsUseCase = services["apps_list"]
	apps = use_case.execute(tag=tag, include_all=include_all)
	for name in apps:
		click.echo(name)


@cli.command("create-app")
@click.argument("app_name", type=str)
@click.option("--initial-env", type=str, default=None, help="JSON com variáveis de ambiente iniciais")
def create_app_cmd(app_name: str, initial_env: Optional[str]) -> None:
	session = load_session()
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
	services = _build_default_services()
	parsed_env = {}
	if initial_env:
		parsed_env = json.loads(initial_env)
	# Enforce tag única de owner (política: enquanto não temos emissão de token próprio, usamos o email como tag; abaixo geramos FABROKU_TAG)
	parsed_env["FABROKU_TAG"] = parsed_env.get("FABROKU_TAG") or get_or_create_user_tag(session.email)
	# Persistir a tag no ambiente da app para filtros posteriores
	result = services["create"].execute(app_name=app_name, initial_environment=parsed_env)
	click.echo(result.message)


@cli.command("delete-app")
@click.argument("app_name", type=str)
@click.option("--force", is_flag=True, default=False)
def delete_app_cmd(app_name: str, force: bool) -> None:
	session = load_session()
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
	services = _build_default_services()
	# Verifica ownership: app deve conter FABROKU_TAG e deve coincidir com a tag informada (padrão: email como tag)
	tag_cfg = services["dokku"].config_get(app_name, "FABROKU_TAG")
	effective_tag = get_or_create_user_tag(session.email)
	if (not tag_cfg.success) or ((tag_cfg.message or "").strip() != effective_tag):
		click.echo("Permissão negada: você não é o owner desta app", err=True)
		raise SystemExit(1)
	result = services["delete"].execute(app_name=app_name, force=force)
	click.echo(result.message)


@cli.command("deploy")
@click.argument("app_name", type=str)
@click.option("--git-url", type=str, default=None)
@click.option("--image", type=str, default=None)
@click.option("--buildpack", type=str, default=None)
def deploy_cmd(app_name: str, git_url: Optional[str], image: Optional[str], buildpack: Optional[str]) -> None:
	services = _build_default_services()
	use_case = services["deploy"]
	result = use_case.execute(app_name=app_name, git_url=git_url, image=image, buildpack=buildpack)
	click.echo(result.message)


@cli.command("smart-deploy")
@click.argument("app_name", type=str)
@click.option("--git-url", type=str, required=True, help="URL do repositório git (pode incluir #branch)")
@click.option("--buildpack", type=str, default=None)
@click.option("--log", "log_to_stderr", is_flag=True, default=False, help="Imprime logs de acompanhamento no stderr")
def smart_deploy_cmd(app_name: str, git_url: str, buildpack: Optional[str], log_to_stderr: bool) -> None:
	services = _build_default_services()
	use_case: SmartDeployUseCase = services["smart_deploy"]

	# Implementação simples de sync local de estado (sem Django)
	class _LocalState:
		def set_status(self, s: str) -> None:
			if log_to_stderr:
				click.echo(f"status={s}", err=True)
		def set_analysis(self, a):
			if log_to_stderr:
				click.echo(f"analysis={json.dumps(a)}", err=True)
		def append_log(self, line: str) -> None:
			if log_to_stderr:
				click.echo(line, err=True)
		def set_error(self, err_msg: str) -> None:
			if log_to_stderr:
				click.echo(f"error={err_msg}", err=True)

	result = use_case.execute(app_name=app_name, git_url=git_url, state_sync=_LocalState(), buildpack=buildpack)
	click.echo(result.message)


@cli.group("plugin")
def plugin_group() -> None:
	pass


@plugin_group.command("install")
@click.argument("plugin_git_url", type=str)
@click.option("--name", type=str, default=None)
def plugin_install_cmd(plugin_git_url: str, name: Optional[str]) -> None:
	services = _build_default_services()
	result = services["plugin_install"].execute(plugin_git_url=plugin_git_url, name=name)
	click.echo(result.message)


@cli.group("postgres")
def postgres_group() -> None:
	pass


@postgres_group.command("create")
@click.argument("service_name", type=str)
@click.option("--option", "options", type=str, multiple=True)
def postgres_create_cmd(service_name: str, options: list[str]) -> None:
	services = _build_default_services()
	result = services["pg_create"].execute(service_name=service_name, options=list(options))
	click.echo(result.message)


@postgres_group.command("link")
@click.argument("service_name", type=str)
@click.argument("app_name", type=str)
def postgres_link_cmd(service_name: str, app_name: str) -> None:
	services = _build_default_services()
	result = services["pg_link"].execute(service_name=service_name, app_name=app_name)
	click.echo(result.message)


@cli.group("rabbitmq")
def rabbitmq_group() -> None:
	pass


@rabbitmq_group.command("create")
@click.argument("service_name", type=str)
@click.option("--option", "options", type=str, multiple=True)
def rabbitmq_create_cmd(service_name: str, options: list[str]) -> None:
	services = _build_default_services()
	result = services["rmq_create"].execute(service_name=service_name, options=list(options))
	click.echo(result.message)


@rabbitmq_group.command("link")
@click.argument("service_name", type=str)
@click.argument("app_name", type=str)
def rabbitmq_link_cmd(service_name: str, app_name: str) -> None:
	services = _build_default_services()
	result = services["rmq_link"].execute(service_name=service_name, app_name=app_name)
	click.echo(result.message)


@cli.group("config")
def config_group() -> None:
	pass


@config_group.command("set")
@click.argument("app_name", type=str)
@click.option("--env", "env_items", type=str, multiple=True, help="KEY=VALUE")
def config_set_cmd(app_name: str, env_items: list[str]) -> None:
	services = _build_default_services()
	env: dict[str, str] = {}
	for item in env_items:
		if "=" not in item:
			click.echo(f"Ignorando item inválido: {item}", err=True)
			continue
		k, v = item.split("=", 1)
		env[k] = v
	result = services["config_set"].execute(app_name=app_name, env_vars=env)
	click.echo(result.message)


@cli.group("ports")
def ports_group() -> None:
	pass


@ports_group.command("set")
@click.argument("app_name", type=str)
@click.option("--map", "mappings", type=str, multiple=True, help="http:80:5000")
def ports_set_cmd(app_name: str, mappings: list[str]) -> None:
	services = _build_default_services()
	result = services["ports_set"].execute(app_name=app_name, mappings=list(mappings))
	click.echo(result.message)


@ports_group.command("add")
@click.argument("app_name", type=str)
@click.option("--map", "mappings", type=str, multiple=True, help="http:8080:5000")
def ports_add_cmd(app_name: str, mappings: list[str]) -> None:
	services = _build_default_services()
	result = services["ports_add"].execute(app_name=app_name, mappings=list(mappings))
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


