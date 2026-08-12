from django.conf import settings

from applications.ports.i_github import IGitHubPort
from infrastructure.adapters.git_mixins import CommitStatusMixin, GitRepoMixin


class GitHubAdapter(GitRepoMixin, CommitStatusMixin, IGitHubPort):
    def __init__(self):
        self.client_id = settings.GITHUB_CLIENT_ID
        self.client_secret = settings.GITHUB_CLIENT_SECRET

    def get_branch_head_sha(self, repo_name: str, branch: str, user_id: int) -> str | None:
        """Get the HEAD commit SHA of a branch, best-effort (never raises)."""
        try:
            from github import Github  # noqa: PLC0415

            from identity.models import User  # noqa: PLC0415

            user = User.objects.get(id=user_id)
            gh = Github(user.git_token)
            repo = gh.get_repo(repo_name)
            return repo.get_branch(branch).commit.sha
        except Exception:
            return None
