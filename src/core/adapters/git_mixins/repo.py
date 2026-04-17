from github import Github, GithubException
from django.conf import settings

import logging
import requests

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
            repos = gh.get_user().get_repos()
            return repos
        except GithubException as e:
            # Detecta erro de permissão ao acessar org
            if e.status in (401, 403):
                return {
                    'status': 'org_permission_denied',
                    'error': 'Permissão insuficiente para acessar organização. Reautorize seu token no GitHub.',
                    'error_type': 'OrgPermissionDenied',
                    'help_url': 'https://github.com/settings/tokens',
                }
            raise

    def add_deploy_key(self, repo_name: str, dokku_key: str, user_id: int):
        """
        Adiciona uma deploy key ao repositório via API REST do GitHub.
        Usa requests diretamente para ter controle total sobre a resposta.
        Retorna dict com 'status' indicando resultado.
        Lança exceção em caso de falha irrecuperável.
        """
        from core.auth_user.models import User  # noqa: PLC0415

        user = User.objects.get(id=user_id)
        token = user.git_token

        # ---- Verificar se a chave já existe (via PyGithub, OK para leitura) ----
        try:
            gh = Github(token)
            repo_obj = gh.get_repo(repo_name)
            existing_keys = repo_obj.get_keys()
            new_key_part = dokku_key.split()[1] if len(dokku_key.split()) > 1 else dokku_key
            for key in existing_keys:
                existing_key_part = key.key.split()[1] if len(key.key.split()) > 1 else key.key
                if existing_key_part == new_key_part:
                    logger.info(f'Deploy key já existe no repositório {repo_name} (key_id={key.id})')
                    return {'status': 'success', 'key_id': key.id, 'already_existed': True}
        except GithubException as e:
            logger.warning(f'Erro ao listar deploy keys existentes para {repo_name}: status={e.status} data={e.data}')
            # Continua tentando criar mesmo assim

        # ---- Criar deploy key via API REST para controle total ----
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

        logger.info(f'Criando deploy key para {repo_name} via POST {url}')

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
        except requests.RequestException as e:
            logger.error(f'Erro de rede ao criar deploy key para {repo_name}: {e}')
            raise Exception(f'Erro de rede ao criar deploy key: {e}') from e

        status_code = response.status_code
        response_body = response.text

        logger.info(f'Resposta da API GitHub para deploy key: status_code={status_code}')

        if status_code == 201:
            logger.info(f'Deploy key criada com sucesso no repositório {repo_name}')
            return {'status': 'success', 'key_id': response.json().get('id')}

        # ---- Tratar erros específicos ----
        logger.error(f'Falha ao criar deploy key para {repo_name}: status_code={status_code} body={response_body}')

        if status_code == 401:
            raise Exception(
                f'Token inválido ou expirado ao criar deploy key para {repo_name}. '
                f'Reautorize seu token no GitHub. (HTTP 401)'
            )

        if status_code == 403:
            raise Exception(
                f'Sem permissão para criar deploy key no repositório {repo_name}. '
                f'Verifique se o token tem escopo "repo" (classic) ou permissão '
                f'"Administration: Read and write" (fine-grained). (HTTP 403)'
            )

        if status_code == 404:
            raise Exception(
                f'Repositório {repo_name} não encontrado ou token sem acesso. '
                f'Verifique se o repositório existe e se o token tem acesso. (HTTP 404)'
            )

        if status_code == 422:
            body_str = response_body.lower()
            if 'already in use' in body_str or 'key is already in use' in body_str:
                raise Exception(
                    f'A chave SSH já está em uso em outro repositório GitHub. '
                    f'O Dokku usa uma única chave global — cada chave só pode ser usada em um repositório privado. '
                    f'Remova a chave duplicada ou use repositórios públicos. (HTTP 422)'
                )
            if 'deploy keys' in body_str and ('disabled' in body_str or 'not enabled' in body_str):
                return {
                    'status': 'deploy keys disabled',
                    'error': 'As deploy keys estão desabilitadas para este repositório. Ative nas configurações do GitHub.',
                    'help_url': 'https://docs.github.com/en/developers/overview/managing-deploy-keys',
                }

        # Erro genérico
        raise Exception(f'Falha ao criar deploy key para {repo_name}: HTTP {status_code} — {response_body}')

    def create_webhook(self, repo_name: str, app_id: int, user_id: int) -> dict:
        """
        Cria um webhook no repositório GitHub para deploys automáticos.
        Verifica se já existe um webhook para o mesmo app antes de criar.
        """
        from core.auth_user.models import User  # noqa: PLC0415

        user = User.objects.get(id=user_id)
        gh = Github(user.git_token)

        # URL do webhook - usa a configuração do backend
        webhook_url = f'{settings.BACKEND_URL}/api/webhooks/github/{app_id}/'

        try:
            repo = gh.get_repo(repo_name)
        except GithubException as e:
            if e.status in (403, 404):
                return {
                    'status': 'repositório não encontrado ou sem acesso',
                    'error': (
                        f'Não foi possível acessar o repositório "{repo_name}". '
                        'Verifique se a URL do repositório está correta e se você tem '
                        'permissão de administrador (para criar webhooks) no repositório. '
                        'Se o repositório pertence a uma organização, a organização pode '
                        'restringir o acesso de apps de terceiros. '
                        f'Detalhes: {self._format_github_error(e.data)}'
                    ),
                }
            raise

        # Verifica se já existe um webhook para este app
        try:
            existing_hooks = list(repo.get_hooks())
        except GithubException as e:
            if e.status in (403, 404):
                return {
                    'status': 'sem permissão para listar webhooks',
                    'error': (
                        f'O token atual consegue acessar "{repo_name}", mas não consegue listar os webhooks. '
                        'No GitHub, listar hooks exige permissão "Webhooks: read" ou acesso administrativo ao repo. '
                        f'Detalhes: {self._format_github_error(e.data)}'
                    ),
                }
            raise

        for hook in existing_hooks:
            if hook.config.get('url') == webhook_url:
                return {'status': 'webhook já existe', 'hook_id': hook.id}

        # Configuração do webhook
        config = {
            'url': webhook_url,
            'content_type': 'json',
        }

        # Adiciona secret se configurado
        webhook_secret = getattr(settings, 'GITHUB_WEBHOOK_SECRET', None)
        if webhook_secret:
            config['secret'] = webhook_secret

        try:
            hook = repo.create_hook(
                name='web',
                config=config,
                events=['push'],
                active=True,
            )
            return {'status': 'webhook criado', 'hook_id': hook.id, 'url': webhook_url}
        except GithubException as e:
            if e.status in (403, 404):
                return {
                    'status': 'sem permissão para criar webhook',
                    'error': (
                        f'O token atual não tem permissão para criar webhooks em "{repo_name}". '
                        'No GitHub, criar hooks exige permissão "Webhooks: write" ou acesso administrativo ao repo. '
                        f'Detalhes: {self._format_github_error(e.data)}'
                    ),
                }
            if e.status == 422:
                return {'status': 'erro ao criar webhook', 'error': self._format_github_error(e.data)}
            raise
