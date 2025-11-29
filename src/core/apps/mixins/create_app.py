from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter, GitHubAdapter
from core.apps.models import App
from core.apps.utils import slugify_dokku
from core.auth_user.models import User
from core.logs.models import AppLogManager, LogCategory


class CreateAppMixin:
    """
    Mixin para criação de aplicações.
    Contém a task principal e métodos auxiliares estáticos para organização.
    """

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
        logger.info('Iniciando criação da aplicação...', category=LogCategory.CREATE, progress=5)

        dokku_app_name = slugify_dokku(f'{app.name}-{app.project.id}')
        dokku_adapter = DokkuAdapter()
        github_adapter = GitHubAdapter()

        try:
            if CreateAppMixin._ensure_dokku_app(task, dokku_adapter, app, dokku_app_name, logger):
                logger.warning(
                    f'Aplicação {dokku_app_name} já existe no Dokku', category=LogCategory.CREATE, progress=100
                )
                return {'status': 'already_exists', 'app_id': app.id}  # type: ignore

            CreateAppMixin._apply_env_vars(task, dokku_adapter, dokku_app_name, env_vars, logger)

            CreateAppMixin._handle_deploy_keys(task, dokku_adapter, github_adapter, user, app.git, logger)

            CreateAppMixin._configure_git(task, dokku_adapter, dokku_app_name, app.git, logger)

            app.status = 'RUNNING'
            app.name_dokku = dokku_app_name
            app.save()

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
    def _ensure_dokku_app(
        task: Task, adapter: DokkuAdapter, app: App, dokku_app_name: str, logger: AppLogManager
    ) -> bool:
        """Cria o container se não existir. Retorna True se já existia."""
        task.update_state(
            state='PROGRESS', meta={'current': 10, 'total': 100, 'status': 'Verificando existência do app...'}
        )
        logger.info('Verificando se a aplicação já existe no Dokku...', category=LogCategory.CREATE, progress=10)

        if adapter.exists_app(dokku_app_name):
            return True

        task.update_state(
            state='PROGRESS', meta={'current': 30, 'total': 100, 'status': f'Criando container {dokku_app_name}...'}
        )
        logger.info(f'Criando container {dokku_app_name}...', category=LogCategory.CREATE, progress=30)

        output = adapter.create_app(app_name=dokku_app_name)
        logger.dokku(output, command=f'dokku apps:create {dokku_app_name}', category=LogCategory.CREATE, progress=35)

        return False

    @staticmethod
    def _configure_git(task: Task, adapter: DokkuAdapter, dokku_app_name: str, git_url: str, logger: AppLogManager):
        """Configura o remote do Git no Dokku."""
        task.update_state(
            state='PROGRESS', meta={'current': 90, 'total': 100, 'status': 'Configurando repositório Git...'}
        )
        logger.info('Configurando repositório Git no Dokku...', category=LogCategory.GIT, progress=90)

        output = adapter.set_git_remote(app_name=dokku_app_name, git_url=git_url)
        logger.dokku(
            output, command=f'dokku git:sync {dokku_app_name} {git_url}', category=LogCategory.GIT, progress=95
        )

    @staticmethod
    def _handle_deploy_keys(
        task: Task, d_adapter: DokkuAdapter, gh_adapter: GitHubAdapter, user: User, git_url: str, logger: AppLogManager
    ):
        """Verifica permissões e gera chaves SSH se necessário."""
        task.update_state(
            state='PROGRESS', meta={'current': 70, 'total': 100, 'status': 'Verificando permissões do GitHub...'}
        )
        logger.info('Verificando permissões do repositório GitHub...', category=LogCategory.GIT, progress=70)

        repo_name = git_url.rsplit('.com/', maxsplit=1)[-1].replace('.git', '')

        user_git_repos_list = gh_adapter.list_user_repos(user_id=user.id)  # type: ignore
        user_git_repos = {repo.full_name: {'private': repo.private} for repo in user_git_repos_list}

        if repo_name in user_git_repos and user_git_repos[repo_name].get('private', False):
            task.update_state(
                state='PROGRESS', meta={'current': 75, 'total': 100, 'status': 'Gerando chaves de acesso seguro...'}
            )
            logger.info(
                f'Repositório {repo_name} é privado. Gerando chave de deploy...', category=LogCategory.GIT, progress=75
            )

            deploy_key = d_adapter.generate_git_deploy_key()
            logger.dokku(
                f'Chave gerada: {deploy_key[:50]}...', command='ssh-keygen', category=LogCategory.GIT, progress=78
            )

            gh_adapter.add_deploy_key(dokku_key=deploy_key, repo_name=repo_name, user_id=user.id)  # type: ignore
            logger.success(
                f'Chave de deploy adicionada ao repositório {repo_name}', category=LogCategory.GIT, progress=85
            )
        else:
            logger.info(
                f'Repositório {repo_name} é público. Chave de deploy não necessária.',
                category=LogCategory.GIT,
                progress=85,
            )

    @staticmethod
    def _apply_env_vars(
        task: Task, adapter: DokkuAdapter, dokku_app_name: str, env_vars: dict | None, logger: AppLogManager
    ):
        """Aplica variáveis de ambiente se fornecidas."""
        if env_vars:
            task.update_state(
                state='PROGRESS', meta={'current': 50, 'total': 100, 'status': 'Aplicando variáveis de ambiente...'}
            )
            logger.info(f'Aplicando {len(env_vars)} variáveis de ambiente...', category=LogCategory.CONFIG, progress=50)

            output = adapter.set_config(app_name=dokku_app_name, env_vars=env_vars)

            # Log das variáveis (sem mostrar valores sensíveis)
            var_names = ', '.join(env_vars.keys())
            logger.dokku(
                output,
                command=f'dokku config:set {dokku_app_name} [vars: {var_names}]',
                category=LogCategory.CONFIG,
                progress=60,
            )
            logger.success('Variáveis de ambiente aplicadas com sucesso', category=LogCategory.CONFIG, progress=65)
        else:
            logger.info('Nenhuma variável de ambiente para configurar', category=LogCategory.CONFIG, progress=65)
