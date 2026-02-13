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
        app.save(update_fields=['task_id', 'status'])

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
            # Verifica se o app existe no Dokku
            if not dokku_adapter.exists_app(dokku_app_name):
                logger.error(f'App {dokku_app_name} não existe no Dokku', category=LogCategory.DEPLOY)
                app.status = 'ERROR'
                app.save(update_fields=['status'])
                return {'status': 'error', 'message': 'App não existe no Dokku'}

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

            # Usa streaming para mostrar logs em tempo real
            # Converte URL HTTPS para SSH para usar deploy key
            git_url = https_to_ssh_url(app.git)

            output = dokku_adapter.sync_git_streaming(
                app_name=dokku_app_name,
                git_url=git_url,
                branch=app.branch,
                on_line=on_log_line,
            )

            if 'Failed' in output:
                logger.error(f'Erro no redeploy: {output}', category=LogCategory.DEPLOY, progress=90)
                app.status = 'ERROR'
                app.save(update_fields=['status'])
                if commit and git_token:
                    github_adapter.set_deploy_failure(git_token, app.git, commit, app.name, 'Build falhou')
                return {'status': 'error', 'message': output}

            # Sucesso
            app.status = 'RUNNING'
            app.save(update_fields=['status'])

            if commit and git_token:
                github_adapter.set_deploy_success(git_token, app.git, commit, app.name)

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
