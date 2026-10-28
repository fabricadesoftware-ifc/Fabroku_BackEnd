import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from applications.models import App, AppStatus
from applications.ownership import dispatch_app_task, is_app_busy
from applications.pending_redeploy import queue_pending_redeploy, run_pending_redeploy
from applications.tasks import deploy_app_task
from infrastructure.adapters.git_utils import parse_github_branch_from_ref

logger = logging.getLogger(__name__)
WEBHOOK_DELIVERY_CACHE_TTL_SECONDS = 24 * 60 * 60


def verify_github_signature(payload_body: bytes, signature: str | None, secret: str) -> bool:
    """Verifica a assinatura HMAC do webhook do GitHub."""
    if not signature:
        return False

    # GitHub envia no formato 'sha256=xxxxx'
    if signature.startswith('sha256='):
        signature = signature[7:]
    elif signature.startswith('sha1='):
        signature = signature[5:]
        # Para sha1 (formato antigo)
        expected = hmac.new(secret.encode(), payload_body, hashlib.sha1).hexdigest()
        return hmac.compare_digest(expected, signature)

    expected = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _queue_redeploy_while_busy(app: App, commit: str | None, branch: str | None) -> JsonResponse:
    """App ocupado: guarda o push para rodar quando a operacao atual terminar."""
    queue_pending_redeploy(app.id, commit)
    # A operacao pode ter terminado entre a checagem e o queue: nesse caso ninguem
    # mais consumiria o pendente, entao tentamos disparar agora.
    app.refresh_from_db(fields=['status', 'task_id'])
    task_id = None if is_app_busy(app) else run_pending_redeploy(app.id, app.task_id)
    if task_id:
        logger.info('Redeploy pendente disparado na hora: task_id=%s app=%s', task_id, app.name)
        return JsonResponse({
            'status': 'deploy_started',
            'message': f'Redeploy iniciado para {app.name}',
            'task_id': task_id,
            'branch': branch,
            'commit': commit[:7] if commit else None,
        })
    logger.info('Push guardado: app %s ocupado (%s)', app.name, app.status)
    return JsonResponse({
        'status': 'queued',
        'message': f'{app.name} está em {app.status}; o redeploy roda quando a operação atual terminar.',
        'branch': branch,
        'commit': commit[:7] if commit else None,
    }, status=202)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def github_webhook(request, app_id: int):
    """
    Endpoint para receber webhooks do GitHub.
    Dispara redeploy quando há push na branch configurada.
    """
    # Verifica assinatura (se configurada)
    webhook_secret = getattr(settings, 'GITHUB_WEBHOOK_SECRET', None)
    if webhook_secret:
        signature = request.headers.get('X-Hub-Signature-256') or request.headers.get('X-Hub-Signature')
        if not verify_github_signature(request.body, signature, webhook_secret):
            return JsonResponse({'status': 'error', 'message': 'Invalid signature'}, status=403)

    # Verifica tipo de evento
    event_type = request.headers.get('X-GitHub-Event', 'push')
    if event_type == 'ping':
        return JsonResponse({'status': 'ok', 'message': 'Webhook configurado com sucesso!'})

    if event_type != 'push':
        return JsonResponse({'status': 'ignored', 'message': f'Evento {event_type} ignorado'})

    # Parse do payload
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    # Busca o app
    try:
        app = App.objects.get(id=app_id, deleted_at__isnull=True)
    except App.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': f'App {app_id} not found'}, status=404)

    # Verifica se é a branch correta
    ref = payload.get('ref', '')
    branch = parse_github_branch_from_ref(ref)

    if branch != app.branch:
        return JsonResponse({
            'status': 'ignored',
            'message': f'Push na branch {branch}, app configurado para {app.branch}',
        })

    delivery_id = request.headers.get('X-GitHub-Delivery')
    delivery_key = None
    if delivery_id:
        delivery_key = f'github-webhook-delivery:{app.id}:{delivery_id}'
        try:
            is_new_delivery = cache.add(
                delivery_key,
                app.id,
                timeout=WEBHOOK_DELIVERY_CACHE_TTL_SECONDS,
            )
        except Exception:
            logger.exception('Falha ao verificar deduplicacao da entrega GitHub %s', delivery_id)
        else:
            if not is_new_delivery:
                logger.info('Entrega GitHub duplicada ignorada: delivery=%s app=%s', delivery_id, app.name)
                return JsonResponse({
                    'status': 'duplicate',
                    'message': 'Entrega do GitHub ja processada.',
                    'delivery_id': delivery_id,
                })

    # Extrai informações do commit
    commit = payload.get('after', payload.get('head_commit', {}).get('id'))
    pusher = payload.get('pusher', {}).get('name', 'unknown')

    logger.info(
        'Webhook recebido: app=%s branch=%s commit=%s pusher=%s',
        app.name,
        branch,
        commit[:7] if commit else 'N/A',
        pusher,
    )

    if app.status == AppStatus.DELETING:
        return JsonResponse({'status': 'ignored', 'message': f'App {app.name} está sendo removido.'})

    # O status do commit e atualizado pela task. O endpoint precisa responder
    # rapidamente ao GitHub e nao deve depender de uma segunda chamada externa.
    try:
        task_id = None
        if not is_app_busy(app):
            # Troca atomica: dois pushes simultaneos nao disparam dois deploys.
            task_id = dispatch_app_task(
                app, AppStatus.DEPLOYING, deploy_app_task,
                expected_task_id=app.task_id, app_id=app.id, commit=commit,
            )
        if task_id is None:
            return _queue_redeploy_while_busy(app, commit, branch)
    except Exception:
        # O GitHub pode reenviar a entrega. Se nem sequer conseguimos colocar
        # a task na fila, ela ainda nao foi processada e deve poder ser tentada novamente.
        if delivery_key:
            try:
                cache.delete(delivery_key)
            except Exception:
                logger.exception('Falha ao liberar entrega GitHub apos erro de enfileiramento: %s', delivery_id)
        raise

    logger.info('Task de redeploy disparada: task_id=%s app=%s', task_id, app.name)

    return JsonResponse({
        'status': 'deploy_started',
        'message': f'Redeploy iniciado para {app.name}',
        'task_id': task_id,
        'branch': branch,
        'commit': commit[:7] if commit else None,
        'pusher': pusher,
    })
