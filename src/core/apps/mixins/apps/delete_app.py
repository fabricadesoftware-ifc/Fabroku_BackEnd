from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import App, Service, ServiceType


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

        # Primeiro, limpa os serviços vinculados ao app
        services = Service.objects.filter(app=app)
        for service in services:
            dokku_service_name = service.container_name or service.name
            try:
                if service.service_type == ServiceType.POSTGRES and dokku_app_name:
                    dokku_adapter.unlink_database(db_name=dokku_service_name, app_name=dokku_app_name)
                    dokku_adapter.delete_database(db_name=dokku_service_name)
            except Exception as e:
                print(f'Erro ao deletar serviço {dokku_service_name}: {e}')
            service.delete()

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
