import logging
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings
from github import Github, GithubException

from core.adapters import GitHubAdapter
from core.adapters.git_utils import build_github_auth_url, parse_github_repo_name
from core.apps.models import App
from core.auth_user.models import User

logger = logging.getLogger(__name__)

GITHUB_API_TIMEOUT_SECONDS = 8
HTTP_OK = 200
HTTP_AUTH_OR_NOT_FOUND = {401, 403, 404}


def display_user(user: User | None) -> str | None:
    if not user:
        return None
    return user.name or user.email or f'user#{user.id}'


def iter_project_users_with_git_token(app: App, preferred_user: User | None = None):
    """Itera tokens GitHub conhecidos, priorizando o usuario que iniciou a acao."""
    yielded_ids = set()

    if preferred_user and preferred_user.git_token:
        yielded_ids.add(preferred_user.id)
        yield preferred_user

    queryset = app.project.users.exclude(git_token__isnull=True).exclude(git_token='')
    if yielded_ids:
        queryset = queryset.exclude(id__in=yielded_ids)

    yield from queryset


@dataclass
class GitHubAccessResult:
    repo_name: str | None
    user: User | None
    repo: Any | None
    attempts: list[dict]

    @property
    def token(self) -> str | None:
        return self.user.git_token if self.user else None


@dataclass
class GitSyncPlan:
    ok: bool
    git_url: str | None
    strategy: str
    message: str
    token: str | None = None
    token_user: User | None = None
    repo_name: str | None = None
    repo_private: bool | None = None
    attempts: list[dict] | None = None


def find_project_user_for_github_repo(
    app: App,
    preferred_user: User | None = None,
    *,
    require_hook_access: bool = False,
) -> GitHubAccessResult:
    """
    Procura um token do projeto que consiga acessar o repositorio.

    Quando require_hook_access=True, tambem valida que o token consegue listar
    webhooks, que e o minimo para diagnosticar/reparar a integracao.
    """
    repo_name = parse_github_repo_name(app.git)
    attempts = []

    if not repo_name:
        return GitHubAccessResult(repo_name=None, user=None, repo=None, attempts=attempts)

    for project_user in iter_project_users_with_git_token(app, preferred_user=preferred_user):
        try:
            gh = Github(project_user.git_token)
            repo = gh.get_repo(repo_name)
            if require_hook_access:
                list(repo.get_hooks())
            return GitHubAccessResult(repo_name=repo_name, user=project_user, repo=repo, attempts=attempts)
        except GithubException as exc:
            attempts.append({
                'user': display_user(project_user),
                'status': exc.status,
                'message': _format_github_exception(exc),
            })
        except Exception as exc:
            attempts.append({
                'user': display_user(project_user),
                'status': 'unexpected',
                'message': str(exc),
            })

    return GitHubAccessResult(repo_name=repo_name, user=None, repo=None, attempts=attempts)


def ensure_github_webhook(
    app: App,
    preferred_user: User | None = None,
    *,
    github_adapter: GitHubAdapter | None = None,
) -> dict:
    """
    Cria ou repara o webhook de um app tentando todos os tokens do projeto.

    O retorno sempre e estruturado para poder ser usado tanto por task quanto
    por endpoint HTTP sem duplicar regra de negocio.
    """
    if not app.git:
        return {
            'ok': False,
            'status': 'git_url ausente',
            'error': 'App nao tem URL do repositorio Git configurada.',
            'attempts': [],
        }

    repo_name = parse_github_repo_name(app.git)
    if not repo_name:
        return {
            'ok': False,
            'status': 'git_url invalida',
            'error': f'Nao foi possivel extrair owner/repo de: {app.git}',
            'attempts': [],
        }

    candidate_users = list(iter_project_users_with_git_token(app, preferred_user=preferred_user))
    if not candidate_users:
        return {
            'ok': False,
            'status': 'sem token github',
            'error': 'Nenhum usuario do projeto tem token GitHub salvo para configurar o webhook.',
            'repo': repo_name,
            'attempts': [],
        }

    adapter = github_adapter or GitHubAdapter()
    webhook_url = f'{settings.BACKEND_URL}/api/webhooks/github/{app.id}/'
    attempts = []

    for candidate_user in candidate_users:
        result = adapter.create_webhook(
            repo_name=repo_name,
            app_id=app.id,
            user_id=candidate_user.id,
        )
        status_value = result.get('status', 'unknown')

        logger.info(
            'Webhook setup para app %s via %s: %s (URL: %s)',
            app.name,
            display_user(candidate_user),
            result,
            webhook_url,
        )

        if _is_webhook_success_status(status_value):
            return {
                'ok': True,
                'status': status_value,
                'webhook_url': webhook_url,
                'backend_url': settings.BACKEND_URL,
                'repo': repo_name,
                'hook_id': result.get('hook_id'),
                'configured_by': display_user(candidate_user),
                'attempts': attempts,
            }

        attempts.append({
            'user': display_user(candidate_user),
            'status': status_value,
            'error': result.get('error'),
        })

    return {
        'ok': False,
        'status': 'webhook nao configurado',
        'error': (
            'Nao foi possivel configurar o webhook com nenhum token do projeto. '
            'Verifique se ao menos um membro tem permissao de Webhooks no repositorio GitHub.'
        ),
        'repo': repo_name,
        'webhook_url': webhook_url,
        'attempts': attempts,
    }


