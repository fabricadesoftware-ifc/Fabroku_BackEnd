"""Serviço Armazenamento S3 (Garage): criar, vincular, desvincular e apagar, com fakes."""
import pytest

from applications.domain.exceptions import DeploymentFailed
from service_mgmt.models import Service
from service_mgmt.s3 import AWS_ENV_KEYS, bucket_name
from service_mgmt.use_cases.create_service import (
    CreateServiceCommand,
    CreateServiceStandaloneCommand,
    CreateServiceUseCase,
)
from service_mgmt.use_cases.delete_service import DeleteServiceCommand, DeleteServiceUseCase
from service_mgmt.use_cases.link_service import LinkServiceCommand, LinkServiceUseCase
from service_mgmt.use_cases.unlink_service import UnlinkServiceCommand, UnlinkServiceUseCase
from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory
from tests.fakes import FakeDokkuPort
from tests.fakes.fake_object_storage import FakeObjectStorage

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def s3_settings(settings):
    settings.FABROKU_S3_ENDPOINT = 'https://s3.test'
    settings.FABROKU_S3_REGION = 'garage'
    settings.FABROKU_S3_QUOTA_MB = 10
    settings.FABROKU_S3_MAX_OBJECTS = 100


def app_with_dokku(name='my-app'):
    app = AppFactory(project=ProjectFactory(), name_dokku=name, variables={'DEBUG': '1'})
    dokku = FakeDokkuPort()
    dokku.create_app(name)
    return app, dokku


def test_create_attached_s3_creates_bucket_and_sets_env():
    app, dokku = app_with_dokku()
    storage = FakeObjectStorage()

    result = CreateServiceUseCase(dokku_port=dokku, storage_port=storage).execute_attached(
        CreateServiceCommand(app_id=app.id, service_type='s3')
    )

    service = Service.objects.get(id=result.service_id)
    assert service.container_name == result.service_name in storage.buckets
    assert storage.buckets[service.container_name]['quota'] == (10 * 1024 * 1024, 100)
    assert service.host == 's3.test' and service.port == 443
    assert service.user.startswith('GK') and service.password == f'segredo-{service.container_name}'

    env = dokku.apps['my-app']['env_vars']
    assert env['S3_URL'] == f'https://{service.user}:{service.password}@s3.test/{service.container_name}'
    assert env['AWS_STORAGE_BUCKET_NAME'] == service.container_name
    assert env['AWS_S3_ENDPOINT_URL'] == 'https://s3.test'
    assert env['AWS_S3_ADDRESSING_STYLE'] == 'path'
    app.refresh_from_db()
    assert app.variables['DEBUG'] == '1' and app.variables['S3_URL'] == env['S3_URL']
    assert 'restart_app' in [call['method'] for call in dokku.get_calls()]


def test_create_attached_s3_refuses_bucket_of_someone_else():
    app, dokku = app_with_dokku()
    storage = FakeObjectStorage()
    storage.buckets[bucket_name(f'{app.name}-storage-{app.id}')] = {'key_id': 'GKoutro', 'secret': 'x', 'objects': 3}

    with pytest.raises(DeploymentFailed):
        CreateServiceUseCase(dokku_port=dokku, storage_port=storage).execute_attached(
            CreateServiceCommand(app_id=app.id, service_type='s3')
        )
    assert 'S3_URL' not in dokku.apps['my-app']['env_vars']


def test_create_attached_s3_retry_reuses_own_bucket():
    app, dokku = app_with_dokku()
    storage = FakeObjectStorage()
    use_case = CreateServiceUseCase(dokku_port=dokku, storage_port=storage)
    first = use_case.execute_attached(CreateServiceCommand(app_id=app.id, service_type='s3'))

    again = use_case.execute_attached(
        CreateServiceCommand(app_id=app.id, service_type='s3', service_id=first.service_id)
    )

    assert again.service_name == first.service_name
    assert len(storage.buckets) == 1


