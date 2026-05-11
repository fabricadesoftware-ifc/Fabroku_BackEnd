from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import App
from core.apps.utils import slugify_dokku


class UpdateAppMixin:
    """Mixin para atualização de aplicações via Celery."""

    @shared_task(bind=True)
    def update_app(
        self, app_id: int, name: str | None = None, git: str | None = None, env_vars: dict | None = None
    ) -> dict:  # noqa: E501
        task = cast(Task, self)

        try:
            app = App.objects.get(id=app_id, deleted_at__isnull=True)
        except App.DoesNotExist:
            return {'status': 'error', 'message': 'App not found'}

        dokku_adapter = DokkuAdapter()

        if not app.name_dokku:
            return {'status': 'error', 'message': 'App without dokku name'}

        app.status = 'DEPLOYING'
        app.task_id = task.request.id
        app.save(update_fields=['status', 'task_id'])

        if name and app.name != name:
            task.update_state(state='PROGRESS', meta={'status': f'Renomeando para {name}...'})
            new_dokku_name = slugify_dokku(name)
            dokku_adapter.rename_app(old_name=app.name_dokku, new_name=new_dokku_name)
            app.name = name
            app.name_dokku = new_dokku_name
            app.save()

        if git and app.git != git:
            task.update_state(state='PROGRESS', meta={'status': 'Atualizando remote Git...'})
            dokku_adapter.set_git_remote(app_name=app.name_dokku, git_url=git)
            app.git = git
            app.save()

        if env_vars is not None:
            task.update_state(state='PROGRESS', meta={'status': 'Atualizando variáveis de ambiente...'})
            dokku_adapter.set_config(app_name=app.name_dokku, env_vars=env_vars)
            app.variables = env_vars
            app.save()

        app.status = 'RUNNING'
        app.save()

        return {'status': 'updated', 'app_id': app.id}  # type: ignore
