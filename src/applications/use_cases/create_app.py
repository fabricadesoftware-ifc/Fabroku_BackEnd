"""CreateAppUseCase: business logic for creating and provisioning a new application.

Ports this session close the parity gap flagged after the first pass: this now
faithfully mirrors `core/apps/mixins/apps/create_app.py` (`CreateAppMixin.create_app`)
step for step — dokku name resolution, webhook setup, private-repo token handling,
commit status, git sync, process-scale reapplication, Let's Encrypt/domain, and the
same error-state bookkeeping on `App` — while staying free of Celery/HTTP concerns.

Two deliberate deviations from the legacy task, both noted in REFACTOR-PLAN.md:
1. `task.update_state(...)` calls are dropped — that's Celery-specific progress
   reporting the use case has no business knowing about. `AppLogManager` (DB-backed,
   already Celery-agnostic) remains the single source of progress/log records.
2. On failure, `app.status` is set to `AppStatus.ERROR` instead of the legacy
   literal `'FAILED'`, which is not a valid `AppStatus` choice — a real, if minor,
   defect this refactor is a natural place to fix.
"""
import re
from dataclasses import dataclass
from typing import Callable

from applications.domain.validators import validate_env_vars
from applications.github_integration import reconcile_github_webhook
from applications.models import App, AppStatus
from applications.ports.i_dokku import IDokkuPort
from applications.ports.i_github import IGitHubPort
from applications.process_scale import reapply_saved_process_scales
from core.apps.utils import slugify_dokku
from identity.models import User
from infrastructure.adapters.git_utils import build_github_auth_url, mask_git_credentials, parse_github_repo_name
from observability.models import AppLogManager, LogCategory


@dataclass(frozen=True)
class CreateAppCommand:
    """Input for CreateAppUseCase.execute — mirrors the real create_app task's arguments."""

    app_id: int
    user_id: int
    env_vars: dict[str, str] | None = None
    task_id: str | None = None


@dataclass(frozen=True)
class AppCreated:
    """Result of a successful (or idempotent) app creation."""

    app_id: int
    status: str
    dokku_app_name: str


