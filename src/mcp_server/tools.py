from typing import Any

from asgiref.sync import sync_to_async
from celery.result import AsyncResult
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from applications.models import App, AppProcessScale
from identity.models import User
from infrastructure.adapters import DokkuAdapter
from observability.ssh_audit import ssh_audit_context

MAX_RUNTIME_LOG_LINES = 500

mcp = MCPServer(
    name='Fabroku',
    instructions=(
        'Consulta somente-leitura dos apps do Fabroku do usuário autenticado: '
        'lista de apps, status, escala de processos e logs de runtime. '
        'Nenhuma tool aqui inicia, para, reinicia, faz redeploy ou apaga um app.'
    ),
)


def _current_user(ctx: Context) -> User:
    request = ctx.request_context.request
    user = getattr(request.state, 'fabroku_user', None) if request is not None else None
    if user is None:
        raise ToolError('Token CLI ausente ou inválido para esta conexão MCP.')
    return user


def _summarize_app(app: App) -> dict[str, Any]:
    return {
        'id': app.id,
        'name': app.name,
        'status': app.status,
        'domain': app.domain,
        'branch': app.branch,
        'project': app.project.name if app.project_id else None,
    }


def _summarize_scale(scale: AppProcessScale) -> dict[str, Any]:
    return {
        'process_name': scale.process_name,
        'desired_quantity': scale.desired_quantity,
        'current_quantity': scale.current_quantity,
        'last_synced_at': scale.last_synced_at.isoformat() if scale.last_synced_at else None,
    }


@sync_to_async
def _fetch_user_apps(user: User) -> list[App]:
    return list(App.objects.filter(project__users=user, deleted_at__isnull=True).select_related('project'))


@sync_to_async
def _get_owned_app(user: User, app_id: int) -> App | None:
    return App.objects.select_related('project').filter(
        id=app_id, project__users=user, deleted_at__isnull=True,
    ).first()


@sync_to_async
def _fetch_task_status(task_id: str) -> dict[str, Any]:
    result = AsyncResult(task_id)
    info = result.info if isinstance(result.info, dict) else None
    return {'state': result.state, **(info or {})}


@sync_to_async
def _fetch_process_scales(app: App) -> list[AppProcessScale]:
    return list(AppProcessScale.objects.filter(app=app).order_by('process_name'))


@sync_to_async
def _fetch_runtime_logs(app: App, num_lines: int, user: User) -> str:
    with ssh_audit_context(origin='mcp.get_runtime_logs', user_id=user.id, app_id=app.id):
        return DokkuAdapter().logs_app(app.name_dokku, num_lines=num_lines)


async def _require_owned_app(user: User, app_id: int) -> App:
    app = await _get_owned_app(user, app_id)
    if app is None:
        raise ToolError(f'App {app_id} não encontrado ou não pertence ao usuário autenticado.')
    return app


@mcp.tool()
async def list_apps(ctx: Context) -> list[dict[str, Any]]:
    """Lista as aplicações do usuário autenticado no Fabroku, com status, domínio, branch e projeto."""
    user = _current_user(ctx)
    apps = await _fetch_user_apps(user)
    return [_summarize_app(app) for app in apps]


@mcp.tool()
async def get_app_status(ctx: Context, app_id: int) -> dict[str, Any]:
    """Retorna o status atual e o progresso da última operação (criação/deploy) de um app pelo id."""
    user = _current_user(ctx)
    app = await _require_owned_app(user, app_id)
    task = await _fetch_task_status(app.task_id) if app.task_id else None
    return {'app': _summarize_app(app), 'task': task}


@mcp.tool()
async def get_app_processes(ctx: Context, app_id: int) -> list[dict[str, Any]]:
    """Retorna a escala de processos (dynos) atual de um app pelo id — réplicas desejadas x ativas."""
    user = _current_user(ctx)
    app = await _require_owned_app(user, app_id)
    scales = await _fetch_process_scales(app)
    return [_summarize_scale(scale) for scale in scales]


@mcp.tool()
async def get_runtime_logs(ctx: Context, app_id: int, lines: int = 100) -> dict[str, Any]:
    """Retorna as últimas linhas de log de runtime (stdout/stderr do container) de um app pelo id."""
    user = _current_user(ctx)
    app = await _require_owned_app(user, app_id)
    if not app.name_dokku:
        return {'lines': []}
    capped = max(1, min(int(lines), MAX_RUNTIME_LOG_LINES))
    output = await _fetch_runtime_logs(app, capped, user)
    return {'lines': [line.strip() for line in (output or '').split('\n') if line.strip()]}
