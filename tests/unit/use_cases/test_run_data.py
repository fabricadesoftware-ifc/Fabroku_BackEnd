"""Unit tests for RunDataUseCase, using fake ports (no SSH)."""
import pytest

from applications.domain.exceptions import DeploymentFailed
from applications.models import AppRunArtifact
from applications.use_cases.run_data import (
    DataCommandRun,
    DumpdataRun,
    RunDataUseCase,
    RunDumpdataCommand,
    RunLoaddataCommand,
    RunMigrateCommand,
)
from observability.models import AppLogManager
from tests.factories.models import AppFactory, ProjectFactory, UserFactory
from tests.fakes import FakeDokkuPort

pytestmark = pytest.mark.django_db


def make_use_case(app, dokku=None):
    dokku = dokku or FakeDokkuPort()
    log_manager = AppLogManager(app, task_id='test-task-id')
    return RunDataUseCase(dokku_port=dokku, log_manager=log_manager), dokku


def test_run_migrate_success():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    result = use_case.execute_migrate(RunMigrateCommand(app_id=app.id, manage_path='manage.py', noinput=True))

    assert isinstance(result, DataCommandRun)
    assert 'migrate' in result.command
    app.refresh_from_db()
    assert app.error_type is None


def test_run_migrate_without_name_dokku_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku=None)
    use_case, _dokku = make_use_case(app)

    with pytest.raises(DeploymentFailed):
        use_case.execute_migrate(RunMigrateCommand(app_id=app.id, manage_path='manage.py'))


def test_run_migrate_failure_records_error():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')
    dokku.run_in_app = lambda app_name, command: 'Traceback (most recent call last):\nBoom'

    with pytest.raises(RuntimeError):
        use_case.execute_migrate(RunMigrateCommand(app_id=app.id, manage_path='manage.py'))

    app.refresh_from_db()
    assert app.error_type == 'MigrateExecutionError'


def test_run_loaddata_success():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    result = use_case.execute_loaddata(
        RunLoaddataCommand(app_id=app.id, fixture_path='fixtures/data.json', manage_path='manage.py')
    )

    assert isinstance(result, DataCommandRun)
    assert 'loaddata' in result.command


def test_run_dumpdata_success_creates_artifact():
    project = ProjectFactory()
    user = UserFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')
    dokku.run_in_app = lambda app_name, command: '[{"model": "app.foo", "pk": 1}]'

    result = use_case.execute_dumpdata(
        RunDumpdataCommand(
            app_id=app.id,
            manage_path='manage.py',
            dump_args=['app'],
            output_filename='dump.json',
            user_id=user.id,
        )
    )

    assert isinstance(result, DumpdataRun)
    assert result.filename == 'dump.json'
    assert AppRunArtifact.objects.filter(id=result.artifact_id).exists()


def test_run_dumpdata_failure_does_not_create_artifact():
    project = ProjectFactory()
    user = UserFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')
    dokku.run_in_app = lambda app_name, command: 'Traceback (most recent call last):\nBoom'

    with pytest.raises(RuntimeError):
        use_case.execute_dumpdata(
            RunDumpdataCommand(
                app_id=app.id,
                manage_path='manage.py',
                dump_args=[],
                output_filename='dump.json',
                user_id=user.id,
            )
        )

    app.refresh_from_db()
    assert app.error_type == 'DumpdataExecutionError'
    assert not AppRunArtifact.objects.filter(app=app).exists()
