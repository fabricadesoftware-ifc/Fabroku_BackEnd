import re
from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter, GitHubAdapter
from core.apps.models import App
from core.apps.utils import slugify_dokku
from core.auth_user.models import User
from core.logs.models import AppLogManager, LogCategory


def https_to_ssh_url(url: str) -> str:
    """
    Converte URL HTTPS do GitHub para SSH.
    https://github.com/user/repo.git -> git@github.com:user/repo.git
    """
    match = re.match(r'https://github\.com/([^/]+)/([^/]+?)(\.git)?$', url)
    if match:
        owner, repo = match.group(1), match.group(2)
        return f'git@github.com:{owner}/{repo}.git'
    return url


class CreateAppMixin:
    """
    Mixin para criação de aplicações.
    Contém a task principal e métodos auxiliares estáticos para organização.

    Distribuição de progresso (baseado no tempo real de cada etapa):
    - 0-5%:   Inicialização
    - 5-10%:  Verificar existência do app
    - 10-15%: Criar container Dokku
    - 15-25%: Variáveis de ambiente
    - 25-40%: Verificar GitHub + deploy keys
    - 40-85%: Git sync (etapa mais demorada)
    - 85-95%: Let's Encrypt
    - 95-100%: Finalização
    """

    @shared_task(bind=True)
    def websocket_deploy_update(self, app_id: int, message: str) -> None:
        """Task auxiliar para enviar atualizações via WebSocket durante o deploy."""

    @shared_task(bind=True)
    def create_app(self, app_id: int, user_id: int, env_vars: dict | None = None) -> dict:
        """
        Orquestrador principal: Cria uma nova aplicação e a provisiona no servidor Dokku.
        """
        task = cast(Task, self)
        task_id = task.request.id

        app, user = CreateAppMixin._get_instances(app_id, user_id)

        # Salva o task_id na app para referência
        app.task_id = task_id
        app.save(update_fields=['task_id'])

        # Inicializa o logger
        logger = AppLogManager(app, task_id)
        logger.info('Iniciando criação da aplicação...', category=LogCategory.CREATE, progress=2)

        dokku_app_name = CreateAppMixin._resolve_dokku_name(app, user)
        dokku_adapter = DokkuAdapter()
        github_adapter = GitHubAdapter()
        app.name_dokku = dokku_app_name
        app.save(update_fields=['name_dokku'])

        head_sha = None  # Declarado fora do try para uso no except

        try:
            if CreateAppMixin._ensure_dokku_app(task, dokku_adapter, app, dokku_app_name, logger):
                logger.warning(
                    f'Aplicação {dokku_app_name} já existe no Dokku', category=LogCategory.CREATE, progress=100
                )
                return {'status': 'already_exists', 'app_id': app.id}  # type: ignore

            CreateAppMixin._apply_env_vars(task, dokku_adapter, dokku_app_name, env_vars, logger)

            git_url = CreateAppMixin._handle_deploy_keys(task, dokku_adapter, github_adapter, user, app.git, logger)

            # --- GitHub Commit Status: marca pending antes do git:sync ---
            head_sha = CreateAppMixin._get_head_sha(github_adapter, user, app)
            if head_sha:
                github_adapter.set_deploy_pending(user.git_token, app.git, head_sha, app.name)

            CreateAppMixin._configure_git(task, dokku_adapter, dokku_app_name, git_url, app.branch, logger)

            # Configura webhook para deploy automático
            CreateAppMixin._setup_webhook(github_adapter, user, app, logger)

            CreateAppMixin._set_letsencrypt(self, dokku_app_name, logger)

            domain = CreateAppMixin._get_domain(self, dokku_app_name, logger)
            if domain:
                app.domain = domain
                app.save(update_fields=['domain'])

            app.status = 'RUNNING'
            app.save()

            # --- GitHub Commit Status: marca success ---
            if head_sha:
                github_adapter.set_deploy_success(user.git_token, app.git, head_sha, app.name)

            logger.success(f'Aplicação {app.name} criada com sucesso!', category=LogCategory.CREATE, progress=100)

            return {'status': 'created', 'app_id': app.id}  # type: ignore

        except Exception as e:
            logger.error(
                f'Erro ao criar aplicação: {str(e)}',
                category=LogCategory.CREATE,
                metadata={'error_type': type(e).__name__, 'error_details': str(e)},
            )
            app.status = 'FAILED'
            app.save(update_fields=['status'])
            # --- GitHub Commit Status: marca failure ---
            if head_sha:
                github_adapter.set_deploy_failure(user.git_token, app.git, head_sha, app.name, str(e)[:100])
            raise

    @staticmethod
    def _get_instances(app_id: int, user_id: int) -> tuple[App, User]:
        """Busca App e User no banco de dados."""
        try:
            app = App.objects.get(id=app_id)
            user = User.objects.get(id=user_id)
            return app, user
        except App.DoesNotExist:
            raise App.DoesNotExist(f'App with id {app_id} not found')
        except User.DoesNotExist:
            raise User.DoesNotExist(f'User with id {user_id} not found')

    @staticmethod
    def _resolve_dokku_name(app: App, user: User) -> str:
        """
        Resolve o nome do app no Dokku.

        - Membros da Fábrica (is_fabric) e admins (is_superuser) podem ter nomes
          personalizados: se app.name_dokku já estiver preenchido, usa ele.
          Caso contrário, usa o nome do app diretamente (sem sufixo de projeto).
        - Usuários normais: nome-{project_id} (padrão).
        """
        can_customize = getattr(user, 'is_fabric', False) or user.is_superuser

        if can_customize and app.name_dokku:
            # Nome personalizado já definido (vindo do frontend)
            return slugify_dokku(app.name_dokku)

        if can_customize:
            # Membro da fábrica/admin sem nome custom: usa nome limpo
            return slugify_dokku(app.name)

        # Usuário normal: sufixo com ID do projeto para evitar colisão
        return slugify_dokku(f'{app.name}-{app.project.id}')

    @staticmethod
    def _ensure_dokku_app(
        task: Task, adapter: DokkuAdapter, app: App, dokku_app_name: str, logger: AppLogManager
    ) -> bool:
        """Cria o container se não existir. Retorna True se já existia."""
        task.update_state(
            state='PROGRESS', meta={'current': 5, 'total': 100, 'status': 'Verificando existência do app...'}
        )
        logger.info('Verificando se a aplicação já existe no Dokku...', category=LogCategory.CREATE, progress=5)

        if adapter.exists_app(dokku_app_name):
            return True

        task.update_state(
            state='PROGRESS', meta={'current': 10, 'total': 100, 'status': f'Criando container {dokku_app_name}...'}
        )
        logger.info(f'Criando container {dokku_app_name}...', category=LogCategory.CREATE, progress=10)

        output = adapter.create_app(app_name=dokku_app_name)
        logger.dokku(output, command=f'dokku apps:create {dokku_app_name}', category=LogCategory.CREATE, progress=15)

        return False

    @staticmethod
    def _apply_env_vars(
        task: Task, adapter: DokkuAdapter, dokku_app_name: str, env_vars: dict | None, logger: AppLogManager
    ):
        """Aplica variáveis de ambiente se fornecidas."""
        if env_vars:
            task.update_state(
                state='PROGRESS', meta={'current': 18, 'total': 100, 'status': 'Aplicando variáveis de ambiente...'}
            )
            logger.info(f'Aplicando {len(env_vars)} variáveis de ambiente...', category=LogCategory.CONFIG, progress=18)

            output = adapter.set_config(app_name=dokku_app_name, env_vars=env_vars)

            var_names = ', '.join(env_vars.keys())
            logger.dokku(
                output,
                command=f'dokku config:set {dokku_app_name} [vars: {var_names}]',
                category=LogCategory.CONFIG,
                progress=22,
            )
            logger.success('Variáveis de ambiente aplicadas com sucesso', category=LogCategory.CONFIG, progress=25)
        else:
            logger.info('Nenhuma variável de ambiente para configurar', category=LogCategory.CONFIG, progress=25)

    @staticmethod
    def _handle_deploy_keys(
        task: Task, d_adapter: DokkuAdapter, gh_adapter: GitHubAdapter, user: User, git_url: str, logger: AppLogManager
    ) -> str:
        """
        Verifica permissões e gera chaves SSH se necessário.
        Retorna a URL correta para usar (SSH para privado, original para público).
        """
        task.update_state(
            state='PROGRESS', meta={'current': 28, 'total': 100, 'status': 'Verificando permissões do GitHub...'}
        )
        logger.info('Verificando permissões do repositório GitHub...', category=LogCategory.GIT, progress=28)

        repo_name = git_url.rsplit('.com/', maxsplit=1)[-1].replace('.git', '')  # type: ignore

        user_git_repos_list = gh_adapter.list_user_repos(user_id=user.id)  # type: ignore
        user_git_repos = {repo.full_name: {'private': repo.private} for repo in user_git_repos_list}

        is_private = repo_name in user_git_repos and user_git_repos[repo_name].get('private', False)

        if is_private:
            task.update_state(
                state='PROGRESS', meta={'current': 32, 'total': 100, 'status': 'Gerando chaves de acesso seguro...'}
            )
            logger.info(
                f'Repositório {repo_name} é privado. Gerando chave de deploy...', category=LogCategory.GIT, progress=32
            )

            deploy_key = d_adapter.generate_git_deploy_key()
            logger.dokku(
                f'Chave gerada: {deploy_key[:50]}...', command='ssh-keygen', category=LogCategory.GIT, progress=35
            )

            deploy_key_result = gh_adapter.add_deploy_key(dokku_key=deploy_key, repo_name=repo_name, user_id=user.id)  # type: ignore
            if isinstance(deploy_key_result, dict) and deploy_key_result.get('status') == 'deploy keys disabled':
                # Lança exceção amigável para o frontend exibir tela de ajuda
                logger.error(
                    f'Deploy keys desabilitadas no repositório {repo_name}. Usuário deve ativar nas configurações do GitHub.',
                    category=LogCategory.GIT,
                    metadata={
                        'error_type': 'DeployKeysDisabled',
                        'error_details': deploy_key_result.get('error'),
                        'help_url': deploy_key_result.get('help_url'),
                    },
                    progress=40,
                )
                raise Exception(
                    f'As deploy keys estão desabilitadas para este repositório. Ative nas configurações do GitHub. Mais informações: {deploy_key_result.get("help_url")}'
                )
            logger.success(
                f'Chave de deploy adicionada ao repositório {repo_name}', category=LogCategory.GIT, progress=40
            )

            # Para repos privados, usar URL SSH
            ssh_url = https_to_ssh_url(git_url)
            logger.info(f'Usando URL SSH: {ssh_url}', category=LogCategory.GIT, progress=42)
            return ssh_url
        else:
            logger.info(
                f'Repositório {repo_name} é público. Chave de deploy não necessária.',
                category=LogCategory.GIT,
                progress=40,
            )
            return git_url

    @staticmethod
    def _configure_git(
        task: Task, adapter: DokkuAdapter, dokku_app_name: str, git_url: str, branch: str, logger: AppLogManager
    ):
        """Configura o remote do Git no Dokku. Etapa mais demorada com streaming de logs."""
        task.update_state(
            state='PROGRESS', meta={'current': 45, 'total': 100, 'status': 'Sincronizando repositório Git...'}
        )
        logger.info('Iniciando sincronização do repositório Git...', category=LogCategory.GIT, progress=45)
        logger.info(
            f'⏳ Clonando branch "{branch}"... Esta etapa pode demorar alguns minutos.',
            category=LogCategory.GIT,
            progress=50,
        )

        # Contador de linhas para calcular progresso incremental
        line_count = [0]  # Usando lista para poder modificar dentro do callback
        base_progress = 50
        max_progress = 85

        def on_log_line(line: str):
            """Callback chamado para cada linha de log do git:sync."""
            if not line.strip():
                return

            line_count[0] += 1
            # Progresso incremental entre 50% e 85%
            # Aumenta 0.5% a cada linha, até o máximo
            progress = min(base_progress + (line_count[0] * 0.5), max_progress - 1)

            logger.dokku(line, category=LogCategory.GIT, progress=int(progress))

        output = adapter.sync_git_streaming(
            app_name=dokku_app_name,
            git_url=git_url,
            branch=branch,
            on_line=on_log_line,
        )

        # Verifica se houve erro
        if 'Failed' in output:
            logger.error(f'Erro no git:sync: {output}', category=LogCategory.GIT, progress=85)
            raise RuntimeError(f'Falha ao sincronizar repositório: {output}')

        # Log final
        logger.dokku(
            f'✅ Sync concluído ({line_count[0]} linhas processadas)',
            command=f'dokku git:sync {dokku_app_name} {git_url} {branch}',
            category=LogCategory.GIT,
            progress=85,
        )

    @staticmethod
    def _get_head_sha(gh_adapter: GitHubAdapter, user: User, app: App) -> str | None:
        """Obtém o SHA do HEAD da branch no GitHub para marcar commit status."""
        try:
            from github import Github  # noqa: PLC0415

            repo_name = app.git.rsplit('.com/', maxsplit=1)[-1].replace('.git', '')
            gh = Github(user.git_token)
            repo = gh.get_repo(repo_name)
            branch = repo.get_branch(app.branch)
            return branch.commit.sha
        except Exception:
            return None

    @staticmethod
    def _setup_webhook(gh_adapter: GitHubAdapter, user: User, app: App, logger: AppLogManager):
        """Configura webhook no GitHub para deploy automático."""
        logger.info('Configurando webhook para deploy automático...', category=LogCategory.GIT, progress=86)

        # Extrai nome do repositório da URL
        repo_name = app.git.rsplit('.com/', maxsplit=1)[-1].replace('.git', '')

        try:
            result = gh_adapter.create_webhook(repo_name=repo_name, app_id=app.id, user_id=user.id)

            if result.get('status') == 'webhook criado':
                logger.success(
                    f"Webhook configurado! Deploys automáticos ativados para branch '{app.branch}'",
                    category=LogCategory.GIT,
                    progress=87,
                )
            elif result.get('status') == 'webhook já existe':
                logger.info('Webhook já estava configurado', category=LogCategory.GIT, progress=87)
            else:
                logger.warning(
                    f'Webhook: {result.get("status", "status desconhecido")}', category=LogCategory.GIT, progress=87
                )

        except Exception as e:
            # Webhook é opcional, não deve falhar a criação do app
            logger.warning(
                f'Não foi possível configurar webhook automático: {str(e)}',
                category=LogCategory.GIT,
                progress=87,
            )

    def _set_letsencrypt(self, dokku_app_name: str, logger: AppLogManager):
        """Configura Let's Encrypt para a aplicação."""
        dokku_adapter = DokkuAdapter()

        logger.info("Configurando certificado SSL (Let's Encrypt)...", category=LogCategory.SSL, progress=88)
        output = dokku_adapter.enable_letsencrypt(app_name=dokku_app_name)
        logger.dokku(
            output, command=f'dokku letsencrypt:enable {dokku_app_name}', category=LogCategory.SSL, progress=95
        )

    def _get_domain(self, name_dokku: str, logger: AppLogManager) -> str | None:
        """Obtém o domínio principal da aplicação Dokku."""

        dokku_adapter = DokkuAdapter()

        logger.info('Obtendo domínio principal da aplicação...', category=LogCategory.SSL, progress=97)
        domains = dokku_adapter.get_app_domain(app_name=name_dokku)
        logger.dokku(domains, command=f'dokku domains:report {name_dokku}', category=LogCategory.SSL, progress=99)
        return domains if domains else None
