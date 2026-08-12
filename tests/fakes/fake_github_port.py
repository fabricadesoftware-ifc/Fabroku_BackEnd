"""Fake GitHub adapter for testing."""
from dataclasses import dataclass

from applications.ports.i_github import IGitHubPort


@dataclass(frozen=True)
class FakeRepo:
    """Stand-in for a PyGithub `Repository`, exposing the attributes real code reads."""

    full_name: str
    private: bool = False


class FakeGitHubPort(IGitHubPort):
    """In-memory implementation of IGitHubPort for testing."""

    def __init__(self):
        """Initialize fake GitHub port."""
        self.repos: dict[int, list[FakeRepo]] = {}
        self.org_permission_denied_users: set[int] = set()
        self.deploy_keys: dict[str, list[dict]] = {}
        self.webhooks: dict[str, dict] = {}
        self.commit_statuses: dict[str, str] = {}
        self.head_shas: dict[tuple[str, str], str] = {}
        self.call_log: list[dict] = []
        self._next_key_id = 1

    def list_user_repos(self, user_id: int):
        """List all repositories accessible to a user (or an OrgPermissionDenied-shaped error dict)."""
        self._log_call('list_user_repos', {'user_id': user_id})
        if user_id in self.org_permission_denied_users:
            return {
                'status': 'org_permission_denied',
                'error': 'Permissao insuficiente para acessar organizacao.',
                'error_type': 'OrgPermissionDenied',
                'help_url': 'https://github.com/settings/tokens',
            }
        return list(self.repos.get(user_id, []))

    def add_deploy_key(self, repo_name: str, dokku_key: str, user_id: int) -> dict:
        """Add a deploy key to a GitHub repository."""
        self._log_call('add_deploy_key', {'repo_name': repo_name, 'user_id': user_id})
        key_id = self._next_key_id
        self._next_key_id += 1
        deploy_key = {'id': key_id, 'key': dokku_key, 'read_only': True}
        self.deploy_keys.setdefault(repo_name, []).append(deploy_key)
        return deploy_key

    def create_webhook(
        self,
        repo_name: str,
        app_id: int,
        user_id: int,
        *,
        force_update: bool = False,
    ) -> dict:
        """Create or repair the auto-deploy webhook for a repository."""
        self._log_call(
            'create_webhook',
            {'repo_name': repo_name, 'app_id': app_id, 'user_id': user_id, 'force_update': force_update},
        )
        webhook = {'status': 'webhook criado', 'repo_name': repo_name, 'app_id': app_id, 'active': True}
        self.webhooks[repo_name] = webhook
        return webhook

    def set_deploy_pending(self, git_token: str, git_url: str, sha: str, app_name: str = '') -> bool:
        """Mark a commit's deploy status as PENDING."""
        self._log_call('set_deploy_pending', {'git_url': git_url, 'sha': sha, 'app_name': app_name})
        self.commit_statuses[f'{git_url}@{sha}'] = 'pending'
        return True

    def set_deploy_success(self, git_token: str, git_url: str, sha: str, app_name: str = '') -> bool:
        """Mark a commit's deploy status as SUCCESS."""
        self._log_call('set_deploy_success', {'git_url': git_url, 'sha': sha, 'app_name': app_name})
        self.commit_statuses[f'{git_url}@{sha}'] = 'success'
        return True

    def set_deploy_failure(
        self, git_token: str, git_url: str, sha: str, app_name: str = '', error: str = ''
    ) -> bool:
        """Mark a commit's deploy status as FAILURE."""
        self._log_call(
            'set_deploy_failure', {'git_url': git_url, 'sha': sha, 'app_name': app_name, 'error': error}
        )
        self.commit_statuses[f'{git_url}@{sha}'] = 'failure'
        return True

    def get_branch_head_sha(self, repo_name: str, branch: str, user_id: int) -> str | None:
        """Get the HEAD commit SHA of a branch."""
        self._log_call('get_branch_head_sha', {'repo_name': repo_name, 'branch': branch, 'user_id': user_id})
        return self.head_shas.get((repo_name, branch))

    def _log_call(self, method_name: str, args: dict) -> None:
        """Log method calls for testing and debugging."""
        self.call_log.append({'method': method_name, 'args': args})

    def get_calls(self) -> list[dict]:
        """Get list of all logged calls."""
        return self.call_log.copy()

    def clear_logs(self) -> None:
        """Clear the call log."""
        self.call_log.clear()

    def add_fake_repo(self, user_id: int, owner: str, name: str, is_private: bool = False) -> FakeRepo:
        """Add a fake repository for testing."""
        repo = FakeRepo(full_name=f'{owner}/{name}', private=is_private)
        self.repos.setdefault(user_id, []).append(repo)
        return repo

    def set_head_sha(self, repo_name: str, branch: str, sha: str) -> None:
        """Configure the HEAD SHA returned by get_branch_head_sha for a repo/branch."""
        self.head_shas[(repo_name, branch)] = sha
