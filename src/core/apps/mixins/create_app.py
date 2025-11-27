from adapters import DokkuAdapter

from core.apps.models import App


def create_app(name: str, git: str, project_id: int) -> App:
    """Cria uma nova aplicação e a provisiona no servidor Dokku."""
    app = App.objects.create(name=name, git=git, project_id=project_id)

    dokku_adapter = DokkuAdapter()
    dokku_adapter.create_app(app_name=app.name)
    dokku_adapter.set_git_remote(app_name=app.name, git_url=app.git)

    return app
