import logging

import requests
from django.conf import settings
from github import Github, GithubException

from core.adapters.git_utils import get_github_hook_events, normalize_webhook_url

logger = logging.getLogger(__name__)


class GitRepoMixin:
    @staticmethod
    def _format_github_error(data) -> str:
        """Normaliza o payload de erro do GitHub para logs e respostas."""
        if isinstance(data, dict):
            message = data.get('message')
            errors = data.get('errors')
            if errors:
                return f'{message} ({errors})' if message else str(errors)
            if message:
                return str(message)
        return str(data)

    def list_user_repos(self, user_id: int):
        from core.auth_user.models import User  # noqa: PLC0415

        user = User.objects.get(id=user_id)
        gh = Github(user.git_token)
        try:
            return gh.get_user().get_repos()
        except GithubException as e:
            if e.status in (401, 403):
                return {
                    'status': 'org_permission_denied',
                    'error': 'Permissao insuficiente para acessar organizacao. Reautorize seu token no GitHub.',
                    'error_type': 'OrgPermissionDenied',
                    'help_url': 'https://github.com/settings/tokens',
                }
            raise

    def add_deploy_key(self, repo_name: str, dokku_key: str, user_id: int):
        """
        Adiciona uma deploy key ao repositorio via API REST do GitHub.
        Usa requests diretamente para ter controle total sobre a resposta.
        """
        from core.auth_user.models import User  # noqa: PLC0415

        user = User.objects.get(id=user_id)
        token = user.git_token

        try:
            gh = Github(token)
            repo_obj = gh.get_repo(repo_name)
            existing_keys = repo_obj.get_keys()
            new_key_part = dokku_key.split()[1] if len(dokku_key.split()) > 1 else dokku_key
            for key in existing_keys:
                existing_key_part = key.key.split()[1] if len(key.key.split()) > 1 else key.key
                if existing_key_part == new_key_part:
                    logger.info('Deploy key ja existe no repositorio %s (key_id=%s)', repo_name, key.id)
                    return {'status': 'success', 'key_id': key.id, 'already_existed': True}
        except GithubException as e:
            logger.warning('Erro ao listar deploy keys existentes para %s: status=%s data=%s', repo_name, e.status, e.data)

        url = f'https://api.github.com/repos/{repo_name}/keys'
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        }
        payload = {
            'title': f'dokku-deploy-{repo_name.split("/")[-1]}',
            'key': dokku_key,
            'read_only': True,
        }

        logger.info('Criando deploy key para %s via POST %s', repo_name, url)

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
        except requests.RequestException as e:
            logger.error('Erro de rede ao criar deploy key para %s: %s', repo_name, e)
            raise Exception(f'Erro de rede ao criar deploy key: {e}') from e

        status_code = response.status_code
        response_body = response.text

        logger.info('Resposta da API GitHub para deploy key: status_code=%s', status_code)

        if status_code == 201:
            logger.info('Deploy key criada com sucesso no repositorio %s', repo_name)
            return {'status': 'success', 'key_id': response.json().get('id')}

        logger.error(
            'Falha ao criar deploy key para %s: status_code=%s body=%s',
            repo_name,
            status_code,
            response_body,
        )

        if status_code == 401:
            raise Exception(
                f'Token invalido ou expirado ao criar deploy key para {repo_name}. '
                f'Reautorize seu token no GitHub. (HTTP 401)'
            )

        if status_code == 403:
            raise Exception(
                f'Sem permissao para criar deploy key no repositorio {repo_name}. '
                f'Verifique se o token tem escopo "repo" (classic) ou permissao '
                f'"Administration: Read and write" (fine-grained). (HTTP 403)'
            )

        if status_code == 404:
            raise Exception(
                f'Repositorio {repo_name} nao encontrado ou token sem acesso. '
                f'Verifique se o repositorio existe e se o token tem acesso. (HTTP 404)'
            )

        if status_code == 422:
            body_str = response_body.lower()
            if 'already in use' in body_str or 'key is already in use' in body_str:
                raise Exception(
                    'A chave SSH ja esta em uso em outro repositorio GitHub. '
                    'O Dokku usa uma unica chave global; cada chave so pode ser usada em um repositorio privado. '
                    'Remova a chave duplicada ou use repositorios publicos. (HTTP 422)'
                )
            if 'deploy keys' in body_str and ('disabled' in body_str or 'not enabled' in body_str):
                return {
                    'status': 'deploy keys disabled',
                    'error': 'As deploy keys estao desabilitadas para este repositorio. Ative nas configuracoes do GitHub.',
                    'help_url': 'https://docs.github.com/en/developers/overview/managing-deploy-keys',
                }

        raise Exception(f'Falha ao criar deploy key para {repo_name}: HTTP {status_code} - {response_body}')

    def create_webhook(self, repo_name: str, app_id: int, user_id: int) -> dict:
        """Cria ou repara o webhook de deploy automatico no GitHub."""
        from core.auth_user.models import User  # noqa: PLC0415

        user = User.objects.get(id=user_id)
        gh = Github(user.git_token)
        webhook_url = f'{settings.BACKEND_URL}/api/webhooks/github/{app_id}/'

        try:
            repo = gh.get_repo(repo_name)
        except GithubException as e:
            if e.status in (403, 404):
                return {
                    'status': 'repositorio nao encontrado ou sem acesso',
                    'error': (
                        f'Nao foi possivel acessar o repositorio "{repo_name}". '
                        'Verifique se a URL do repositorio esta correta e se voce tem permissao '
                        'de Webhooks no repositorio. Se o repositorio pertence a uma organizacao, '
                        'a organizacao pode restringir o acesso de apps de terceiros. '
                        f'Detalhes: {self._format_github_error(e.data)}'
                    ),
                }
            raise

        config = {
            'url': webhook_url,
            'content_type': 'json',
        }
        webhook_secret = getattr(settings, 'GITHUB_WEBHOOK_SECRET', None)
        if webhook_secret:
            config['secret'] = webhook_secret

        try:
            existing_hooks = list(repo.get_hooks())
        except GithubException as e:
            if e.status in (403, 404):
                return {
                    'status': 'sem permissao para listar webhooks',
                    'error': (
                        f'O token atual consegue acessar "{repo_name}", mas nao consegue listar os webhooks. '
                        'No GitHub, listar hooks exige permissao "Webhooks: read" ou acesso administrativo ao repo. '
                        f'Detalhes: {self._format_github_error(e.data)}'
                    ),
                }
            raise

        expected_url = normalize_webhook_url(webhook_url)
        for hook in existing_hooks:
            if normalize_webhook_url(hook.config.get('url')) != expected_url:
                continue

            events = get_github_hook_events(hook)
            is_active = bool(hook.active)
            uses_json = hook.config.get('content_type') == 'json'
            has_push_event = 'push' in events
            should_update = not is_active or not uses_json or not has_push_event or bool(webhook_secret)

            if not should_update:
                return {'status': 'webhook ja existe', 'hook_id': hook.id, 'url': webhook_url}

            try:
                hook.edit(name='web', config=config, events=['push'], active=True)
                return {
                    'status': 'webhook atualizado',
                    'hook_id': hook.id,
                    'url': webhook_url,
                    'previous': {
                        'active': is_active,
                        'events': events,
                        'content_type': hook.config.get('content_type'),
                    },
                }
            except GithubException as e:
                if e.status in (403, 404):
                    return {
                        'status': 'sem permissao para atualizar webhook',
                        'error': (
                            f'O token atual nao tem permissao para atualizar webhooks em "{repo_name}". '
                            'No GitHub, atualizar hooks exige permissao "Webhooks: write" ou acesso administrativo ao repo. '
                            f'Detalhes: {self._format_github_error(e.data)}'
                        ),
                    }
                return {'status': 'erro ao atualizar webhook', 'error': self._format_github_error(e.data)}

        try:
            hook = repo.create_hook(name='web', config=config, events=['push'], active=True)
            return {'status': 'webhook criado', 'hook_id': hook.id, 'url': webhook_url}
        except GithubException as e:
            if e.status in (403, 404):
                return {
                    'status': 'sem permissao para criar webhook',
                    'error': (
                        f'O token atual nao tem permissao para criar webhooks em "{repo_name}". '
                        'No GitHub, criar hooks exige permissao "Webhooks: write" ou acesso administrativo ao repo. '
                        f'Detalhes: {self._format_github_error(e.data)}'
                    ),
                }
            if e.status == 422:
                return {'status': 'erro ao criar webhook', 'error': self._format_github_error(e.data)}
            raise
