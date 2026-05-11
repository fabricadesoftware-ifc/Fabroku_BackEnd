import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from core.adapters import GitHubAdapter
from core.apps.mixins import AppMixin
from core.apps.models import App

logger = logging.getLogger(__name__)


def _get_git_token_for_app(app: App) -> str | None:
    """Obtém o git_token de um usuário do projeto que tenha acesso ao repo."""
    from github import Github, GithubException  # noqa: PLC0415

    users_with_token = app.project.users.exclude(git_token__isnull=True).exclude(git_token='')
    repo_name = app.git.rsplit('.com/', maxsplit=1)[-1].replace('.git', '') if app.git and '.com/' in app.git else None

    for user in users_with_token:
        if not repo_name:
            return user.git_token
        try:
            gh = Github(user.git_token)
            gh.get_repo(repo_name)
            logger.info('Token válido para repo %s via usuário %s', repo_name, user.username or user.id)
            return user.git_token
        except GithubException:
            logger.warning('Token do usuário %s não tem acesso ao repo %s', user.username or user.id, repo_name)
            continue
        except Exception:
            continue

    logger.warning('Nenhum token com acesso ao repo %s', repo_name)
    return None


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
    branch = ref.split('/')[-1] if ref else None

    if branch != app.branch:
        return JsonResponse({
            'status': 'ignored',
            'message': f'Push na branch {branch}, app configurado para {app.branch}',
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

    # --- Setar commit status PENDING imediatamente (síncrono, sem depender do Celery) ---
    if commit:
        git_token = _get_git_token_for_app(app)
        if git_token:
            try:
                github_adapter = GitHubAdapter()
                ok = github_adapter.set_deploy_pending(git_token, app.git, commit, app.name)
                logger.info('Commit status pending setado no webhook: ok=%s commit=%s', ok, commit[:7])
            except Exception as e:
                logger.warning('Falha ao setar commit status pending no webhook: %s', e)
        else:
            logger.warning('Nenhum git_token disponível para setar commit status no webhook (app=%s)', app.name)

    # Dispara a task de redeploy
    task_result = AppMixin.redeploy_app.delay(app_id=app.id, commit=commit)  # type: ignore

    logger.info('Task de redeploy disparada: task_id=%s app=%s', task_result.id, app.name)

    return JsonResponse({
        'status': 'deploy_started',
        'message': f'Redeploy iniciado para {app.name}',
        'task_id': task_result.id,
        'branch': branch,
        'commit': commit[:7] if commit else None,
        'pusher': pusher,
    })
