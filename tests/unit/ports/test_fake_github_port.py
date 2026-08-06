"""Tests for FakeGitHubPort implementation."""
from applications.ports.i_github import IGitHubPort
from tests.fakes import FakeGitHubPort


class TestFakeGitHubPortImplementsInterface:
    """Verify FakeGitHubPort properly implements IGitHubPort."""

    def test_fake_github_is_instance_of_interface(self):
        """FakeGitHubPort should be an instance of IGitHubPort."""
        fake = FakeGitHubPort()
        assert isinstance(fake, IGitHubPort)

    def test_list_user_repos_empty(self):
        """Test listing repos for user with no repos."""
        fake = FakeGitHubPort()

        repos = fake.list_user_repos(1)
        assert repos == []

    def test_add_and_list_repos(self):
        """Test adding repos and listing them."""
        fake = FakeGitHubPort()

        fake.add_fake_repo(1, 'owner', 'repo1')
        fake.add_fake_repo(1, 'owner', 'repo2')

        repos = fake.list_user_repos(1)
        assert len(repos) == 2
        assert repos[0].full_name == 'owner/repo1'
        assert repos[1].full_name == 'owner/repo2'

    def test_repo_info_attributes(self):
        """Test fake repo exposes the attributes real code reads (full_name, private)."""
        fake = FakeGitHubPort()

        repo = fake.add_fake_repo(1, 'owner', 'repo', is_private=True)

        assert repo.full_name == 'owner/repo'
        assert repo.private is True

    def test_list_user_repos_org_permission_denied(self):
        """Test simulating an OrgPermissionDenied response."""
        fake = FakeGitHubPort()
        fake.org_permission_denied_users.add(1)

        result = fake.list_user_repos(1)

        assert result['error_type'] == 'OrgPermissionDenied'

    def test_get_branch_head_sha(self):
        """Test configuring and reading a branch's HEAD sha."""
        fake = FakeGitHubPort()

        assert fake.get_branch_head_sha('owner/repo', 'main', user_id=1) is None

        fake.set_head_sha('owner/repo', 'main', 'abc123')
        assert fake.get_branch_head_sha('owner/repo', 'main', user_id=1) == 'abc123'

    def test_add_deploy_key(self):
        """Test adding a deploy key to a repository."""
        fake = FakeGitHubPort()

        key = fake.add_deploy_key(repo_name='owner/repo', dokku_key='ssh-rsa AAAAB3...', user_id=1)

        assert key['id'] > 0
        assert key['key'] == 'ssh-rsa AAAAB3...'
        assert key in fake.deploy_keys['owner/repo']

    def test_create_webhook(self):
        """Test creating a deploy webhook for a repository."""
        fake = FakeGitHubPort()

        webhook = fake.create_webhook('owner/repo', app_id=42, user_id=1)

        assert webhook['app_id'] == 42
        assert fake.webhooks['owner/repo']['active'] is True

    def test_commit_status_pending(self):
        """Test setting commit status to pending."""
        fake = FakeGitHubPort()

        fake.set_deploy_pending('token', 'https://github.com/owner/repo', 'abc123def456')

        assert fake.commit_statuses['https://github.com/owner/repo@abc123def456'] == 'pending'

    def test_commit_status_success(self):
        """Test setting commit status to success."""
        fake = FakeGitHubPort()

        fake.set_deploy_success('token', 'https://github.com/owner/repo', 'abc123def456')

        assert fake.commit_statuses['https://github.com/owner/repo@abc123def456'] == 'success'

    def test_commit_status_failure(self):
        """Test setting commit status to failure."""
        fake = FakeGitHubPort()

        fake.set_deploy_failure('token', 'https://github.com/owner/repo', 'abc123def456', error='Build failed')

        assert fake.commit_statuses['https://github.com/owner/repo@abc123def456'] == 'failure'

    def test_call_logging(self):
        """Test that method calls are logged."""
        fake = FakeGitHubPort()

        fake.add_fake_repo(1, 'owner', 'repo')
        fake.list_user_repos(1)

        calls = fake.get_calls()
        assert len(calls) >= 1
        assert 'list_user_repos' in [call['method'] for call in calls]

        fake.clear_logs()
        assert len(fake.get_calls()) == 0

    def test_multiple_users_separate_repos(self):
        """Test that repos for different users are separate."""
        fake = FakeGitHubPort()

        fake.add_fake_repo(1, 'owner1', 'repo1')
        fake.add_fake_repo(2, 'owner2', 'repo2')

        repos_user1 = fake.list_user_repos(1)
        repos_user2 = fake.list_user_repos(2)

        assert len(repos_user1) == 1
        assert len(repos_user2) == 1
        assert repos_user1[0].full_name == 'owner1/repo1'
        assert repos_user2[0].full_name == 'owner2/repo2'
