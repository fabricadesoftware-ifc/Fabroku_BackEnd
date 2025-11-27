from adapters import DokkuAdapter

from core.apps.models import App


class DeleteAppMixin:
    """Mixin para exclusão de aplicações."""

    def delete_app(self, id: int) -> App:
        """Cria uma nova aplicação e a provisiona no servidor Dokku."""
        app = App.objects.get(id=id)

        dokku_adapter = DokkuAdapter()
        dokku_adapter.delete_app(app_name=app.name)

        app.delete()

        return app
