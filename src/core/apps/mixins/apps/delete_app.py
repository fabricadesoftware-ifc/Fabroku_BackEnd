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
            return {'status': 'deleted', 'message': 'App already deleted from DB'}

        dokku_app_name = app.name_dokku
        task.update_state(state='PROGRESS', meta={'status': f'Removendo container {dokku_app_name}...'})

        dokku_adapter = DokkuAdapter()

        # Só tenta deletar no Dokku se o name_dokku existir
        if dokku_app_name:
            try:
                result = dokku_adapter.delete_app(app_name=dokku_app_name)
                print(f'Dokku delete result: {result}')
            except Exception as e:
                print(f'Erro ao deletar app no Dokku: {e}')
                # Continua para deletar do banco mesmo se falhar no Dokku

        app.delete()

        return {'status': 'deleted', 'app_id': app_id, 'dokku_app': dokku_app_name}
