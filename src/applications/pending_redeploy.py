"""Redeploy pendente: push do GitHub que chegou com o app ocupado.

Antes o webhook disparava o deploy na hora, rodando em paralelo com restart, stop,
delete ou outro deploy no mesmo app. Agora o push com o app ocupado so guarda o
commit (o ultimo push vence) e o deploy roda quando a operacao atual termina.
"""
from django.core.cache import cache

from applications.models import App, AppStatus
from applications.ownership import dispatch_app_task
from observability.models import AppLogManager, LogCategory

PENDING_REDEPLOY_TTL_SECONDS = 24 * 60 * 60


def _key(app_id: int) -> str:
    return f'app-pending-redeploy:{app_id}'


def queue_pending_redeploy(app_id: int, commit: str | None) -> None:
    cache.set(_key(app_id), {'commit': commit}, timeout=PENDING_REDEPLOY_TTL_SECONDS)


def clear_pending_redeploy(app_id: int) -> None:
    cache.delete(_key(app_id))


def run_pending_redeploy(app_id: int, finished_task_id: str | None) -> str | None:
    """Dispara o redeploy pendente se `finished_task_id` ainda for o dono do app.

    A troca de dono e atomica: se outra operacao ja assumiu, o pendente fica para
    quando ela terminar. Devolve o task_id do deploy disparado, ou None.
    """
    pending = cache.get(_key(app_id))
    if pending is None:
        return None

    app = App.objects.filter(id=app_id, deleted_at__isnull=True).first()
    if app is None or app.status == AppStatus.DELETING:
        clear_pending_redeploy(app_id)
        return None

    # Import local: tasks importa este modulo.
    from applications.tasks import deploy_app_task  # noqa: PLC0415

    task_id = dispatch_app_task(
        app,
        AppStatus.DEPLOYING,
        deploy_app_task,
        expected_task_id=finished_task_id,
        app_id=app.id,
        commit=pending['commit'],
    )
    if task_id:
        clear_pending_redeploy(app_id)
        AppLogManager(app, task_id).info(
            'Iniciando redeploy de um push recebido enquanto outra operação rodava.',
            category=LogCategory.DEPLOY,
            progress=1,
        )
    return task_id
