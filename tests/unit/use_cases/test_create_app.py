"""Unit tests for CreateAppUseCase, using fake ports (no SSH/GitHub/Celery)."""
import pytest

from applications.models import AppStatus
from applications.use_cases.create_app import AppCreated, CreateAppCommand, CreateAppUseCase
from observability.models import AppLogManager
from tests.factories.models import AppFactory, ProjectFactory, UserFactory
from tests.fakes import FakeDokkuPort, FakeGitHubPort

pytestmark = pytest.mark.django_db


def noop_reconcile_webhook(app, *, preferred_user=None, github_adapter=None, app_logger=None, progress=0):
    """Stand-in for reconcile_github_webhook that skips real DB/GitHub-API webhook resolution."""
    return {'ok': False, 'status': 'skipped for test', 'attempts': []}


def make_use_case(app, *, dokku=None, github=None, reconcile_webhook=noop_reconcile_webhook):
    dokku = dokku or FakeDokkuPort()
    github = github or FakeGitHubPort()
    log_manager = AppLogManager(app, task_id='test-task-id')
    use_case = CreateAppUseCase(
        dokku_port=dokku, github_port=github, log_manager=log_manager, reconcile_webhook=reconcile_webhook
    )
    return use_case, dokku, github


def test_create_app_success_public_repo():
    user = UserFactory()
    project = ProjectFactory(users=[user])
    app = AppFactory(project=project, name='my-app', git='https://github.com/owner/repo.git', branch='main')
    use_case, dokku, github = make_use_case(app)

    result = use_case.execute(CreateAppCommand(app_id=app.id, user_id=user.id, task_id='task-1'))

    assert isinstance(result, AppCreated)
    assert result.status == 'created'
    assert dokku.exists_app(result.dokku_app_name)

    app.refresh_from_db()
    assert app.status == AppStatus.RUNNING
    assert app.task_id == 'task-1'
    assert app.name_dokku == result.dokku_app_name


def test_create_app_private_repo_uses_authenticated_url():
    user = UserFactory(git_token='gh-token-123')
    project = ProjectFactory(users=[user])
    app = AppFactory(project=project, name='private-app', git='https://github.com/owner/repo.git', branch='main')
    use_case, dokku, github = make_use_case(app)
    github.add_fake_repo(user.id, 'owner', 'repo', is_private=True)

    result = use_case.execute(CreateAppCommand(app_id=app.id, user_id=user.id))

    assert result.status == 'created'
    assert dokku.apps[result.dokku_app_name]['git_url'] == 'https://x-access-token:gh-token-123@github.com/owner/repo.git'


def test_create_app_applies_env_vars():
    user = UserFactory()
    project = ProjectFactory(users=[user])
    app = AppFactory(project=project, name='env-app', git='https://github.com/owner/repo.git')
    use_case, dokku, github = make_use_case(app)

    result = use_case.execute(
        CreateAppCommand(app_id=app.id, user_id=user.id, env_vars={'DATABASE_URL': 'postgres://x'})
    )

    assert dokku.apps[result.dokku_app_name]['env_vars'] == {'DATABASE_URL': 'postgres://x'}


def test_create_app_already_exists_in_dokku_is_idempotent():
    user = UserFactory()
    project = ProjectFactory(users=[user])
    app = AppFactory(
        project=project, name='existing-app', git='https://github.com/owner/repo.git', status=AppStatus.STARTING
    )
    use_case, dokku, github = make_use_case(app)
    dokku.create_app('existing-app')

    result = use_case.execute(CreateAppCommand(app_id=app.id, user_id=user.id))

    assert result.status == 'already_exists'
    app.refresh_from_db()
    assert app.status == AppStatus.STARTING  # provisioning steps beyond ensure_app never ran, status untouched
    assert app.domain is None


def test_create_app_git_sync_failure_marks_app_error():
    user = UserFactory()
    project = ProjectFactory(users=[user])
    app = AppFactory(project=project, name='broken-app', git='https://github.com/owner/repo.git')
    use_case, dokku, github = make_use_case(app)

    original_sync = dokku.sync_git_streaming

    def failing_sync(*args, **kwargs):
        original_sync(*args, **kwargs)
        return 'Failed to sync Git repository and deploy.'

    dokku.sync_git_streaming = failing_sync

    with pytest.raises(RuntimeError):
        use_case.execute(CreateAppCommand(app_id=app.id, user_id=user.id))

    app.refresh_from_db()
    assert app.status == AppStatus.ERROR
    assert app.error_details
