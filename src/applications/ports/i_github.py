"""Port (interface) for GitHub operations.

Mirrors the real methods already implemented by `GitRepoMixin` and
`CommitStatusMixin` (composed into `GitHubAdapter`), so `GitHubAdapter`
satisfies this interface without any bridging code. Deploy-key removal has
no real implementation anywhere in the codebase today (deploy keys aren't
currently a live feature) and is intentionally left out until that logic
actually exists.
"""
from abc import ABC, abstractmethod
from typing import Any


class IGitHubPort(ABC):
    """Interface for GitHub operations."""

    @abstractmethod
    def list_user_repos(self, user_id: int) -> Any:
        """List all repositories accessible to the given user's stored GitHub token."""

    @abstractmethod
    def add_deploy_key(self, repo_name: str, dokku_key: str, user_id: int) -> dict:
        """Add a Dokku deploy key to a GitHub repository, using the given user's token."""

    @abstractmethod
    def create_webhook(
        self,
        repo_name: str,
        app_id: int,
        user_id: int,
        *,
        force_update: bool = False,
    ) -> dict:
        """Create or repair the auto-deploy webhook for a GitHub repository."""

    @abstractmethod
    def set_deploy_pending(self, git_token: str, git_url: str, sha: str, app_name: str = '') -> bool:
        """Mark a commit's deploy status as PENDING."""

    @abstractmethod
    def set_deploy_success(self, git_token: str, git_url: str, sha: str, app_name: str = '') -> bool:
        """Mark a commit's deploy status as SUCCESS."""

    @abstractmethod
    def set_deploy_failure(
        self, git_token: str, git_url: str, sha: str, app_name: str = '', error: str = ''
    ) -> bool:
        """Mark a commit's deploy status as FAILURE."""

    @abstractmethod
    def get_branch_head_sha(self, repo_name: str, branch: str, user_id: int) -> str | None:
        """Get the HEAD commit SHA of a branch, using the given user's stored GitHub token.

        Returns None if the repo/branch can't be resolved for any reason (network error,
        missing token, branch not found, etc) — commit status is best-effort, never fatal.
        """
