from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import App


class UpdateAppMixin:
    """Mixin para atualização de aplicações via Celery."""

    @shared_task(bind=True)
    def update_app(
        self, app_id: int, name: str | None = None, git: str | None = None, env_vars: dict | None = None
    ) -> dict:  # noqa: E501
        task = cast(Task, self)

        try:
            app = App.objects.get(id=app_id)
        except App.DoesNotExist:
            return {'status': 'error', 'message': 'App not found'}

        dokku_adapter = DokkuAdapter()

        if name and app.name != name:
            task.update_state(state='PROGRESS', meta={'status': f'Renomeando para {name}...'})
            dokku_adapter.rename_app(old_name=app.name, new_name=name)
            app.name = name
            app.save()

        if git and app.git != git:
            task.update_state(state='PROGRESS', meta={'status': 'Atualizando remote Git...'})
            dokku_adapter.set_git_remote(app_name=app.name, git_url=git)
            app.git = git
            app.save()

        if env_vars is not None:
            task.update_state(state='PROGRESS', meta={'status': 'Atualizando variáveis de ambiente...'})
            dokku_adapter.set_config(app_name=app.name, env_vars=env_vars)
            app.variables = env_vars
            app.save()

        return {'status': 'updated', 'app_id': app.id}  # type: ignore
