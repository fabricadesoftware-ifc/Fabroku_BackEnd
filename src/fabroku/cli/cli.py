from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Optional, Any, Dict

import click
from dotenv import load_dotenv

from fabroku.application.use_cases import (
	# CreateAppUseCase, # Removido
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
	# ListAppsUseCase, # Removido
	CreateProjectUseCase,
	GetProjectStatusUseCase,
	ProjectStatus,
	ListProjectsUseCase,
	GetAppLogsUseCase,
	GetDeployLogsUseCase,
)
from fabroku.infrastructure.adapters.dokku_shell_adapter import DokkuShellAdapter
from fabroku.application.use_cases.auth import AuthService
from fabroku.infrastructure.session import load_session, save_session, clear_session
from fabroku.infrastructure.user_store import get_or_create_user_tag
from fabroku.infrastructure.django_bootstrap import setup_django


# Carrega variáveis de ambiente do arquivo .env, se existir.
load_dotenv()


def _build_default_services():
	dokku = DokkuShellAdapter()
	from core.project.infra.project_django_app.models import Projeto, Network # lazy import
	from core.user.infra.user_django_app.models import User # lazy import
	return {
		"dokku": dokku,
		"create_project": CreateProjectUseCase(dokku, Projeto, User, Network),
		"deploy": DeployAppUseCase(dokku, Projeto),
		"delete": DeleteAppUseCase(dokku, Projeto, User),
		"plugin_install": InstallPluginUseCase(dokku),
		"pg_create": CreatePostgresUseCase(dokku),
		"pg_link": LinkPostgresUseCase(dokku),
		"rmq_create": CreateRabbitMQUseCase(dokku),
		"rmq_link": LinkRabbitMQUseCase(dokku),
		"config_set": ConfigSetUseCase(dokku),
		"ports_set": ProxyPortsSetUseCase(dokku),

		"ports_clear": ProxyPortsClearUseCase(dokku),
		"smart_deploy": SmartDeployUseCase(dokku),
		"list_projects": ListProjectsUseCase(dokku, Projeto),
		"get_project_status": GetProjectStatusUseCase(Projeto),
		"get_app_logs": GetAppLogsUseCase(dokku),
		"get_deploy_logs": GetDeployLogsUseCase(dokku),
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


@cli.group("project")
def project_group() -> None:
	pass


@project_group.command("create")
@click.option("--name", type=str, required=True, help="Nome do projeto/app (único no Dokku)")
@click.option("--tecnologia", type=click.Choice(['Vue', 'Django']), required=True, help="Tecnologia principal do projeto")
@click.option("--porta", type=int, required=True, help="Porta da aplicação (ex: 8000)")
@click.option("--source-url", type=str, required=True, help="URL da fonte (repo Git ou imagem Docker)")
@click.option("--source-type", type=click.Choice(['git', 'docker_image']), required=True, help="Tipo da fonte (git ou docker_image)")
@click.option("--network", type=str, default="default", help="Nome da rede a ser vinculada (padrão: default)")
@click.option("--descricao", type=str, default="", help="Descrição opcional do projeto")
@click.option("--env", "initial_env", type=str, multiple=True, help="Variáveis de ambiente (KEY=VALUE)")
def project_create_cmd(
	name: str,
	tecnologia: str,
	porta: int,
	source_url: str,
	source_type: str,
	network: str,
	descricao: str,
	initial_env: list[str],
) -> None:
	session = load_session()
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)

	services = _build_default_services()
	parsed_env: dict[str, str] = {k: v for item in initial_env for k, v in [item.split("=", 1)]}
	parsed_env["FABROKU_TAG"] = get_or_create_user_tag(session.email)

	result = services["create_project"].execute(
		app_name=name,
		user_email=session.email,
		nome=name,
		descricao=descricao,
		tecnologia=tecnologia,
		source_type=source_type,
		source_url=source_url,
		network_name=network,
		porta=porta,
		variaveis_ambiente=parsed_env,
	)
	click.echo(result.message)


@project_group.command("list")
@click.option("--tag", type=str, default=None, help="Filtra por FABROKU_TAG; padrão: tag do usuário autenticado")
@click.option("--all", "include_all", is_flag=True, default=False, help="Lista todos os projetos (ignora filtro de tag)")
def project_list_cmd(tag: Optional[str], include_all: bool) -> None:
	session = load_session()
	if not include_all and not tag:
		if not session:
			click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
			raise SystemExit(1)
		tag = get_or_create_user_tag(session.email)
	services = _build_default_services()
	use_case: ListProjectsUseCase = services["list_projects"]
	projects = use_case.execute(tag=tag, include_all=include_all)
	for name in projects:
		click.echo(name)


