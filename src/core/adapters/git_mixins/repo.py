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
            if e.status == 422 and 'already in use' in str(e.data):
                return {'status': 'deploy key já existe em outro repositório'}
            raise

    def create_webhook(repo_name: str, project_id: int, user_id: int):
        from core.auth_user.models import User  # noqa: PLC0415
        user = User.objects.get(id=user_id)

        gh = Github(user.git_token)
        repo = gh.get_repo(repo_name)

        config = {
            "url": f"https://fabroku.com/deploy/hooks/{project_id}",
            "content_type": "json",
            "secret": settings.GITHUB_WEBHOOK_SECRET,
        }

        repo.create_hook(
            name="web",
            config=config,
            events=["push"],
            active=True
        )
