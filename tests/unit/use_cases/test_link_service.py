"""Unit tests for LinkServiceUseCase, using fake ports (no SSH)."""
import pytest

from applications.domain.exceptions import ApplicationDomainError
from service_mgmt.use_cases.link_service import LinkServiceCommand, LinkServiceUseCase, ServiceLinked
from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory
from tests.fakes import FakeDokkuPort

pytestmark = pytest.mark.django_db


def make_use_case(dokku=None):
    dokku = dokku or FakeDokkuPort()
    return LinkServiceUseCase(dokku_port=dokku), dokku


def test_link_standalone_service_to_app():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')
    dokku.create_database('standalone-db', 'secret')
    service = ServiceFactory(
        app=None, project=project, service_type='postgres', container_name='standalone-db', env_key=None
    )

    result = use_case.execute(LinkServiceCommand(service_id=service.id, app_id=app.id))

    assert isinstance(result, ServiceLinked)
    assert result.env_key == 'DATABASE_URL'
    service.refresh_from_db()
    assert service.app_id == app.id
    assert 'my-app' in dokku.databases['standalone-db']['linked_apps']
    assert 'restart_app' in [call['method'] for call in dokku.get_calls()]


def test_link_service_different_project_raises():
    project_a = ProjectFactory()
    project_b = ProjectFactory()
    app = AppFactory(project=project_a, name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')
    service = ServiceFactory(app=None, project=project_b, service_type='postgres', container_name='some-db')

    with pytest.raises(ApplicationDomainError):
        use_case.execute(LinkServiceCommand(service_id=service.id, app_id=app.id))


def test_link_service_already_linked_to_another_app_raises():
    project = ProjectFactory()
    other_app = AppFactory(project=project, name_dokku='other-app')
    target_app = AppFactory(project=project, name_dokku='target-app')
    use_case, dokku = make_use_case()
    dokku.create_app('other-app')
    dokku.create_app('target-app')
    service = ServiceFactory(app=other_app, project=project, service_type='postgres', container_name='some-db')

    with pytest.raises(ApplicationDomainError):
        use_case.execute(LinkServiceCommand(service_id=service.id, app_id=target_app.id))


def test_link_service_without_container_name_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')
    service = ServiceFactory(app=None, project=project, service_type='postgres', container_name=None)

    with pytest.raises(ApplicationDomainError):
        use_case.execute(LinkServiceCommand(service_id=service.id, app_id=app.id))


def test_link_service_allocates_distinct_env_key_on_collision():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')
    dokku.create_database('primary-db', 'secret')
    dokku.link_database('primary-db', 'my-app')
    ServiceFactory(
        app=app, project=project, service_type='postgres', container_name='primary-db', env_key='DATABASE_URL'
    )
    dokku.create_database('second-db', 'secret')
    second_service = ServiceFactory(
        app=None, project=project, service_type='postgres', container_name='second-db', env_key=None
    )

    result = use_case.execute(LinkServiceCommand(service_id=second_service.id, app_id=app.id))

    assert result.env_key != 'DATABASE_URL'
