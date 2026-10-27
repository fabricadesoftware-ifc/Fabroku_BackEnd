"""Admin notifications: criadas nas falhas de delecao no Dokku e expostas so para superusers."""
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from applications.domain.exceptions import InfrastructureError
from applications.use_cases.delete_app import DeleteAppCommand, DeleteAppUseCase
from observability.models import AdminNotification, AdminNotificationEvent, AppLogManager
from service_mgmt.use_cases.delete_service import DeleteServiceCommand, DeleteServiceUseCase
from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory, UserFactory
from tests.fakes import FakeDokkuPort

pytestmark = pytest.mark.django_db

URL = '/api/admin-api/notifications/'
SEEDED = 2


def failing(*args, **kwargs):
    raise RuntimeError('ssh connection error')


def test_app_delete_failure_notifies_admins():
    app = AppFactory(project=ProjectFactory(), name_dokku='my-app')
    dokku = FakeDokkuPort()
    dokku.create_app('my-app')
    dokku.delete_app = failing
    use_case = DeleteAppUseCase(dokku_port=dokku, log_manager=AppLogManager(app, task_id='t'))

    with pytest.raises(InfrastructureError):
        use_case.execute(DeleteAppCommand(app_id=app.id))

    notification = AdminNotification.objects.get()
    assert notification.event_type == AdminNotificationEvent.APP_DELETE_FAILED
    assert notification.app_id == app.id
    assert 'ssh connection error' in notification.message


def test_app_delete_success_does_not_notify():
    app = AppFactory(project=ProjectFactory(), name_dokku='my-app')
    dokku = FakeDokkuPort()
    dokku.create_app('my-app')

    DeleteAppUseCase(dokku_port=dokku, log_manager=AppLogManager(app, task_id='t')).execute(
        DeleteAppCommand(app_id=app.id)
    )

    assert not AdminNotification.objects.exists()


def test_service_delete_failure_notifies_admins():
    service = ServiceFactory(project=ProjectFactory(), service_type='postgres', container_name='solo-db')
    dokku = FakeDokkuPort()
    dokku.delete_database = failing

    DeleteServiceUseCase(dokku_port=dokku).execute(DeleteServiceCommand(service_id=service.id))

    notification = AdminNotification.objects.get()
    assert notification.event_type == AdminNotificationEvent.SERVICE_DELETE_FAILED
    assert notification.service_id == service.id


def test_linked_service_delete_failure_during_app_delete_notifies_admins():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    ServiceFactory(app=app, project=project, service_type='postgres', container_name='my-app-db')
    dokku = FakeDokkuPort()
    dokku.create_app('my-app')
    dokku.delete_database = failing

    DeleteAppUseCase(dokku_port=dokku, log_manager=AppLogManager(app, task_id='t')).execute(
        DeleteAppCommand(app_id=app.id)
    )

    assert AdminNotification.objects.filter(event_type=AdminNotificationEvent.SERVICE_DELETE_FAILED).count() == 1


def make_notifications():
    AdminNotification.objects.create(event_type=AdminNotificationEvent.APP_DELETE_FAILED, title='a')
    AdminNotification.objects.create(event_type=AdminNotificationEvent.SERVICE_DELETE_FAILED, title='b')


def test_only_superusers_can_access():
    client = APIClient()
    client.force_authenticate(user=UserFactory())

    assert client.get(URL).status_code == status.HTTP_403_FORBIDDEN
    assert client.get(f'{URL}unread_count/').status_code == status.HTTP_403_FORBIDDEN


def test_superuser_reads_and_marks_notifications():
    make_notifications()
    admin = UserFactory(is_superuser=True)
    client = APIClient()
    client.force_authenticate(user=admin)

    assert client.get(f'{URL}unread_count/').data['count'] == SEEDED

    first_id = client.get(URL, {'unread': '1'}).data['results'][0]['id']
    response = client.post(f'{URL}{first_id}/read/')
    assert response.status_code == status.HTTP_200_OK
    assert response.data['read_at'] is not None
    assert client.get(f'{URL}unread_count/').data['count'] == 1

    assert client.post(f'{URL}read_all/').data['updated'] == 1
    assert client.get(f'{URL}unread_count/').data['count'] == 0
    assert AdminNotification.objects.filter(read_by=admin).count() == SEEDED
