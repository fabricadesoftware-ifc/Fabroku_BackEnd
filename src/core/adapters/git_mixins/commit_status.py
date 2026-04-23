"""
Mixin para atualizar o Commit Status no GitHub.

Referência: https://docs.github.com/en/rest/commits/statuses

Mostra os ícones de deploy (🟡 pending, ✅ success, ❌ failure)
diretamente nos commits do GitHub.
"""

import logging
import re

from django.conf import settings
from github import Github, GithubException

logger = logging.getLogger(__name__)


def _parse_repo_name(git_url: str) -> str | None:
    """Extrai 'owner/repo' de uma URL do GitHub (HTTPS ou SSH)."""
    # HTTPS: https://github.com/owner/repo.git
    match = re.match(r'https://github\.com/([^/]+/[^/]+?)(?:\.git)?$', git_url)
    if match:
        return match.group(1)
    # SSH: git@github.com:owner/repo.git
    match = re.match(r'git@github\.com:([^/]+/[^/]+?)(?:\.git)?$', git_url)
    if match:
        return match.group(1)
    return None


class CommitStatusMixin:
    """Mixin para gerenciar GitHub Commit Statuses."""

    def set_commit_status(  # noqa: PLR0913
        self,
        *,
        git_token: str,
        git_url: str,
        sha: str,
        state: str,
        description: str = '',
        target_url: str | None = None,
        context: str = 'fabroku/deploy',
    ) -> bool:
        """
        Atualiza o commit status no GitHub.

        Args:
            git_token: Token OAuth do usuário no GitHub.
            git_url: URL do repositório (HTTPS ou SSH).
            sha: SHA do commit.
            state: 'pending', 'success', 'failure' ou 'error'.
            description: Descrição curta (max 140 chars).
            target_url: URL para o painel do Fabroku (opcional).
            context: Identificador do status (ex: 'fabroku/deploy').

        Returns:
            True se o status foi atualizado, False se falhou.
        """
        repo_name = _parse_repo_name(git_url)
        if not repo_name:
            logger.warning('Não foi possível extrair owner/repo de: %s', git_url)
            return False

        if not git_token or not sha:
            logger.warning('git_token ou sha ausente, pulando commit status')
            return False

        try:
            gh = Github(git_token)
            repo = gh.get_repo(repo_name)
            commit = repo.get_commit(sha)

            commit.create_status(
                state=state,
                target_url=target_url or '',
                description=description[:140],
                context=context,
            )
            logger.info('Commit status [%s] definido para %s@%s', state, repo_name, sha[:7])
            return True

        except GithubException as e:
            logger.warning('Falha ao definir commit status: %s', e)
            return False
        except Exception as e:
            logger.warning('Erro inesperado ao definir commit status: %s', e)
            return False

    def set_deploy_pending(self, git_token: str, git_url: str, sha: str, app_name: str = '') -> bool:
        """Marca o commit como deploy em andamento (🟡)."""
        return self.set_commit_status(
            git_token=git_token,
            git_url=git_url,
            sha=sha,
            state='pending',
            description=f'Deploy em andamento{f" — {app_name}" if app_name else ""}',
            target_url=self._app_dashboard_url(app_name),
        )

    def set_deploy_success(self, git_token: str, git_url: str, sha: str, app_name: str = '') -> bool:
        """Marca o commit como deploy concluído (✅)."""
        return self.set_commit_status(
            git_token=git_token,
            git_url=git_url,
            sha=sha,
            state='success',
            description=f'Deploy concluído{f" — {app_name}" if app_name else ""}',
            target_url=self._app_dashboard_url(app_name),
        )

    def set_deploy_failure(  # noqa: PLR0913
        self, git_token: str, git_url: str, sha: str, app_name: str = '', error: str = ''
    ) -> bool:
        """Marca o commit como deploy falhou (❌)."""
        desc = f'Deploy falhou{f" — {app_name}" if app_name else ""}'
        if error:
            desc = f'{desc}: {error}'
        return self.set_commit_status(
            git_token=git_token,
            git_url=git_url,
            sha=sha,
            state='failure',
            description=desc,
            target_url=self._app_dashboard_url(app_name),
        )

    @staticmethod
    def _app_dashboard_url(app_name: str) -> str:
        """Retorna a URL do dashboard do app no frontend."""
        frontend_url = getattr(settings, 'FRONTEND_URL', 'https://fabroku.fabricadesoftware.ifc.edu.br')
        return f'{frontend_url}/dashboard' if not app_name else f'{frontend_url}/dashboard'
