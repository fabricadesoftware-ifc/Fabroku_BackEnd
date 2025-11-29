from core.adapters import DokkuAdapter, GitHubAdapter
from core.apps.models import App
from core.auth_user.models import User


class CreateAppMixin:
    """Mixin para criação de aplicações."""

    def create_app(self, name: str, git: str, project_id: int, user: User, env_vars: dict | None = None) -> App:
        """Cria uma nova aplicação e a provisiona no servidor Dokku."""

        dokku_adapter = DokkuAdapter()
        github_adapter = GitHubAdapter()

        dokku_adapter.create_app(app_name=name)
        dokku_adapter.set_git_remote(app_name=name, git_url=git)
        repo_name = git.split(".com/")[-1].replace(".git", "")
        user_git_repos_list = github_adapter.list_user_repos(user_id=user.id)  # type: ignore
        user_git_repos = {repo.full_name: {'private': repo.private} for repo in user_git_repos_list}
        if repo_name in user_git_repos and user_git_repos[repo_name].get('private', False):
            deploy_key = dokku_adapter.generate_git_deploy_key()
            github_adapter.add_deploy_key(dokku_key=deploy_key, repo_name=repo_name, user_id=user.id)  # type: ignore

        if env_vars is not None:
            dokku_adapter.set_config(app_name=name, env_vars=env_vars or {})

        return App.objects.create(name=name, git=git, project_id=project_id)
