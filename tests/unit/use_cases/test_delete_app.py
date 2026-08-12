"""Unit tests for DeleteAppUseCase, using fake ports (no SSH)."""
import pytest
from django.utils import timezone

from applications.use_cases.delete_app import AppDeleted, DeleteAppCommand, DeleteAppUseCase
from observability.models import AppLogManager
from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory
from tests.fakes import FakeDokkuPort

pytestmark = pytest.mark.django_db


def make_use_case(app, dokku=None):
    dokku = dokku or FakeDokkuPort()
    log_manager = AppLogManager(app, task_id='test-task-id')
    return DeleteAppUseCase(dokku_port=dokku, log_manager=log_manager), dokku


def test_delete_app_success():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    result = use_case.execute(DeleteAppCommand(app_id=app.id, deleted_by_id=None))

    assert isinstance(result, AppDeleted)
    assert result.already_deleted is False
    assert 'my-app' not in dokku.apps
    app.refresh_from_db()
    assert app.deleted_at is not None


def test_delete_app_removes_linked_postgres_service():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    service = ServiceFactory(app=app, project=project, container_name='my-app-db', service_type='postgres')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')
    dokku.create_database('my-app-db', 'secret')
    dokku.link_database('my-app-db', 'my-app')

    use_case.execute(DeleteAppCommand(app_id=app.id))

    assert 'my-app-db' not in dokku.databases
    service.refresh_from_db()
    assert service.deleted_at is not None


def test_delete_app_already_soft_deleted_is_idempotent():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app', deleted_at=timezone.now())
    use_case, dokku = make_use_case(app)

    result = use_case.execute(DeleteAppCommand(app_id=app.id))

    assert result.already_deleted is True
    assert dokku.get_calls() == []


def test_delete_app_not_found_is_idempotent():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    missing_id = app.id + 1000

    result = use_case.execute(DeleteAppCommand(app_id=missing_id))

    assert result.already_deleted is True
    assert result.app_id == missing_id


def test_delete_app_dokku_failure_does_not_abort_deletion():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    use_case, dokku = make_use_case(app)
    dokku.create_app('my-app')

    def failing_delete(*args, **kwargs):
        raise RuntimeError('ssh connection error')

    dokku.delete_app = failing_delete

    result = use_case.execute(DeleteAppCommand(app_id=app.id))

    assert result.already_deleted is False
    app.refresh_from_db()
    assert app.deleted_at is not None
