"""Unit tests for ManageAppUseCase, using fake ports (no SSH)."""
import pytest

from applications.domain.exceptions import DeploymentFailed
from applications.models import AppStatus
from applications.use_cases.manage_app import AppManaged, ManageAppCommand, ManageAppUseCase
from observability.models import AppLogManager
from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory
from tests.fakes import FakeDokkuPort

pytestmark = pytest.mark.django_db


def make_use_case(app, dokku=None):
    dokku = dokku or FakeDokkuPort()
    log_manager = AppLogManager(app, task_id='test-task-id')
    return ManageAppUseCase(dokku_port=dokku, log_manager=log_manager), dokku


def test_manage_app_start():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app', status=AppStatus.STOPPED)
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    result = use_case.execute(ManageAppCommand(app_id=app.id, action='start'))

    assert isinstance(result, AppManaged)
    assert result.action == 'start'
    app.refresh_from_db()
    assert app.status == AppStatus.RUNNING
    assert dokku.get_app_status('my-app') == 'running'


def test_manage_app_stop():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app', status=AppStatus.RUNNING)
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    use_case.execute(ManageAppCommand(app_id=app.id, action='stop'))

    app.refresh_from_db()
    assert app.status == AppStatus.STOPPED


def test_manage_app_restart_warms_up_linked_postgres_service():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app', status=AppStatus.RUNNING)
    ServiceFactory(app=app, project=project, container_name='my-app-postgres')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    use_case.execute(ManageAppCommand(app_id=app.id, action='restart'))

    assert 'start_database' in [call['method'] for call in dokku.get_calls()]


def test_manage_app_without_name_dokku_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku=None)
    use_case, _dokku = make_use_case(app)

    with pytest.raises(DeploymentFailed):
        use_case.execute(ManageAppCommand(app_id=app.id, action='start'))


def test_manage_app_dokku_failure_marks_app_error():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app', status=AppStatus.RUNNING)
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    def failing_stop(*args, **kwargs):
        raise RuntimeError('ssh connection error')

    dokku.stop_app = failing_stop

    with pytest.raises(RuntimeError):
        use_case.execute(ManageAppCommand(app_id=app.id, action='stop'))

    app.refresh_from_db()
    assert app.status == AppStatus.ERROR
