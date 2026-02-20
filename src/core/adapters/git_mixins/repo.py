from github import Github, GithubException
from django.conf import settings


class GitRepoMixin:
    def list_user_repos(self, user_id: int):
        from core.auth_user.models import User  # noqa: PLC0415

        user = User.objects.get(id=user_id)
        gh = Github(user.git_token)
        repos = gh.get_user().get_repos()

        return repos

    def add_deploy_key(self, repo_name: str, dokku_key: str, user_id: int):
        from core.auth_user.models import User  # noqa: PLC0415

        user = User.objects.get(id=user_id)
        gh = Github(user.git_token)
        repo = gh.get_repo(repo_name)

        # Verifica se a chave já existe no repositório
        existing_keys = repo.get_keys()
        for key in existing_keys:
            # Compara apenas a parte da chave (sem o comentário no final)
            existing_key_part = key.key.split()[1] if len(key.key.split()) > 1 else key.key
            new_key_part = dokku_key.split()[1] if len(dokku_key.split()) > 1 else dokku_key

            if existing_key_part == new_key_part:
                return {'status': 'deploy key já existe', 'key_id': key.id}

        try:
            repo.create_key(title='dokku-deploy', key=dokku_key, read_only=False)
            return {'status': 'deploy key cadastrada'}
        except GithubException as e:
            # Erro: deploy key já existe em outro repositório
            if e.status == 422 and 'already in use' in str(e.data):
                return {'status': 'deploy key já existe em outro repositório'}
            # Erro: deploy keys desabilitadas no repositório
            if e.status == 422 and (
                ('Deploy keys are disabled' in str(e.data))
                or ('deploy keys are disabled' in str(e.data))
                or ('deploy keys are not enabled' in str(e.data))
            ):
                return {
                    'status': 'deploy keys disabled',
                    'error': 'As deploy keys estão desabilitadas para este repositório. Ative nas configurações do GitHub.',
                    'help_url': 'https://docs.github.com/en/developers/overview/managing-deploy-keys#enabling-deploy-keys-for-your-repository',
                }
            raise

    def create_webhook(self, repo_name: str, app_id: int, user_id: int) -> dict:
        """
        Cria um webhook no repositório GitHub para deploys automáticos.
        Verifica se já existe um webhook para o mesmo app antes de criar.
        """
        from core.auth_user.models import User  # noqa: PLC0415

        user = User.objects.get(id=user_id)
        gh = Github(user.git_token)
        repo = gh.get_repo(repo_name)

        # URL do webhook - usa a configuração do backend
        webhook_url = f'{settings.BACKEND_URL}/api/webhooks/github/{app_id}/'

        # Verifica se já existe um webhook para este app
        existing_hooks = repo.get_hooks()
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
            if e.status == 422:
                return {'status': 'erro ao criar webhook', 'error': str(e.data)}
            raise
