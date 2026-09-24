"""Unit tests for CreateServiceUseCase, using fake ports (no SSH)."""
import pytest

from applications.domain.exceptions import DeploymentFailed
from service_mgmt.use_cases.create_service import (
    CreateServiceCommand,
    CreateServiceStandaloneCommand,
    CreateServiceUseCase,
    ServiceCreated,
)
from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory
from tests.fakes import FakeDokkuPort

pytestmark = pytest.mark.django_db


def make_use_case(dokku=None):
    dokku = dokku or FakeDokkuPort()
    return CreateServiceUseCase(dokku_port=dokku), dokku


def test_create_attached_postgres_service():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')

    result = use_case.execute_attached(CreateServiceCommand(app_id=app.id, service_type='postgres'))

    assert isinstance(result, ServiceCreated)
    assert result.service_type == 'postgres'
    assert result.service_name in dokku.databases
    assert app.name_dokku in dokku.databases[result.service_name]['linked_apps']
    assert 'restart_app' in [call['method'] for call in dokku.get_calls()]


def test_create_attached_redis_service():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')

    result = use_case.execute_attached(CreateServiceCommand(app_id=app.id, service_type='redis'))

    assert result.service_type == 'redis'
    assert result.service_name in dokku.redis_instances


def test_create_attached_without_name_dokku_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku=None)
    use_case, _dokku = make_use_case()

    with pytest.raises(DeploymentFailed):
        use_case.execute_attached(CreateServiceCommand(app_id=app.id, service_type='postgres'))


def test_create_attached_reuses_existing_placeholder_service():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    service = ServiceFactory(app=app, project=project, service_type='postgres', name='existing-db')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')

    result = use_case.execute_attached(
        CreateServiceCommand(app_id=app.id, service_type='postgres', service_id=service.id)
    )

    assert result.service_id == service.id


def test_create_standalone_service_has_no_app():
    project = ProjectFactory()
    use_case, dokku = make_use_case()

    result = use_case.execute_standalone(
        CreateServiceStandaloneCommand(project_id=project.id, service_type='postgres', name='standalone-db')
    )

    assert isinstance(result, ServiceCreated)
    assert result.service_name in dokku.databases
    assert dokku.databases[result.service_name]['linked_apps'] == {}


def test_create_standalone_refuses_to_adopt_unrelated_dokku_service():
    """A fresh, unrelated Service row must not be able to claim a container that already
    exists in Dokku (e.g. someone else's database with a guessable/chosen name)."""
    project = ProjectFactory()
    use_case, dokku = make_use_case()
    dokku.create_database = lambda **kwargs: 'Postgres container victim-db already exists'

    with pytest.raises(DeploymentFailed):
        use_case.execute_standalone(
            CreateServiceStandaloneCommand(project_id=project.id, service_type='postgres', name='victim-db')
        )


def test_create_standalone_retry_of_own_service_is_idempotent():
    """A retry (this Service row already owns `container_name` from a prior run) is not a hijack."""
    project = ProjectFactory()
    service = ServiceFactory(
        app=None, project=project, service_type='postgres', name='my-db', container_name='my-db'
    )
    use_case, dokku = make_use_case()
    dokku.create_database = lambda **kwargs: 'Postgres container my-db already exists'

    result = use_case.execute_standalone(
        CreateServiceStandaloneCommand(
            project_id=project.id, service_type='postgres', name='my-db', service_id=service.id
        )
    )

    assert result.service_id == service.id


def test_create_attached_refuses_to_adopt_unrelated_dokku_service():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')
    dokku.create_database = lambda **kwargs: 'Postgres container victim-db already exists'

    with pytest.raises(DeploymentFailed):
        use_case.execute_attached(CreateServiceCommand(app_id=app.id, service_type='postgres'))
