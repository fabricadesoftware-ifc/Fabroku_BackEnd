from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import App


class DeleteAppMixin:
    """Mixin para exclusão de aplicações via Celery."""

    @shared_task(bind=True)
    def delete_app(self, app_id: int) -> dict:
        task = cast(Task, self)

        try:
            app = App.objects.get(id=app_id)
        except App.DoesNotExist:
            return {"status": "deleted", "message": "App already deleted from DB"}

        task.update_state(state='PROGRESS', meta={'status': f'Removendo container {app.name}...'})

        dokku_adapter = DokkuAdapter()
        try:
            dokku_adapter.delete_app(app_name=f"{app.name}_{app.project.name}")

        except Exception:
            # TODO: fazer erro
            pass

        app.delete()

        return {"status": "deleted", "app_id": app_id}
