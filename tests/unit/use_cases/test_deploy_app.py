"""Unit tests for DeployAppUseCase, using fake ports (no SSH/GitHub/Celery)."""
import pytest

from applications.domain.exceptions import DeploymentFailed
from applications.github_integration import GitSyncPlan
from applications.models import AppStatus
from applications.use_cases.deploy_app import AppDeployed, DeployAppCommand, DeployAppUseCase
from observability.models import AppLogManager
from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory
from tests.fakes import FakeDokkuPort, FakeGitHubPort

pytestmark = pytest.mark.django_db


def noop_reconcile_webhook(app, *, preferred_user=None, github_adapter=None, app_logger=None, progress=0):
    """Stand-in for reconcile_github_webhook that skips real DB/GitHub-API webhook resolution."""
    return {'ok': False, 'status': 'skipped for test', 'attempts': []}


def ok_sync_plan(git_url='https://github.com/owner/repo.git', token=None):
    def _resolve(app, preferred_user=None):
        return GitSyncPlan(ok=True, git_url=git_url, strategy='raw', message='test plan', token=token)

    return _resolve


def failing_sync_plan(message='no access'):
    def _resolve(app, preferred_user=None):
        return GitSyncPlan(ok=False, git_url=None, strategy='github_token_required', message=message)

    return _resolve


def make_use_case(app, *, dokku=None, github=None, reconcile_webhook=noop_reconcile_webhook, resolve_sync_plan=None):
    dokku = dokku or FakeDokkuPort()
    github = github or FakeGitHubPort()
    resolve_sync_plan = resolve_sync_plan or ok_sync_plan()
    log_manager = AppLogManager(app, task_id='test-task-id')
    use_case = DeployAppUseCase(
        dokku_port=dokku,
        github_port=github,
        log_manager=log_manager,
        reconcile_webhook=reconcile_webhook,
        resolve_sync_plan=resolve_sync_plan,
    )
    return use_case, dokku, github


def test_deploy_app_success():
    project = ProjectFactory()
    app = AppFactory(project=project, name='my-app', name_dokku='my-app', git='https://github.com/owner/repo.git')
    use_case, dokku, _github = make_use_case(app)
    dokku.create_app('my-app')

    result = use_case.execute(DeployAppCommand(app_id=app.id, task_id='task-1', commit_sha='abc123'))

    assert isinstance(result, AppDeployed)
    assert result.dokku_app_name == 'my-app'
    app.refresh_from_db()
    assert app.status == AppStatus.RUNNING
    assert app.last_commit_sha == 'abc123'
    assert app.task_id == 'task-1'


def test_deploy_app_missing_name_dokku_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku=None)
    use_case, _dokku, _github = make_use_case(app)

    with pytest.raises(DeploymentFailed):
        use_case.execute(DeployAppCommand(app_id=app.id))

    app.refresh_from_db()
    assert app.status == AppStatus.ERROR


def test_deploy_app_not_in_dokku_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='ghost-app')
    use_case, _dokku, _github = make_use_case(app)  # fake dokku has no 'ghost-app' registered

    with pytest.raises(DeploymentFailed):
        use_case.execute(DeployAppCommand(app_id=app.id))

    app.refresh_from_db()
    assert app.status == AppStatus.ERROR


def test_deploy_app_sync_plan_not_ok_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku, _github = make_use_case(app, resolve_sync_plan=failing_sync_plan('need token'))
    dokku.create_app('my-app')

    with pytest.raises(DeploymentFailed):
        use_case.execute(DeployAppCommand(app_id=app.id))

    app.refresh_from_db()
    assert app.status == AppStatus.ERROR


def test_deploy_app_git_sync_failure_sets_error_and_github_status():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app', git='https://github.com/owner/repo.git')
    use_case, dokku, github = make_use_case(app, resolve_sync_plan=ok_sync_plan(token='tok123'))
    dokku.create_app('my-app')

    original_sync = dokku.sync_git_streaming

    def failing_sync(*args, **kwargs):
        original_sync(*args, **kwargs)
        return 'Failed to sync Git repository and deploy.'

    dokku.sync_git_streaming = failing_sync

    with pytest.raises(DeploymentFailed):
        use_case.execute(DeployAppCommand(app_id=app.id, commit_sha='deadbeef'))

    app.refresh_from_db()
    assert app.status == AppStatus.ERROR
    assert github.commit_statuses[f'{app.git}@deadbeef'] == 'failure'


def test_deploy_app_starts_linked_postgres_services():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app', git='https://github.com/owner/repo.git')
    ServiceFactory(app=app, project=project, container_name='my-app-postgres')
    use_case, dokku, _github = make_use_case(app)
    dokku.create_app('my-app')

    use_case.execute(DeployAppCommand(app_id=app.id))

    assert 'start_database' in [call['method'] for call in dokku.get_calls()]
