"""Unit tests for RunCommandUseCase, using fake ports (no SSH)."""
import pytest

from applications.domain.exceptions import DeploymentFailed
from applications.use_cases.run_command import CommandNotAllowed, CommandRun, RunCommandCommand, RunCommandUseCase
from observability.models import AppLogManager
from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory
from tests.fakes import FakeDokkuPort

pytestmark = pytest.mark.django_db


def make_use_case(app, dokku=None):
    dokku = dokku or FakeDokkuPort()
    log_manager = AppLogManager(app, task_id='test-task-id')
    return RunCommandUseCase(dokku_port=dokku, log_manager=log_manager), dokku


def test_run_command_success():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    result = use_case.execute(RunCommandCommand(app_id=app.id, command='python manage.py migrate'))

    assert isinstance(result, CommandRun)
    assert result.command == 'python manage.py migrate'
    app.refresh_from_db()
    assert app.error_type is None
    assert app.error_details is None


def test_run_command_not_allowed_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    with pytest.raises(CommandNotAllowed):
        use_case.execute(RunCommandCommand(app_id=app.id, command='rm -rf /'))


def test_run_command_without_name_dokku_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku=None)
    use_case, _dokku = make_use_case(app)

    with pytest.raises(DeploymentFailed):
        use_case.execute(RunCommandCommand(app_id=app.id, command='python manage.py migrate'))


def test_run_command_output_with_error_marker_raises_and_records_error():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    def failing_stream(app_name, command):
        yield 'Traceback (most recent call last):'
        yield 'CommandError: something broke'
        return 1

    dokku.run_in_app_streaming = failing_stream

    with pytest.raises(RuntimeError):
        use_case.execute(RunCommandCommand(app_id=app.id, command='python manage.py migrate'))

    app.refresh_from_db()
    assert app.error_type == 'CommandExecutionError'
    assert app.error_details


def test_run_command_warms_up_linked_postgres_before_running():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')
    ServiceFactory(app=app, project=project, container_name='my-app-db', service_type='postgres')

    use_case.execute(RunCommandCommand(app_id=app.id, command='python manage.py migrate'))

    assert 'start_database' in [call['method'] for call in dokku.get_calls()]