@project_group.command("destroy")
@click.argument("project_name", type=str)
def project_destroy_cmd(project_name: str) -> None:
	session = load_session()
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)

	services = _build_default_services()
	# Verifica ownership e pede confirmação
	tag_cfg = services["dokku"].config_get(project_name, "FABROKU_TAG")
	effective_tag = get_or_create_user_tag(session.email)
	if (not tag_cfg.success) or ((tag_cfg.message or "").strip() != effective_tag):
		click.echo("Permissão negada: você não é o owner deste projeto", err=True)
		raise SystemExit(1)

	if not click.confirm(f"ATENÇÃO: Isso irá DESTRUIR o projeto {project_name}. Tem certeza? Para prosseguir, digite \"{project_name}\"", confirmation_prompt=True, default=False, abort=True):
		raise SystemExit(0)

	result = services["delete"].execute(app_name=project_name)
	click.echo(result.message)


@cli.command("deploy") # Mantido como comando de nível superior por simplicidade no primeiro momento, pode ser movido para project <name> deploy
@click.argument("app_name", type=str)
def deploy_cmd(app_name: str) -> None:
	session = load_session() # Adicionar verificação de sessão para deploy e smart-deploy
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
	services = _build_default_services()
	use_case = services["deploy"]

	# Buscar informações do projeto no banco de dados
	try:
		project_model = use_case._Projeto.objects.get(nome=app_name, usuario__email=session.email)
	except use_case._Projeto.DoesNotExist:
		click.echo(f"Projeto '{app_name}' não encontrado ou você não tem permissão.", err=True)
		raise SystemExit(1)

	# Determinar qual tipo de deploy fazer
	git_url = project_model.source_url if project_model.source_type == "git" else None
	image = project_model.source_url if project_model.source_type == "docker_image" else None
	# TODO: Adicionar lógica para buildpack se for um campo no modelo Projeto
	buildpack = None # Por enquanto, mantém como None

	result = use_case.execute(app_name=app_name, git_url=git_url, image=image, buildpack=buildpack)
	click.echo(result.message)


@cli.command("smart-deploy") # Mantido como comando de nível superior por simplicidade no primeiro momento, pode ser movido para project <name> smart-deploy
@click.argument("app_name", type=str)
@click.option("--git-url", type=str, required=True, help="URL do repositório git (pode incluir #branch)")
@click.option("--buildpack", type=str, default=None)
@click.option("--log", "log_to_stderr", is_flag=True, default=False, help="Imprime logs de acompanhamento no stderr")
def smart_deploy_cmd(app_name: str, git_url: str, buildpack: Optional[str], log_to_stderr: bool) -> None:
	session = load_session() # Adicionar verificação de sessão para deploy e smart-deploy
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
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


@project_group.command("status")
@click.argument("project_name", type=str)
def project_status_cmd(project_name: str) -> None:
	session = load_session()
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
	services = _build_default_services()

	# Busca o projeto no banco de dados
	from core.project.infra.project_django_app.models import Projeto # lazy import
	try:
		projeto = Projeto.objects.get(nome=project_name, usuario__email=session.email)
	except Projeto.DoesNotExist:
		click.echo(f"Projeto '{project_name}' não encontrado ou você não tem permissão.", err=True)
		raise SystemExit(1)

	# Formata a saída
	name = projeto.nome
	ready_status = "1/1" if projeto.status in ['pronto', 'em_andamento'] else "0/1"
	estado = projeto.status.capitalize() # Capitaliza a primeira letra
	age = (datetime.now(timezone.utc) - projeto.data_criacao).total_seconds()
	age_minutes = int(age / 60)
	age_str = f"{age_minutes}m" # Formato simples por enquanto

	click.echo(f"{{'NAME':<12}} {{'READY':<8}} {{'ESTADO':<12}} {{'AGE':<8}}")
	click.echo(f"{name:<12} {ready_status:<8} {estado:<12} {age_str:<8}")


@cli.group("config") # Mantive config e ports fora de project, para que possam ser usados para configurar o dokku como um todo
def config_group() -> None:
	pass


