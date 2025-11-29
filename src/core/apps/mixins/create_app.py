import re
from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter, GitHubAdapter
from core.apps.models import App
from core.auth_user.models import User


class CreateAppMixin:
    """
    Mixin para criação de aplicações.
    Contém a task principal e métodos auxiliares estáticos para organização.
    """

    @shared_task(bind=True)
    def create_app(self, app_id: int, user_id: int, env_vars: dict | None = None) -> dict:
        """
        Orquestrador principal: Cria uma nova aplicação e a provisiona no servidor Dokku.
        """
        task = cast(Task, self)

        app, user = CreateAppMixin._get_instances(app_id, user_id)

        dokku_app_name = CreateAppMixin.slugify_dokku(f"{app.name}-{app.project.id}")
        dokku_adapter = DokkuAdapter()
        github_adapter = GitHubAdapter()

        if CreateAppMixin._ensure_dokku_app(task, dokku_adapter, app, dokku_app_name):
            return {"status": "already_exists", "app_id": app.id}  # type: ignore

        CreateAppMixin._configure_git(task, dokku_adapter, dokku_app_name, app.git)

        CreateAppMixin._handle_deploy_keys(task, dokku_adapter, github_adapter, user, app.git)

        CreateAppMixin._apply_env_vars(task, dokku_adapter, dokku_app_name, env_vars)

        app.status = 'RUNNING'
        app.save()

        return {"status": "created", "app_id": app.id}  # type: ignore

    @staticmethod
    def _get_instances(app_id: int, user_id: int) -> tuple[App, User]:
        """Busca App e User no banco de dados."""
        try:
            app = App.objects.get(id=app_id)
            user = User.objects.get(id=user_id)
            return app, user
        except App.DoesNotExist:
            raise App.DoesNotExist(f"App with id {app_id} not found")
        except User.DoesNotExist:
            raise User.DoesNotExist(f"User with id {user_id} not found")

    @staticmethod
    def _ensure_dokku_app(task: Task, adapter: DokkuAdapter, app: App, dokku_app_name: str) -> bool:
        """Cria o container se não existir. Retorna True se já existia."""
        task.update_state(state='PROGRESS', meta={
            'current': 10, 'total': 100, 'status': 'Verificando existência do app...'
        })

        if adapter.exists_app(dokku_app_name):
            return True

        task.update_state(state='PROGRESS', meta={
            'current': 30, 'total': 100, 'status': f'Criando container {dokku_app_name}...'
        })
        adapter.create_app(app_name=dokku_app_name)
        return False

    @staticmethod
    def _configure_git(task: Task, adapter: DokkuAdapter, dokku_app_name: str, git_url: str):
        """Configura o remote do Git no Dokku."""
        task.update_state(state='PROGRESS', meta={
            'current': 50, 'total': 100, 'status': 'Configurando repositório Git...'
        })
        adapter.set_git_remote(app_name=dokku_app_name, git_url=git_url)

    @staticmethod
    def _handle_deploy_keys(task: Task, d_adapter: DokkuAdapter, gh_adapter: GitHubAdapter, user: User, git_url: str):
        """Verifica permissões e gera chaves SSH se necessário."""
        task.update_state(state='PROGRESS', meta={
            'current': 70, 'total': 100, 'status': 'Verificando permissões do GitHub...'
        })

        repo_name = git_url.split(".com/")[-1].replace(".git", "")

        user_git_repos_list = gh_adapter.list_user_repos(user_id=user.id)  # type: ignore
        user_git_repos = {repo.full_name: {'private': repo.private} for repo in user_git_repos_list}

        if repo_name in user_git_repos and user_git_repos[repo_name].get('private', False):
            task.update_state(state='PROGRESS', meta={
                'current': 75, 'total': 100, 'status': 'Gerando chaves de acesso seguro...'
            })
            deploy_key = d_adapter.generate_git_deploy_key()
            gh_adapter.add_deploy_key(dokku_key=deploy_key, repo_name=repo_name, user_id=user.id)  # type: ignore

    @staticmethod
    def _apply_env_vars(task: Task, adapter: DokkuAdapter, dokku_app_name: str, env_vars: dict | None):
        """Aplica variáveis de ambiente se fornecidas."""
        if env_vars:
            task.update_state(state='PROGRESS', meta={
                'current': 90, 'total': 100, 'status': 'Aplicando variáveis de ambiente...'
            })
            adapter.set_config(app_name=dokku_app_name, env_vars=env_vars)

    @staticmethod
    def slugify_dokku(name: str) -> str:

        name = name.lower()
        name = re.sub(r'[^a-z0-9\-]', '-', name)  # Mantém apenas a-z, 0-9 e hífen
        name = re.sub(r'-+', '-', name)          # Evita hífens duplos
        name = name.strip('-')                   # Remove hífens do começo/fim
        return name
