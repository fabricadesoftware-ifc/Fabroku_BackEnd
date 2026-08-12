"""Unit tests for ScaleProcessesUseCase, using fake ports (no SSH)."""
import pytest

from applications.domain.exceptions import AppNotFound, DeploymentFailed
from applications.models import AppProcessScale
from applications.use_cases.scale_processes import ProcessesScaled, ScaleProcessesCommand, ScaleProcessesUseCase
from observability.models import AppLogManager
from tests.factories.models import AppFactory, ProjectFactory
from tests.fakes import FakeDokkuPort

pytestmark = pytest.mark.django_db


def make_use_case(app, dokku=None):
    dokku = dokku or FakeDokkuPort()
    log_manager = AppLogManager(app, task_id='test-task-id')
    return ScaleProcessesUseCase(dokku_port=dokku, log_manager=log_manager), dokku


def test_scale_processes_applies_scale_and_persists_desired_quantities():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    result = use_case.execute(
        ScaleProcessesCommand(app_id=app.id, processes={'web': 2}, task_id='test-task-id')
    )

    assert isinstance(result, ProcessesScaled)
    assert result.app_id == app.id
    assert result.dokku_app_name == 'my-app'
    assert result.processes == {'web': 2}
    assert 'ps_scale' in [call['method'] for call in dokku.get_calls()]

    process_scale = AppProcessScale.objects.get(app=app, process_name='web')
    assert process_scale.desired_quantity == 2
    assert process_scale.current_quantity == 2

    app.refresh_from_db()
    assert app.task_id == 'test-task-id'


def test_scale_processes_missing_app_raises_app_not_found():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, _dokku = make_use_case(app)
    missing_app_id = app.id + 1000

    with pytest.raises(AppNotFound):
        use_case.execute(ScaleProcessesCommand(app_id=missing_app_id, processes={'web': 2}))


def test_scale_processes_without_name_dokku_raises_deployment_failed():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku=None)
    use_case, _dokku = make_use_case(app)

    with pytest.raises(DeploymentFailed):
        use_case.execute(ScaleProcessesCommand(app_id=app.id, processes={'web': 2}))


def test_scale_processes_invalid_quantity_raises_value_error():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    with pytest.raises(ValueError):
        use_case.execute(ScaleProcessesCommand(app_id=app.id, processes={'web': 999}))


def test_scale_processes_dokku_failure_raises_deployment_failed():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    def failing_ps_scale(*args, **kwargs):
        return 'ssh connection error: could not scale'

    dokku.ps_scale = failing_ps_scale

    with pytest.raises(DeploymentFailed):
        use_case.execute(ScaleProcessesCommand(app_id=app.id, processes={'web': 2}))
