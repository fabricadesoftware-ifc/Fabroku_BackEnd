import datetime
import logging
import re
from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter, GitHubAdapter
from core.apps.models import App
from core.auth_user.models import User
from core.logs.models import AppLogManager, LogCategory

py_logger = logging.getLogger(__name__)


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

def https_to_auth_url(url: str, token: str) -> str:
    """
    Adiciona token de autenticação na URL HTTPS do GitHub.
    https://github.com/user/repo.git -> https://x-access-token:{token}@github.com/user/repo.git
    """
    match = re.match(r'https://github\.com/(.+)', url)
    if match:
        return f'https://x-access-token:{token}@github.com/{match.group(1)}'
    return url

class RedeployAppMixin:
    """Mixin para redeploy de aplicações via webhook."""

    @shared_task(bind=True)
    def redeploy_app(self, app_id: int, commit: str | None = None) -> dict:
        """
        Faz redeploy de uma aplicação existente.
        Chamado pelo webhook do GitHub quando há push na branch configurada.
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            app = App.objects.get(id=app_id)
        except App.DoesNotExist:
            return {'status': 'error', 'message': f'App {app_id} not found'}

        # Atualiza task_id e status
        app.task_id = task_id
        app.status = 'DEPLOYING'
        if commit:
            app.last_commit_sha = commit
        save_fields = ['task_id', 'status']
        if commit:
            save_fields.append('last_commit_sha')
        app.save(update_fields=save_fields)

        # Inicializa logger
        logger = AppLogManager(app, task_id)
        logger.info(
            f'Iniciando redeploy da aplicação (commit: {commit[:7] if commit else "latest"})...',
            category=LogCategory.DEPLOY,
            progress=5,
        )

        # --- GitHub Commit Status ---
        github_adapter = GitHubAdapter()
        git_token = RedeployAppMixin._get_git_token(app)
        if not git_token:
            py_logger.warning(
                'Commit status ignorado para app %s: nenhum usuário do projeto tem git_token',
                app.name,
            )
            logger.warning(
                'Commit status indisponível: nenhum usuário do projeto tem token GitHub',
                category=LogCategory.DEPLOY,
            )
        if not commit:
            py_logger.warning('Commit status ignorado para app %s: SHA do commit não fornecido', app.name)
        if commit and git_token:
            py_logger.info('Setando commit status pending para %s @ %s', app.name, commit[:7])
            github_adapter.set_deploy_pending(git_token, app.git, commit, app.name)

        dokku_adapter = DokkuAdapter()
        dokku_app_name = app.name_dokku

        if not dokku_app_name:
            logger.error('App não tem name_dokku configurado', category=LogCategory.DEPLOY)
            return {'status': 'error', 'message': 'App não tem name_dokku'}

        try:
            # Garante que serviços linkados estejam rodando antes do redeploy
            from core.apps.models import Service  # noqa: PLC0415

            for svc in Service.objects.filter(app=app):
                if svc.container_name and svc.service_type == 'postgres':
                    try:
                        dokku_adapter.start_database(svc.container_name)
                    except Exception:
                        pass

            # Verifica se o app existe no Dokku
            if not dokku_adapter.exists_app(dokku_app_name):
                logger.error(f'App {dokku_app_name} não existe no Dokku', category=LogCategory.DEPLOY)
                app.status = 'ERROR'
                app.save(update_fields=['status'])
                return {'status': 'error', 'message': 'App não existe no Dokku'}

            # Aplica env vars atualizadas (caso tenham mudado desde a criação)
            if app.variables:
                task.update_state(
                    state='PROGRESS',
                    meta={'current': 5, 'total': 100, 'status': 'Sincronizando variáveis de ambiente...'},
                )
                logger.info('Aplicando variáveis de ambiente atualizadas...', category=LogCategory.CONFIG, progress=5)
                dokku_adapter.set_config(app_name=dokku_app_name, env_vars=app.variables)

            task.update_state(
                state='PROGRESS',
                meta={'current': 10, 'total': 100, 'status': 'Sincronizando repositório...'},
            )
            logger.info('Sincronizando repositório Git...', category=LogCategory.GIT, progress=10)

            # Contador para progresso incremental
            line_count = [0]
            base_progress = 10
            max_progress = 90

            def on_log_line(line: str):
                if not line.strip():
                    return
                line_count[0] += 1
                progress = min(base_progress + (line_count[0] * 0.5), max_progress - 1)
                progress = int(progress)
                logger.dokku(line, category=LogCategory.GIT, progress=progress)
                task.update_state(
                    state='PROGRESS',
                    meta={'current': progress, 'total': 100, 'status': line.strip()[:120]},
                )

            # Decide a URL para git:sync.
            # Se o repo é privado, o create_app já salvou a URL SSH no app.git.
            # Se é público, a URL é HTTPS. Respeita o que foi definido na criação.
            # Também verifica via GitHub API se temos token disponível.
            git_url = app.git

            if git_url.startswith('git@'):
                # Já é SSH (repo privado legado)
                logger.info(
                    'Usando URL SSH (repositório privado)',
                    category=LogCategory.GIT,
                    progress=10,
                )
            else:
                # Verifica se o repo é privado para usar HTTPS com token
                is_private = False
                if git_token:
                    try:
                        from github import Github  # noqa: PLC0415

                        repo_name = git_url.rsplit('.com/', maxsplit=1)[-1].replace('.git', '')
                        gh = Github(git_token)
                        repo = gh.get_repo(repo_name)
                        is_private = repo.private
                    except Exception:
                        pass

                if is_private and git_token:
                    git_url = https_to_auth_url(app.git, git_token)
                    logger.info(
                        'Repositório privado detectado, usando HTTPS com token',
                        category=LogCategory.GIT,
                        progress=10,
                    )
                else:
                    logger.info(
                        'Usando URL HTTPS (repositório público)',
                        category=LogCategory.GIT,
                        progress=10,
                    )

            output = dokku_adapter.sync_git_streaming(
                app_name=dokku_app_name,
                git_url=git_url,
                branch=app.branch,
                on_line=on_log_line,
            )

            if 'Failed' in output or 'failed' in output.lower():
                logger.error(f'Erro no redeploy: {output}', category=LogCategory.DEPLOY, progress=90)
                app.status = 'ERROR'
                app.save(update_fields=['status'])
                if commit and git_token:
                    github_adapter.set_deploy_failure(git_token, app.git, commit, app.name, 'Build falhou')
                return {'status': 'error', 'message': output}

            # Sucesso
            app.status = 'RUNNING'
            app.save(update_fields=['status'])

            # Garante Let's Encrypt e domínio (caso tenha falhado na criação)
            if not app.domain or not dokku_adapter.get_app_domain(dokku_app_name):
                logger.info('Verificando/reativando Let\'s Encrypt...', category=LogCategory.SSL, progress=90)
                try:
                    dokku_adapter.enable_letsencrypt(app_name=dokku_app_name)
                except Exception:
                    logger.warning('Let\'s Encrypt falhou, tentando obter domínio mesmo assim', category=LogCategory.SSL)

                domain = dokku_adapter.get_app_domain(dokku_app_name)
                if domain:
                    app.domain = domain
                    app.save(update_fields=['domain'])
                    logger.success(f'Domínio configurado: {domain}', category=LogCategory.SSL, progress=95)

            if commit and git_token:
                github_adapter.set_deploy_success(git_token, app.git, commit, app.name)

            app.updated_at = datetime.datetime.now()  # Trigger update
            app.save(update_fields=['updated_at'])

            logger.success(
                f'Redeploy concluído com sucesso! ({line_count[0]} linhas processadas)',
                category=LogCategory.DEPLOY,
                progress=100,
            )

            return {
                'status': 'success',
                'app_id': app_id,
                'commit': commit,
                'dokku_app': dokku_app_name,
            }

        except Exception as e:
            logger.error(f'Erro no redeploy: {str(e)}', category=LogCategory.DEPLOY)
            app.status = 'ERROR'
            app.save(update_fields=['status'])
            if commit and git_token:
                github_adapter.set_deploy_failure(git_token, app.git, commit, app.name, str(e)[:100])
            raise

    @staticmethod
    def _get_git_token(app: App) -> str | None:
        """Obtém o git_token de um usuário do projeto que tenha acesso ao repo."""
        from github import Github, GithubException  # noqa: PLC0415

        users_with_token = app.project.users.exclude(git_token__isnull=True).exclude(git_token='')
        repo_name = (
            app.git.rsplit('.com/', maxsplit=1)[-1].replace('.git', '') if app.git and '.com/' in app.git else None
        )

        for user in users_with_token:
            if not repo_name:
                # Sem repo pra testar, retorna o primeiro token disponível
                return user.git_token
            try:
                gh = Github(user.git_token)
                gh.get_repo(repo_name)
                py_logger.info('Token válido para repo %s via usuário %s', repo_name, user.username or user.id)
                return user.git_token
            except GithubException:
                py_logger.warning('Token do usuário %s não tem acesso ao repo %s', user.username or user.id, repo_name)
                continue
            except Exception:
                continue

        py_logger.warning('Nenhum token com acesso ao repo %s', repo_name)
        return None
