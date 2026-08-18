"""DeployAppUseCase: business logic for redeploying an existing application.

Ports `core/apps/mixins/apps/redeploy_app.py` (`RedeployAppMixin.redeploy_app`)
faithfully: linked-database warmup, git-token/webhook resolution via
`github_integration.py`, git sync, process-scale reapplication, and Let's
Encrypt/domain touch-up.

Two deliberate deviations from the legacy task, both noted in REFACTOR-PLAN.md:
1. `task.update_state(...)` calls are dropped, same reasoning as `CreateAppUseCase`.
2. Every failure path (app missing, no `name_dokku`, app absent from Dokku, git
   sync plan not `ok`, git sync output containing "failed") now *raises*
   `DeploymentFailed` instead of the legacy pattern of silently `return`-ing an
   `{'status': 'error', ...}` dict. A Celery task that returns normally is
   recorded as SUCCESS regardless of the dict's contents — the legacy code was
   masking real deployment failures from monitoring/retries. All these paths
   still result in the same `App.status = ERROR` + GitHub failure-status
   bookkeeping as before; they just now surface as an actual task failure too.
"""
from dataclasses import dataclass
from typing import Callable

from django.utils import timezone

from applications.domain.exceptions import DeploymentFailed
from applications.github_integration import GitSyncPlan, reconcile_github_webhook, resolve_git_sync_plan
from applications.models import App, AppStatus
from applications.ports.i_dokku import IDokkuPort
from applications.ports.i_github import IGitHubPort
from applications.process_scale import reapply_saved_process_scales
from identity.models import User
from infrastructure.adapters.git_utils import mask_git_credentials
from observability.models import AppLogManager, LogCategory
from service_mgmt.models import Service
from service_mgmt.service_types import is_postgres_service_type


def _dokku_output_failed(output: str) -> bool:
    output_lower = (output or '').lower()
    return any(
        marker in output_lower
        for marker in ('failed', 'failed to execute command', 'ssh command timeout', 'ssh connection error')
    )


@dataclass(frozen=True)
class DeployAppCommand:
    """Input for DeployAppUseCase.execute — mirrors the real redeploy_app task's arguments."""

    app_id: int
    task_id: str | None = None
    commit_sha: str | None = None
    user_id: int | None = None  # who requested a manual redeploy; None for webhook-triggered


@dataclass(frozen=True)
class AppDeployed:
    """Result of a successful redeploy."""

    app_id: int
    dokku_app_name: str
    commit_sha: str | None


