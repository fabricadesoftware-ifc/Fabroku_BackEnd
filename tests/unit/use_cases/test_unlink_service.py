"""Unit tests for UnlinkServiceUseCase, using fake ports (no SSH)."""
import pytest

from applications.domain.exceptions import ApplicationDomainError
from service_mgmt.use_cases.unlink_service import ServiceUnlinked, UnlinkServiceCommand, UnlinkServiceUseCase
from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory
from tests.fakes import FakeDokkuPort

pytestmark = pytest.mark.django_db


def make_use_case(dokku=None):
    dokku = dokku or FakeDokkuPort()
    return UnlinkServiceUseCase(dokku_port=dokku), dokku


def test_unlink_service_detaches_from_app():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')
    dokku.create_database('my-app-db-1', 'secret')
    dokku.link_database('my-app-db-1', 'my-app')
    service = ServiceFactory(
        app=app, project=project, service_type='postgres', container_name='my-app-db-1', env_key='DATABASE_URL'
    )

    result = use_case.execute(UnlinkServiceCommand(service_id=service.id))

    assert isinstance(result, ServiceUnlinked)
    service.refresh_from_db()
    assert service.app_id is None
    assert service.env_key is None
    assert 'my-app' not in dokku.databases['my-app-db-1']['linked_apps']


def test_unlink_service_without_app_raises():
    project = ProjectFactory()
    use_case, _dokku = make_use_case()
    service = ServiceFactory(app=None, project=project, service_type='postgres', container_name='standalone-db')

    with pytest.raises(ApplicationDomainError):
        use_case.execute(UnlinkServiceCommand(service_id=service.id))


def test_unlink_service_removes_mirrored_env_var():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')
    dokku.create_database('my-app-db-1', 'secret')
    dokku.link_database('my-app-db-1', 'my-app')
    app.variables = {'DATABASE_URL': 'postgres://fake/my-app-db-1'}
    app.save(update_fields=['variables'])
    service = ServiceFactory(
        app=app, project=project, service_type='postgres', container_name='my-app-db-1', env_key='DATABASE_URL'
    )

    use_case.execute(UnlinkServiceCommand(service_id=service.id))

    app.refresh_from_db()
    assert 'DATABASE_URL' not in app.variables


def test_unlink_service_without_container_name_is_local_only():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')
    service = ServiceFactory(app=app, project=project, service_type='postgres', container_name=None)

    result = use_case.execute(UnlinkServiceCommand(service_id=service.id))

    assert isinstance(result, ServiceUnlinked)
    assert 'unlink_database' not in [call['method'] for call in dokku.get_calls()]
    service.refresh_from_db()
    assert service.app_id is None


def test_unlink_service_promotes_remaining_database():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')
    dokku.create_database('primary-db', 'secret')
    dokku.link_database('primary-db', 'my-app')
    primary = ServiceFactory(
        app=app, project=project, service_type='postgres', container_name='primary-db', env_key='DATABASE_URL'
    )
    dokku.create_database('secondary-db', 'secret')
    dokku.link_database('secondary-db', 'my-app', alias='SECONDARY')
    ServiceFactory(
        app=app, project=project, service_type='postgres', container_name='secondary-db', env_key='SECONDARY_URL'
    )

    use_case.execute(UnlinkServiceCommand(service_id=primary.id))

    assert 'promote_database' in [call['method'] for call in dokku.get_calls()]
