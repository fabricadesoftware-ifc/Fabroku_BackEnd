from django.http import JsonResponse
from github import Github


class GitRepoMixin:

    def list_user_repos(self, user_id: int):
        from core.auth_user.models import User

        user = User.objects.get(id=user_id)
        gh = Github(user.git_token)
        repos = gh.get_user().get_repos()

        return JsonResponse({
            "repos": [r.full_name for r in repos]
        })

    def add_deploy_key(self, repo_name: str, dokku_key: str, user_id: int):
        from core.auth_user.models import User

        user = User.objects.get(id=user_id)
        gh = Github(user.git_token)
        repo = gh.get_repo(repo_name)

        repo.create_key(
            title="dokku-deploy",
            key=dokku_key,
            read_only=False
        )

        return JsonResponse({"status": "deploy key cadastrada"})
