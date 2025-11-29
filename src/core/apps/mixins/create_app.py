from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter, GitHubAdapter
from core.apps.models import App
from core.auth_user.models import User


class CreateAppMixin:
    """Mixin para criação de aplicações."""
    @shared_task(bind=True)
    def create_app(self, name: str, git: str, project_id: int, user: User, env_vars: dict | None = None) -> App:
        """Cria uma nova aplicação e a provisiona no servidor Dokku."""

        task = cast(Task, self)

        try:
            user = User.objects.get(id=user.id)  # type: ignore
        except User.DoesNotExist:
            raise ValueError("Usuário não encontrado")

        dokku_adapter = DokkuAdapter()
        github_adapter = GitHubAdapter()
        dokku_app_name = f"{name}_{project_id}"

        task.update_state(state='PROGRESS', meta={
        'current': 10, 'total': 100, 'status': 'Verificando existência do app...'
        })

        if dokku_adapter.exists_app(dokku_app_name):
            return App.objects.get(name=name, project_id=project_id)

        task.update_state(state='PROGRESS', meta={
        'current': 30, 'total': 100, 'status': f'Criando container {dokku_app_name}...'
        })

        dokku_adapter.create_app(app_name=dokku_app_name)

        task.update_state(state='PROGRESS', meta={
                'current': 50,
                'total': 100, 'status': 'Configurando repositório Git...'
        })

        dokku_adapter.set_git_remote(app_name=dokku_app_name, git_url=git)

        task.update_state(state='PROGRESS', meta={
        'current': 70, 'total': 100, 'status': 'Verificando permissões do GitHub...'
        })

        repo_name = git.split(".com/")[-1].replace(".git", "")
        user_git_repos_list = github_adapter.list_user_repos(user_id=user.id)  # type: ignore
        user_git_repos = {repo.full_name: {'private': repo.private} for repo in user_git_repos_list}

        if repo_name in user_git_repos and user_git_repos[repo_name].get('private', False):
            task.update_state(state='PROGRESS', meta={
            'current': 75, 'total': 100, 'status': 'Gerando chaves de acesso seguro...'
            })
            deploy_key = dokku_adapter.generate_git_deploy_key()
            github_adapter.add_deploy_key(dokku_key=deploy_key, repo_name=repo_name, user_id=user.id)  # type: ignore

        if env_vars is not None:
            task.update_state(state='PROGRESS', meta={
            'current': 90, 'total': 100, 'status': 'Aplicando variáveis de ambiente...'
            })
            dokku_adapter.set_config(app_name=dokku_app_name, env_vars=env_vars or {})

        return App.objects.create(name=name, git=git, project_id=project_id)
