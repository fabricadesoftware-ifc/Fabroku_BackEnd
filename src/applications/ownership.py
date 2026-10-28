"""Posse do App por operacao.

`App.task_id` diz qual operacao (deploy, start/stop/restart, delete) e dona do app
agora. O despacho (`dispatch_app_task`) grava o dono antes de enfileirar; a task so
grava status se ainda for a dona. Sem isso valia "o ultimo a escrever vence": excluir
durante um deploy fazia o deploy gravar RUNNING por cima de DELETING, e dois deploys
paralelos deixavam o status de quem terminasse por ultimo.

Tasks auxiliares (comandos, migrate, escala) nao tomam posse: elas nao mudam status.
"""
import uuid

from celery.result import AsyncResult
from django.db.models import Q

from applications.models import TRANSIENT_APP_STATUSES, App

FINISHED_TASK_STATES = frozenset({'SUCCESS', 'FAILURE', 'REVOKED'})

# Sentinela de dispatch_app_task: "nao conferir o dono anterior".
ANY_OWNER = object()


class OperationSuperseded(Exception):
    """Outra operacao assumiu o app depois que esta task foi despachada."""


def is_app_busy(app: App) -> bool:
    """Ha operacao em andamento no worker.

    Status transitorio cuja task ja terminou (FAILURE/REVOKED) nao conta: senao um app
    que ficou preso nunca mais aceitaria start/restart.
    """
    if app.status not in TRANSIENT_APP_STATUSES:
        return False
    return not (app.task_id and AsyncResult(app.task_id).state in FINISHED_TASK_STATES)


def dispatch_app_task(app: App, new_status: str, task, *, expected_task_id=ANY_OWNER, **task_kwargs) -> str | None:
    """Grava status + task_id ANTES de enfileirar e devolve o task_id.

    Com `expected_task_id`, so despacha se o dono atual ainda for esse (troca atomica);
    devolve None se outro despacho chegou antes. Evita despachar duas vezes o mesmo
    redeploy pendente.
    """
    task_id = str(uuid.uuid4())
    previous_status, previous_task_id = app.status, app.task_id
    queryset = App.objects.filter(id=app.id)
    if expected_task_id is not ANY_OWNER:
        queryset = queryset.filter(task_id=expected_task_id)
    if not queryset.update(status=new_status, task_id=task_id):
        return None
    app.status = new_status
    app.task_id = task_id
    try:
        task.apply_async(kwargs=task_kwargs, task_id=task_id)
    except Exception:
        # Broker fora: a task nunca vai rodar. Sem desfazer, o app ficaria preso
        # num status transitorio de uma task PENDING para sempre.
        App.objects.filter(id=app.id, task_id=task_id).update(status=previous_status, task_id=previous_task_id)
        app.status, app.task_id = previous_status, previous_task_id
        raise
    return task_id


def claim_app(app: App, task_id: str | None) -> None:
    """Inicio da task: confirma a posse. Levanta OperationSuperseded se outra assumiu.

    App sem dono (task_id vazio) e assumido: caminho de quem chama o use case direto.
    """
    if task_id is None:
        return
    owned = (
        App.objects.filter(id=app.id)
        .filter(Q(task_id=task_id) | Q(task_id__isnull=True) | Q(task_id=''))
        .update(task_id=task_id)
    )
    if not owned:
        raise OperationSuperseded(f'App {app.id} foi assumido por outra operação.')
    app.task_id = task_id


def save_if_owner(app: App, task_id: str | None, **fields) -> bool:
    """Grava `fields` so se `task_id` ainda for o dono. Devolve se gravou.

    Sem task_id (use case chamado direto) grava sempre, como antes.
    """
    if task_id is None:
        for name, value in fields.items():
            setattr(app, name, value)
        app.save(update_fields=list(fields))
        return True
    if not App.objects.filter(id=app.id, task_id=task_id).update(**fields):
        return False
    for name, value in fields.items():
        setattr(app, name, value)
    return True