class DeployAppUseCase:
    """Redeploy an already-provisioned `App`: sync git, reapply config, verify it's up."""

    def __init__(
        self,
        dokku_port: IDokkuPort,
        github_port: IGitHubPort,
        log_manager: AppLogManager,
        *,
        reconcile_webhook: Callable = reconcile_github_webhook,
        resolve_sync_plan: Callable[..., GitSyncPlan] = resolve_git_sync_plan,
    ):
        self.dokku_port = dokku_port
        self.github_port = github_port
        self.log_manager = log_manager
        self._reconcile_webhook = reconcile_webhook
        self._resolve_sync_plan = resolve_sync_plan

    def execute(self, cmd: DeployAppCommand) -> AppDeployed:
        app = App.objects.get(id=cmd.app_id, deleted_at__isnull=True)

        app.task_id = cmd.task_id
        app.status = AppStatus.DEPLOYING
        update_fields = ['task_id', 'status']
        if cmd.commit_sha:
            app.last_commit_sha = cmd.commit_sha
            update_fields.append('last_commit_sha')
        app.save(update_fields=update_fields)

        commit_display = cmd.commit_sha[:7] if cmd.commit_sha else 'latest'
        self.log_manager.info(
            f'Iniciando redeploy da aplicação (commit: {commit_display})...', category=LogCategory.DEPLOY, progress=5
        )

        requested_by = User.objects.filter(id=cmd.user_id).first() if cmd.user_id else None
        self._reconcile_webhook_if_manual(app, requested_by)

        git_sync_plan = self._resolve_sync_plan(app, preferred_user=requested_by)
        git_token = git_sync_plan.token

        if not git_token:
            self.log_manager.warning(
                'Commit status indisponível: nenhum usuário do projeto tem token GitHub', category=LogCategory.DEPLOY
            )
            self.log_manager.warning(
                'Repositórios privados precisam de um token GitHub válido. Reautorize o GitHub '
                'ou garanta que um membro do projeto tenha acesso ao repo.',
                category=LogCategory.GIT,
                progress=9,
            )
        if cmd.commit_sha and git_token:
            self.github_port.set_deploy_pending(git_token, app.git, cmd.commit_sha, app.name)

        dokku_app_name = app.name_dokku

        try:
            if not dokku_app_name:
                raise DeploymentFailed(reason='App não tem name_dokku configurado', step='validate')

            self._start_linked_databases(app)

            app_exists = self.dokku_port.exists_app(dokku_app_name)
            self.log_manager.dokku(
                'App encontrado no Dokku.' if app_exists else 'App nao encontrado no Dokku.',
                command='dokku apps:list',
                category=LogCategory.DEPLOY,
                progress=4,
            )
            if not app_exists:
                raise DeploymentFailed(reason=f'App {dokku_app_name} não existe no Dokku', step='verify_exists')

            if app.variables:
                self._apply_env_vars(dokku_app_name, app.variables)

            if not git_sync_plan.ok:
                self.log_manager.error(git_sync_plan.message, category=LogCategory.GIT, progress=10)
                raise DeploymentFailed(reason=git_sync_plan.message, step='resolve_git_sync_plan')

            git_url = git_sync_plan.git_url or app.git
            self.log_manager.info(git_sync_plan.message, category=LogCategory.GIT, progress=10)

            output = self._sync_git(dokku_app_name, git_url, app.branch)
            if 'Failed' in output or 'failed' in output.lower():
                safe_output = mask_git_credentials(output)
                self.log_manager.error(f'Erro no redeploy: {safe_output}', category=LogCategory.DEPLOY, progress=90)
                raise DeploymentFailed(reason=safe_output, step='git_sync')

            app.status = AppStatus.RUNNING
            app.save(update_fields=['status'])

            try:
                applied = reapply_saved_process_scales(app, self.dokku_port, self.log_manager, progress=90)
                if applied:
                    self.log_manager.success(
                        'Escala de processos reaplicada apos o redeploy.', category=LogCategory.DEPLOY, progress=90
                    )
            except Exception as exc:
                self.log_manager.warning(
                    f'Redeploy concluido, mas nao foi possivel reaplicar escala de processos: {exc}',
                    category=LogCategory.DEPLOY,
                    progress=90,
                )

            self._ensure_letsencrypt(app, dokku_app_name)

            if cmd.commit_sha and git_token:
                self.github_port.set_deploy_success(git_token, app.git, cmd.commit_sha, app.name)

            app.updated_at = timezone.now()
            app.save(update_fields=['updated_at'])

            self.log_manager.success('Redeploy concluído com sucesso!', category=LogCategory.DEPLOY, progress=100)

            return AppDeployed(app_id=app.id, dokku_app_name=dokku_app_name, commit_sha=cmd.commit_sha)

        except Exception as e:
            self.log_manager.error(f'Erro no redeploy: {e}', category=LogCategory.DEPLOY)
            app.status = AppStatus.ERROR
            app.save(update_fields=['status'])
            if cmd.commit_sha and git_token:
                self.github_port.set_deploy_failure(git_token, app.git, cmd.commit_sha, app.name, str(e)[:100])
            raise

    def _reconcile_webhook_if_manual(self, app: App, requested_by: User | None) -> None:
        """Reconcile the GitHub webhook only for a manual redeploy.

        A redeploy triggered by the webhook itself (`requested_by is None`) is already
        proof the webhook is configured and firing — reconciling again here would just
        repeat the same GitHub API calls (`get_repo` + list hooks) that the incoming push
        just validated, on every single automatic deploy. Manual redeploys still reconcile
        so a user clicking "Redeploy" can self-heal a broken webhook right away.
        """
        if requested_by is None:
            return

        self._reconcile_webhook(
            app,
            preferred_user=requested_by,
            github_adapter=self.github_port,
            app_logger=self.log_manager,
            progress=6,
        )

    def _start_linked_databases(self, app: App) -> None:
        """Best-effort warm-up of linked Postgres services before redeploying against them."""
        for svc in Service.objects.filter(app=app, deleted_at__isnull=True):
            if svc.container_name and is_postgres_service_type(svc.service_type):
                try:
                    output = self.dokku_port.start_database(svc.container_name)
                    self.log_manager.dokku(
                        output,
                        command=f'dokku postgres:start {svc.container_name}',
                        category=LogCategory.DATABASE,
                        progress=3,
                    )
                except Exception:
                    pass

    def _apply_env_vars(self, dokku_app_name: str, env_vars: dict[str, str]) -> None:
        self.log_manager.info('Aplicando variáveis de ambiente atualizadas...', category=LogCategory.CONFIG, progress=5)
        output = self.dokku_port.set_config(dokku_app_name, env_vars, no_restart=True)
        self.log_manager.dokku(
            output,
            command=f'dokku config:set --no-restart {dokku_app_name} [vars: {", ".join(env_vars.keys())}]',
            category=LogCategory.CONFIG,
            progress=5,
        )
        if _dokku_output_failed(output):
            raise DeploymentFailed(reason=output, step='apply_env_vars')

    def _sync_git(self, dokku_app_name: str, git_url: str, branch: str) -> str:
        line_count = [0]
        base_progress, max_progress = 10, 90

        def on_log_line(line: str) -> None:
            if not line.strip():
                return
            safe_line = mask_git_credentials(line)
            line_count[0] += 1
            progress = min(base_progress + (line_count[0] * 0.5), max_progress - 1)
            self.log_manager.dokku(safe_line, category=LogCategory.GIT, progress=int(progress))

        return self.dokku_port.sync_git_streaming(dokku_app_name, git_url, branch, on_line=on_log_line)

    def _ensure_letsencrypt(self, app: App, dokku_app_name: str) -> None:
        """Re-check Let's Encrypt/domain only if they weren't already configured (e.g. first deploy failed)."""
        if app.domain and self.dokku_port.get_app_domain(dokku_app_name):
            return

        self.log_manager.info("Verificando/reativando Let's Encrypt...", category=LogCategory.SSL, progress=90)
        try:
            self.dokku_port.enable_letsencrypt(dokku_app_name)
        except Exception:
            self.log_manager.warning(
                "Let's Encrypt falhou, tentando obter domínio mesmo assim", category=LogCategory.SSL
            )

        domain = self.dokku_port.get_app_domain(dokku_app_name)
        if domain:
            app.domain = domain
            app.save(update_fields=['domain'])
            self.log_manager.success(f'Domínio configurado: {domain}', category=LogCategory.SSL, progress=95)