class CreateAppUseCase:
    """
    Provision an already-registered `App` row in Dokku.

    Does not create the `App` row itself or check name/limit conflicts — those are
    presentation-layer concerns (today: `AppCreateSerializer.create()`), enforced
    before this use case's command is ever dispatched. Given an app_id, this owns
    everything that happens to make the app actually run: Dokku container, env vars,
    GitHub webhook, git sync, Let's Encrypt, and error bookkeeping on failure.
    """

    def __init__(
        self,
        dokku_port: IDokkuPort,
        github_port: IGitHubPort,
        log_manager: AppLogManager,
        *,
        reconcile_webhook: Callable = reconcile_github_webhook,
    ):
        self.dokku_port = dokku_port
        self.github_port = github_port
        self.log_manager = log_manager
        self._reconcile_webhook = reconcile_webhook

    def execute(self, cmd: CreateAppCommand) -> AppCreated:
        app = App.objects.get(id=cmd.app_id, deleted_at__isnull=True)
        user = User.objects.get(id=cmd.user_id)

        if cmd.env_vars:
            validate_env_vars(cmd.env_vars)

        app.task_id = cmd.task_id
        app.save(update_fields=['task_id'])

        self.log_manager.info('Iniciando criação da aplicação...', category=LogCategory.CREATE, progress=2)

        dokku_app_name = self._resolve_dokku_name(app, user)
        app.name_dokku = dokku_app_name
        app.save(update_fields=['name_dokku'])

        head_sha: str | None = None

        try:
            if self._ensure_dokku_app(dokku_app_name):
                self._setup_webhook(user, app, progress=99)
                self.log_manager.warning(
                    f'Aplicação {dokku_app_name} já existe no Dokku', category=LogCategory.CREATE, progress=100
                )
                return AppCreated(app_id=app.id, status='already_exists', dokku_app_name=dokku_app_name)

            self._apply_env_vars(dokku_app_name, cmd.env_vars)

            # Webhook doesn't depend on the build; setting it up early lets a push
            # self-heal a first deploy that later fails.
            self._setup_webhook(user, app, progress=26)

            git_url = self._handle_deploy_keys(user, app.git)

            head_sha = self._get_head_sha(user, app)
            if head_sha:
                self.github_port.set_deploy_pending(user.git_token, app.git, head_sha, app.name)

            self._configure_git(dokku_app_name, git_url, app.branch)

            try:
                reapply_saved_process_scales(app, self.dokku_port, self.log_manager, progress=86)
            except Exception as exc:
                self.log_manager.warning(
                    f'Não foi possível sincronizar escala de processos: {exc}',
                    category=LogCategory.DEPLOY,
                    progress=86,
                )

            self._set_letsencrypt(dokku_app_name)

            domain = self._get_domain(dokku_app_name)
            if domain:
                app.domain = domain
                app.save(update_fields=['domain'])

            app.status = AppStatus.RUNNING
            app.save()

            if head_sha:
                self.github_port.set_deploy_success(user.git_token, app.git, head_sha, app.name)

            self.log_manager.success(
                f'Aplicação {app.name} criada com sucesso!', category=LogCategory.CREATE, progress=100
            )

            return AppCreated(app_id=app.id, status='created', dokku_app_name=dokku_app_name)

        except Exception as e:
            error_type = getattr(e, 'error_type', type(e).__name__)
            error_details = str(e)
            help_url = None
            if 'deploy keys' in error_details and 'desabilitadas' in error_details:
                error_type = 'DeployKeysDisabled'
                match = re.search(r'(https?://[\w./\-]+)', error_details)
                if match:
                    help_url = match.group(1)

            self.log_manager.error(
                f'Erro ao criar aplicação: {error_details}',
                category=LogCategory.CREATE,
                metadata={'error_type': error_type, 'error_details': error_details, 'help_url': help_url},
            )

            app.status = AppStatus.ERROR
            app.error_type = error_type
            app.error_details = error_details
            app.help_url = help_url
            app.save(update_fields=['status', 'error_type', 'error_details', 'help_url'])

            if head_sha:
                self.github_port.set_deploy_failure(user.git_token, app.git, head_sha, app.name, error_details[:100])

            raise

    def _resolve_dokku_name(self, app: App, user: User) -> str:
        """Privileged users may bring a custom name_dokku; everyone else gets the app's own name."""
        can_customize = getattr(user, 'is_fabric', False) or user.is_superuser
        if can_customize and app.name_dokku:
            return slugify_dokku(app.name_dokku)
        return slugify_dokku(app.name)

    def _ensure_dokku_app(self, dokku_app_name: str) -> bool:
        """Create the container if it doesn't exist. Returns True if it already existed."""
        self.log_manager.info(
            'Verificando se a aplicação já existe no Dokku...', category=LogCategory.CREATE, progress=5
        )

        if self.dokku_port.exists_app(dokku_app_name):
            return True

        self.log_manager.info(f'Criando container {dokku_app_name}...', category=LogCategory.CREATE, progress=10)
        output = self.dokku_port.create_app(dokku_app_name)
        self.log_manager.dokku(
            output, command=f'dokku apps:create {dokku_app_name}', category=LogCategory.CREATE, progress=15
        )
        return False

    def _apply_env_vars(self, dokku_app_name: str, env_vars: dict[str, str] | None) -> None:
        if not env_vars:
            self.log_manager.info(
                'Nenhuma variável de ambiente para configurar', category=LogCategory.CONFIG, progress=25
            )
            return

        self.log_manager.info(
            f'Aplicando {len(env_vars)} variáveis de ambiente...', category=LogCategory.CONFIG, progress=18
        )
        output = self.dokku_port.set_config(dokku_app_name, env_vars, no_restart=True)
        var_names = ', '.join(env_vars.keys())
        self.log_manager.dokku(
            output,
            command=f'dokku config:set --no-restart {dokku_app_name} [vars: {var_names}]',
            category=LogCategory.CONFIG,
            progress=22,
        )
        self.log_manager.success(
            'Variáveis de ambiente aplicadas com sucesso', category=LogCategory.CONFIG, progress=25
        )

    def _setup_webhook(self, user: User, app: App, *, progress: int) -> dict:
        return self._reconcile_webhook(
            app,
            preferred_user=user,
            github_adapter=self.github_port,
            app_logger=self.log_manager,
            progress=progress,
        )

    def _handle_deploy_keys(self, user: User, git_url: str) -> str:
        """Resolve the URL to sync: auth-embedded HTTPS for private repos, raw URL otherwise."""
        self.log_manager.info('Verificando permissões do repositório GitHub...', category=LogCategory.GIT, progress=28)

        repo_name = parse_github_repo_name(git_url)
        if not repo_name:
            raise Exception(f'Não foi possível extrair owner/repo de: {git_url}')

        user_git_repos_list = self.github_port.list_user_repos(user_id=user.id)
        if isinstance(user_git_repos_list, dict) and user_git_repos_list.get('error_type') == 'OrgPermissionDenied':
            self.log_manager.error(
                user_git_repos_list.get('error'),
                category=LogCategory.GIT,
                metadata={
                    'error_type': 'OrgPermissionDenied',
                    'error_details': user_git_repos_list.get('error'),
                    'help_url': user_git_repos_list.get('help_url'),
                },
                progress=28,
            )
            raise Exception(
                'Permissão insuficiente para acessar organização. Reautorize seu token no GitHub. '
                f'Mais informações: {user_git_repos_list.get("help_url")}'
            )

        user_git_repos = {repo.full_name: {'private': repo.private} for repo in user_git_repos_list}
        is_private = repo_name in user_git_repos and user_git_repos[repo_name].get('private', False)

        if is_private:
            self.log_manager.info(
                f'Repositório {repo_name} é privado. Usando autenticação HTTPS com token...',
                category=LogCategory.GIT,
                progress=32,
            )
            auth_url = build_github_auth_url(git_url, user.git_token)
            self.log_manager.success(
                f'Autenticação configurada para repositório privado {repo_name}',
                category=LogCategory.GIT,
                progress=40,
            )
            return auth_url

        self.log_manager.info(
            f'Repositório {repo_name} é público. Autenticação não necessária.',
            category=LogCategory.GIT,
            progress=40,
        )
        return git_url

    def _get_head_sha(self, user: User, app: App) -> str | None:
        repo_name = parse_github_repo_name(app.git)
        if not repo_name:
            return None
        return self.github_port.get_branch_head_sha(repo_name, app.branch, user_id=user.id)

    def _configure_git(self, dokku_app_name: str, git_url: str, branch: str) -> None:
        self.log_manager.info('Iniciando sincronização do repositório Git...', category=LogCategory.GIT, progress=45)
        self.log_manager.info(
            f'Clonando branch "{branch}"... Esta etapa pode demorar alguns minutos.',
            category=LogCategory.GIT,
            progress=50,
        )

        line_count = [0]
        base_progress, max_progress = 50, 85

        def on_log_line(line: str) -> None:
            if not line.strip():
                return
            safe_line = mask_git_credentials(line)
            line_count[0] += 1
            progress = min(base_progress + (line_count[0] * 0.5), max_progress - 1)
            self.log_manager.dokku(safe_line, category=LogCategory.GIT, progress=int(progress))

        output = self.dokku_port.sync_git_streaming(
            dokku_app_name, git_url, branch, on_line=on_log_line
        )
        safe_output = mask_git_credentials(output)

        if 'Failed' in output or 'failed' in output.lower():
            self.log_manager.error(f'Erro no git:sync: {safe_output}', category=LogCategory.GIT, progress=85)
            raise RuntimeError(f'Falha ao sincronizar repositorio: {safe_output}')

        self.log_manager.dokku(
            f'Sync concluído ({line_count[0]} linhas processadas)',
            command=f'dokku git:sync {dokku_app_name} {mask_git_credentials(git_url)} {branch}',
            category=LogCategory.GIT,
            progress=85,
        )

    def _set_letsencrypt(self, dokku_app_name: str) -> None:
        self.log_manager.info("Configurando certificado SSL (Let's Encrypt)...", category=LogCategory.SSL, progress=88)
        output = self.dokku_port.enable_letsencrypt(dokku_app_name)
        self.log_manager.dokku(
            output, command=f'dokku letsencrypt:enable {dokku_app_name}', category=LogCategory.SSL, progress=95
        )

    def _get_domain(self, dokku_app_name: str) -> str | None:
        self.log_manager.info('Obtendo domínio principal da aplicação...', category=LogCategory.SSL, progress=97)
        domain = self.dokku_port.get_app_domain(dokku_app_name)
        self.log_manager.dokku(
            domain, command=f'dokku domains:report {dokku_app_name}', category=LogCategory.SSL, progress=99
        )
        return domain or None
