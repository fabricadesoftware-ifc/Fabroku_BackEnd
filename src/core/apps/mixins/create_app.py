from adapters import DokkuAdapter

from core.apps.models import App


class CreateAppMixin:
    """Mixin para criação de aplicações."""

    def create_app(self, name: str, git: str, project_id: int, env_vars: dict | None = None) -> App:
        """Cria uma nova aplicação e a provisiona no servidor Dokku."""

        dokku_adapter = DokkuAdapter()
        dokku_adapter.create_app(app_name=name)
        dokku_adapter.set_git_remote(app_name=name, git_url=git)
        dokku_adapter.set_config(app_name=name, env_vars=env_vars or {})

        return App.objects.create(name=name, git=git, project_id=project_id)