def test_create_standalone_s3_has_no_env_and_saves_credentials():
    project = ProjectFactory()
    storage = FakeObjectStorage()
    placeholder = Service.objects.create(
        name='fotos', service_type='s3', user='', password='', host='provisionando...', port=443, project=project
    )

    result = CreateServiceUseCase(dokku_port=FakeDokkuPort(), storage_port=storage).execute_standalone(
        CreateServiceStandaloneCommand(project_id=project.id, service_type='s3', name='fotos', service_id=placeholder.id)
    )

    placeholder.refresh_from_db()
    assert result.service_name == 'fotos' == placeholder.container_name
    assert placeholder.user.startswith('GK') and placeholder.task_id is None


def s3_service(app, storage, *, env_key='S3_URL', bucket='blog-storage-1'):
    creds = storage.ensure_bucket(bucket, max_size_bytes=None, max_objects=None)
    return ServiceFactory(
        app=app, project=app.project, service_type='s3', container_name=bucket, env_key=env_key,
        user=creds.access_key_id, password=creds.secret_access_key, host='s3.test', port=443,
    )


def test_link_unlink_s3_sets_and_removes_all_variables():
    app, dokku = app_with_dokku()
    storage = FakeObjectStorage()
    service = s3_service(app, storage)
    service.app = None
    service.save()
    service.app = app  # o view já grava app + env_key antes de despachar a task
    service.save()

    LinkServiceUseCase(dokku_port=dokku).execute(LinkServiceCommand(service_id=service.id, app_id=app.id))
    env = dokku.apps['my-app']['env_vars']
    assert {'S3_URL', *AWS_ENV_KEYS} <= set(env)

    UnlinkServiceUseCase(dokku_port=dokku).execute(UnlinkServiceCommand(service_id=service.id))
    env = dokku.apps['my-app']['env_vars']
    assert not ({'S3_URL', *AWS_ENV_KEYS} & set(env))
    app.refresh_from_db()
    assert app.variables == {'DEBUG': '1'}
    assert 'blog-storage-1' in storage.buckets  # desvincular não apaga os arquivos


def test_second_s3_on_same_app_only_gets_its_own_url():
    app, dokku = app_with_dokku()
    storage = FakeObjectStorage()
    service = s3_service(app, storage, env_key='FOTOS_URL', bucket='fotos-1')

    LinkServiceUseCase(dokku_port=dokku).execute(LinkServiceCommand(service_id=service.id, app_id=app.id))

    env = dokku.apps['my-app']['env_vars']
    assert 'FOTOS_URL' in env and 'AWS_ACCESS_KEY_ID' not in env


def test_delete_s3_unsets_env_and_deletes_bucket():
    app, dokku = app_with_dokku()
    storage = FakeObjectStorage()
    service = s3_service(app, storage)
    dokku.set_config('my-app', {'S3_URL': 'x', 'AWS_ACCESS_KEY_ID': 'y'})

    DeleteServiceUseCase(dokku_port=dokku, storage_port=storage).execute(DeleteServiceCommand(service_id=service.id))

    service.refresh_from_db()
    assert service.deleted_at is not None
    assert 'blog-storage-1' not in storage.buckets
    assert 'S3_URL' not in dokku.apps['my-app']['env_vars']


def test_delete_s3_never_provisioned_does_not_touch_other_buckets():
    project = ProjectFactory()
    storage = FakeObjectStorage()
    storage.ensure_bucket('fotos', max_size_bytes=None, max_objects=None)  # de outro aluno
    service = Service.objects.create(
        name='fotos', service_type='s3', user='', password='', host='provisionando...', port=443, project=project
    )

    DeleteServiceUseCase(dokku_port=FakeDokkuPort(), storage_port=storage).execute(
        DeleteServiceCommand(service_id=service.id)
    )

    assert 'fotos' in storage.buckets


def test_bucket_name_rules():
    assert bucket_name('a' * 80) == 'a' * 63
    assert len(bucket_name('ab')) >= 3
    assert bucket_name('x' * 62 + '-y') == 'x' * 62
