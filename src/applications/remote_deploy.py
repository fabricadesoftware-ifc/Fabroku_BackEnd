"""Deploy pelo plugin fabroku (Fabroku_Plugin): o build roda no servidor, fora da sessão SSH.

Se o worker morre no meio (deploy do próprio Fabroku, OOM), a task some mas o build segue
no servidor, e o App ficaria DEPLOYING para sempre. Aqui o Fabroku consulta o plugin e grava
o status real.
"""

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from applications.models import App, AppStatus
from applications.ownership import save_if_owner
from infrastructure.adapters.dokku import DokkuAdapter
from infrastructure.adapters.dokku_mixins.dokku_git import REMOTE_DEPLOY_FINISHED_STATES
from observability.models import AppLogManager, LogCategory

logger = logging.getLogger(__name__)

# get_app_status é consultado a cada poucos segundos; o SSH para o plugin, no máximo a cada 30 s.
RECONCILE_THROTTLE_SECONDS = 30
# Depois do build a task ainda configura SSL e domínio. Passado isso sem gravar o status, morreu.
ORPHAN_AFTER = timedelta(minutes=5)


def cancel_remote_deploy(app: App, task_id: str) -> None:
    """Para o build no servidor; sem o plugin, revogar a task já derruba a sessão SSH."""
    if not settings.DOKKU_REMOTE_DEPLOY_PLUGIN:
        return
    try:
        DokkuAdapter().cancel_remote_deploy(task_id)
    except Exception:
        logger.exception('Falha ao cancelar o deploy %s de %s no plugin fabroku', task_id, app.name_dokku)


def _parse_finished_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def _orphaned_remote_deploy(deploy_id: str) -> dict | None:
    """Estado remoto se o build já terminou há tempo demais para a task ainda estar viva."""
    try:
        remote = DokkuAdapter().get_remote_deploy_status(deploy_id)
    except Exception:
        logger.warning('Falha ao consultar o deploy %s no plugin fabroku', deploy_id, exc_info=True)
        return None
    if not remote or remote.get('state') not in REMOTE_DEPLOY_FINISHED_STATES:
        return None
    if remote['state'] == 'lost':
        return remote
    finished_at = _parse_finished_at(remote.get('finished_at'))
    if finished_at is None or timezone.now() - finished_at < ORPHAN_AFTER:
        return None
    return remote


def reconcile_orphan_remote_deploy(app: App) -> bool:
    """Grava o status real de um deploy cuja task morreu; True se gravou."""
    if not settings.DOKKU_REMOTE_DEPLOY_PLUGIN or app.status != AppStatus.DEPLOYING or not app.task_id:
        return False
    if not cache.add(f'remote-deploy-reconcile:{app.id}', 1, RECONCILE_THROTTLE_SECONDS):
        return False

    remote = _orphaned_remote_deploy(app.task_id)
    if remote is None:
        return False

    if remote['state'] == 'succeeded' and app.domain:
        fields = {'status': AppStatus.RUNNING}
        message = 'O worker parou durante o deploy, mas o build terminou no servidor. App no ar.'
    else:
        detail = (
            'O build terminou no servidor, mas a configuração final não rodou. Faça um redeploy.'
            if remote['state'] == 'succeeded'
            else f'O worker parou durante o deploy e o build terminou como "{remote["state"]}" no servidor.'
        )
        fields = {'status': AppStatus.ERROR, 'error_type': 'RemoteDeployOrphaned', 'error_details': detail}
        message = detail

    if not save_if_owner(app, app.task_id, **fields):
        return False
    AppLogManager(app, app.task_id).warning(message, category=LogCategory.DEPLOY, progress=100)
    return True
