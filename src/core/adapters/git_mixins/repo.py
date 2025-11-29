from github import Github


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

        repo.create_key(title='dokku-deploy', key=dokku_key, read_only=False)

        return {'status': 'deploy key cadastrada'}