def resolve_git_sync_plan(app: App, preferred_user: User | None = None) -> GitSyncPlan:
    """
    Decide qual URL deve ser usada no dokku git:sync.

    Repos GitHub privados sempre precisam de token valido. Quando nenhum token
    existe, tentamos provar que o repo e publico pela API antes de seguir sem
    credencial. Isso transforma falhas misteriosas do Git em mensagens claras.
    """
    git_url = app.git

    if git_url.startswith('git@') or git_url.startswith('ssh://'):
        return GitSyncPlan(
            ok=True,
            git_url=git_url,
            strategy='ssh',
            message='Usando URL SSH configurada para sincronizar o repositorio.',
        )

    repo_name = parse_github_repo_name(git_url)
    if not repo_name:
        return GitSyncPlan(
            ok=True,
            git_url=git_url,
            strategy='raw',
            message='URL Git nao e GitHub ou nao pode ser validada automaticamente.',
        )

    access = find_project_user_for_github_repo(app, preferred_user=preferred_user)
    if access.user and access.token:
        return GitSyncPlan(
            ok=True,
            git_url=build_github_auth_url(git_url, access.token),
            strategy='github_token',
            message=f'Usando HTTPS autenticado com token de {display_user(access.user)}.',
            token=access.token,
            token_user=access.user,
            repo_name=repo_name,
            repo_private=bool(getattr(access.repo, 'private', False)),
            attempts=access.attempts,
        )

    public_check = check_public_github_repo(repo_name)
    if public_check.get('ok'):
        return GitSyncPlan(
            ok=True,
            git_url=git_url,
            strategy='github_public',
            message='Repositorio GitHub acessivel publicamente; usando HTTPS sem credencial.',
            repo_name=repo_name,
            repo_private=False,
            attempts=access.attempts,
        )

    if public_check['status'] == 'unavailable':
        return GitSyncPlan(
            ok=True,
            git_url=git_url,
            strategy='github_public_unverified',
            message=(
                'Nao foi possivel confirmar se o repositorio e publico agora; '
                'tentando HTTPS sem credencial como fallback.'
            ),
            repo_name=repo_name,
            repo_private=None,
            attempts=access.attempts + [public_check],
        )

    return GitSyncPlan(
        ok=False,
        git_url=None,
        strategy='github_token_required',
        message=(
            f'O repositorio {repo_name} nao esta acessivel publicamente e nenhum token GitHub '
            'do projeto conseguiu acessa-lo. Reautorize o GitHub com acesso ao repositorio '
            'ou adicione ao projeto alguem que tenha permissao nesse repo.'
        ),
        repo_name=repo_name,
        repo_private=True,
        attempts=access.attempts + [public_check],
    )


def check_public_github_repo(repo_name: str) -> dict:
    url = f'https://api.github.com/repos/{repo_name}'
    headers = {
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }

    try:
        response = requests.get(url, headers=headers, timeout=GITHUB_API_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return {
            'status': 'unavailable',
            'message': f'Nao foi possivel consultar o GitHub agora: {exc}',
        }

    if response.status_code == HTTP_OK:
        data = response.json()
        if data.get('private'):
            return {
                'ok': False,
                'status': 'token_required',
                'http_status': response.status_code,
                'private': True,
                'message': 'Repositorio privado exige autenticacao.',
            }
        return {
            'ok': True,
            'status': 'public',
            'private': bool(data.get('private')),
        }

    if response.status_code in HTTP_AUTH_OR_NOT_FOUND:
        return {
            'ok': False,
            'status': 'token_required',
            'http_status': response.status_code,
            'message': 'Repositorio nao acessivel sem autenticacao.',
        }

    return {
        'status': 'unavailable',
        'http_status': response.status_code,
        'message': f'GitHub retornou HTTP {response.status_code} ao validar repositorio publico.',
    }


def _is_webhook_success_status(status_value: str) -> bool:
    return status_value in {'webhook criado', 'webhook atualizado'} or (
        status_value.startswith('webhook') and 'existe' in status_value
    )


def _format_github_exception(exc: GithubException) -> str:
    data = getattr(exc, 'data', None)
    if isinstance(data, dict):
        message = data.get('message')
        if message:
            return str(message)
    return str(data or exc)
