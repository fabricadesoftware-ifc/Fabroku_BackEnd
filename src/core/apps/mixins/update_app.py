from core.adapters import DokkuAdapter
from core.apps.models import App


class UpdateAppMixin:
    """Mixin para atualização de aplicações."""

    def update_app(self, name: str, git: str, id: int, env_vars: dict | None = None) -> App:
        """Atualiza uma aplicação existente e a provisiona no servidor Dokku."""
        app = App.objects.get(id=id)

        if app.name != name:
            dokku_adapter = DokkuAdapter()
            dokku_adapter.rename_app(old_name=app.name, new_name=name)
            app.name = name
            app.save()
        if app.git != git:
            dokku_adapter = DokkuAdapter()
            dokku_adapter.set_git_remote(app_name=name, git_url=git)
            app.git = git
            app.save()
        if env_vars is not None:
            dokku_adapter = DokkuAdapter()
            dokku_adapter.set_config(app_name=name, env_vars=env_vars)
            app.variables = env_vars
            app.save()

        return app
