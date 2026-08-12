"""Unit tests for DeleteServiceUseCase, using fake ports (no SSH)."""
import pytest

from service_mgmt.use_cases.delete_service import DeleteServiceCommand, DeleteServiceUseCase, ServiceDeleted
from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory
from tests.fakes import FakeDokkuPort

pytestmark = pytest.mark.django_db


def make_use_case(dokku=None):
    dokku = dokku or FakeDokkuPort()
    return DeleteServiceUseCase(dokku_port=dokku), dokku


def test_delete_linked_service_unlinks_and_removes_remote():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')
    dokku.create_database('my-app-db-1', 'secret')
    dokku.link_database('my-app-db-1', 'my-app')
    service = ServiceFactory(
        app=app, project=project, service_type='postgres', container_name='my-app-db-1', env_key='DATABASE_URL'
    )

    result = use_case.execute(DeleteServiceCommand(service_id=service.id))

    assert isinstance(result, ServiceDeleted)
    assert result.already_deleted is False
    service.refresh_from_db()
    assert service.deleted_at is not None
    assert 'my-app-db-1' not in dokku.databases


def test_delete_standalone_service_skips_unlink():
    project = ProjectFactory()
    use_case, dokku = make_use_case()
    dokku.create_database('standalone-db', 'secret')
    service = ServiceFactory(
        app=None, project=project, service_type='postgres', container_name='standalone-db', env_key=None
    )

    result = use_case.execute(DeleteServiceCommand(service_id=service.id))

    assert result.already_deleted is False
    assert 'unlink_database' not in [call['method'] for call in dokku.get_calls()]
    assert 'standalone-db' not in dokku.databases


def test_delete_already_deleted_service_is_idempotent():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, _dokku = make_use_case()
    service = ServiceFactory(app=app, project=project, service_type='postgres')
    service.soft_delete()

    result = use_case.execute(DeleteServiceCommand(service_id=service.id))

    assert result.already_deleted is True


def test_delete_nonexistent_service_is_idempotent():
    use_case, _dokku = make_use_case()

    result = use_case.execute(DeleteServiceCommand(service_id=999999))

    assert result.already_deleted is True


def test_delete_service_remote_failure_does_not_abort():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')
    dokku.create_database('my-app-db-1', 'secret')
    dokku.link_database('my-app-db-1', 'my-app')

    def failing_unlink(db_name, app_name):
        raise RuntimeError('ssh connection error')

    dokku.unlink_database = failing_unlink

    service = ServiceFactory(
        app=app, project=project, service_type='postgres', container_name='my-app-db-1', env_key='DATABASE_URL'
    )

    result = use_case.execute(DeleteServiceCommand(service_id=service.id))

    assert result.already_deleted is False
    service.refresh_from_db()
    assert service.deleted_at is not None
    assert 'my-app-db-1' not in dokku.databases