@config_group.command("set")
@click.argument("app_name", type=str)
@click.option("--env", "env_items", type=str, multiple=True, help="KEY=VALUE")
def config_set_cmd(app_name: str, env_items: list[str]) -> None:
	session = load_session() # Adicionar verificação de sessão para deploy e smart-deploy
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
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


@cli.group("ports") # Mantive config e ports fora de project, para que possam ser usados para configurar o dokku como um todo
def ports_group() -> None:
	pass


@ports_group.command("set")
@click.argument("app_name", type=str)
@click.option("--map", "mappings", type=str, multiple=True, help="http:80:5000")
def ports_set_cmd(app_name: str, mappings: list[str]) -> None:
	session = load_session() # Adicionar verificação de sessão para deploy e smart-deploy
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
	services = _build_default_services()
	result = services["ports_set"].execute(app_name=app_name, mappings=list(mappings))
	click.echo(result.message)


@ports_group.command("add")
@click.argument("app_name", type=str)
@click.option("--map", "mappings", type=str, multiple=True, help="http:8080:5000")
def ports_add_cmd(app_name: str, mappings: list[str]) -> None:
	session = load_session() # Adicionar verificação de sessão para deploy e smart-deploy
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
	services = _build_default_services()
	result = services["ports_add"].execute(app_name=app_name, mappings=list(mappings))
	click.echo(result.message)


@ports_group.command("clear")
@click.argument("app_name", type=str)
def ports_clear_cmd(app_name: str) -> None:
	session = load_session() # Adicionar verificação de sessão para deploy e smart-deploy
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
	services = _build_default_services()
	use_case = services["ports_clear"]
	result = use_case.execute(app_name=app_name)
	click.echo(result.message)


@cli.group("plugin") # Plugins também pode ser de nível superior
def plugin_group() -> None:
	pass


@plugin_group.command("install")
@click.argument("plugin_git_url", type=str)
@click.option("--name", type=str, default=None)
def plugin_install_cmd(plugin_git_url: str, name: Optional[str]) -> None:
	session = load_session() # Adicionar verificação de sessão para deploy e smart-deploy
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
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
	session = load_session() # Adicionar verificação de sessão para deploy e smart-deploy
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
	services = _build_default_services()
	result = services["pg_create"].execute(service_name=service_name, options=list(options))
	click.echo(result.message)


@postgres_group.command("link")
@click.argument("service_name", type=str)
@click.argument("app_name", type=str)
def postgres_link_cmd(service_name: str, app_name: str) -> None:
	session = load_session() # Adicionar verificação de sessão para deploy e smart-deploy
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
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
	session = load_session() # Adicionar verificação de sessão para deploy e smart-deploy
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
	services = _build_default_services()
	result = services["rmq_create"].execute(service_name=service_name, options=list(options))
	click.echo(result.message)


@rabbitmq_group.command("link")
@click.argument("service_name", type=str)
@click.argument("app_name", type=str)
def rabbitmq_link_cmd(service_name: str, app_name: str) -> None:
	session = load_session() # Adicionar verificação de sessão para deploy e smart-deploy
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
	services = _build_default_services()
	result = services["rmq_link"].execute(service_name=service_name, app_name=app_name)
	click.echo(result.message)


@cli.command("logs")
@click.argument("app_name", type=str)
@click.option("--tail", type=int, default=50, help="Número de linhas para exibir do final dos logs (padrão: 50).")
def logs_cmd(app_name: str, tail: int) -> None:
	session = load_session()
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
	services = _build_default_services()
	use_case: GetAppLogsUseCase = services["get_app_logs"]
	result = use_case.execute(app_name=app_name, tail=tail)
	if result.success:
		click.echo(result.message)
	else:
		click.echo(f"Erro ao obter logs: {result.message}", err=True)


@cli.command("deploy-logs")
@click.argument("app_name", type=str)
def deploy_logs_cmd(app_name: str) -> None:
	session = load_session()
	if not session:
		click.echo("Você precisa estar autenticado. Execute 'fabroku auth login' ou crie uma conta com 'fabroku auth register'", err=True)
		raise SystemExit(1)
	services = _build_default_services()
	use_case: GetDeployLogsUseCase = services["get_deploy_logs"]
	result = use_case.execute(app_name=app_name)
	if result.success:
		click.echo(result.message)
	else:
		click.echo(f"Erro ao obter logs de deploy: {result.message}", err=True)


def main() -> int:
	try:
		setup_django()
		cli(standalone_mode=True)
		return 0
	except SystemExit as exc:  # Click usa SystemExit
		return int(getattr(exc, "code", 1))


