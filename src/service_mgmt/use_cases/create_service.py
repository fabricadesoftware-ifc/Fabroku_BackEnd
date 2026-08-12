"""CreateServiceUseCase: business logic for provisioning a Dokku service
(Postgres/PostGIS/Redis), either attached to an App or standalone in a Project.

Ports `core/apps/mixins/services/{create_service,create_service_standalone}.py`
faithfully, reusing `core.apps.mixins.services.service_dokku`'s
`create_dokku_service`/`link_dokku_service`/`start_dokku_service`/
`initialize_dokku_service`/`sync_service_url_from_dokku` helpers directly —
they already only depend on `IDokkuPort` methods, so nothing to port.

Same deviation as every other Fase 4 use case: no `task.update_state(...)`
calls. `App`/`Project`/`Service` `DoesNotExist` are left to propagate
naturally, same precedent as `UpdateAppUseCase`/`ManageAppUseCase`.
Unsupported `service_type` is left to raise `ValueError` from
`get_service_runtime` naturally too, same precedent as `DeleteAppUseCase`
(which also doesn't wrap it in a domain exception).
"""
import time
import uuid
from dataclasses import dataclass

from applications.domain.exceptions import DeploymentFailed
from applications.models import App
from applications.ports.i_dokku import IDokkuPort
from core.apps.mixins.services.service_dokku import (
    check_dokku_output,
    create_dokku_service,
    dokku_output_failed,
    initialize_dokku_service,
    link_dokku_service,
    start_dokku_service,
    sync_service_url_from_dokku,
)
from core.apps.utils import slugify_dokku
from observability.models import AppLogManager, LogCategory
from projects.models import Project
from service_mgmt.models import Service
from service_mgmt.service_types import ServiceRuntime, get_service_runtime, is_postgres_runtime


@dataclass(frozen=True)
class CreateServiceCommand:
    app_id: int
    service_type: str
    service_id: int | None = None
    task_id: str | None = None


@dataclass(frozen=True)
class CreateServiceStandaloneCommand:
    project_id: int
    service_type: str
    name: str | None = None
    service_id: int | None = None
    password: str | None = None
    task_id: str | None = None


@dataclass(frozen=True)
class ServiceCreated:
    service_id: int
    service_name: str
    service_type: str


class CreateServiceUseCase:
    """Provision a Dokku service, attached to an App or standalone in a Project."""

    def __init__(self, dokku_port: IDokkuPort, log_manager: AppLogManager | None = None):
        self.dokku_port = dokku_port
        self.log_manager = log_manager

    def execute_attached(self, cmd: CreateServiceCommand) -> ServiceCreated:
        app = App.objects.get(id=cmd.app_id, deleted_at__isnull=True)
        runtime = get_service_runtime(cmd.service_type)

        app.task_id = cmd.task_id
        app.save(update_fields=['task_id'])

        log_manager = self.log_manager or AppLogManager(app, cmd.task_id)

        service = None
        if cmd.service_id is not None:
            service = Service.objects.get(id=cmd.service_id, app=app, deleted_at__isnull=True)

        service_name = service.name if service else f'{app.name}-{runtime.attached_suffix}'
        dokku_service_name = slugify_dokku(f'{service_name}-{app.id}')
        password = service.password if service else (uuid.uuid4().hex if is_postgres_runtime(runtime) else '')
        env_key = service.env_key if service else runtime.env_key

        if not app.name_dokku:
            log_manager.error('App sem name_dokku configurado', category=LogCategory.DATABASE)
            raise DeploymentFailed(reason='App sem name_dokku configurado', step='validate')

        self._create_remote_service(log_manager, runtime, dokku_service_name, password, service)
        self._link_remote_service(log_manager, app, runtime, dokku_service_name, env_key)
        self._start_remote_service(log_manager, runtime, dokku_service_name)
        self._initialize_remote_service(log_manager, runtime, dokku_service_name)

        service = self._persist_local_service(app, service, runtime, service_name, dokku_service_name, password)

        restart_output = self.dokku_port.restart_app(app.name_dokku)
        log_manager.dokku(restart_output, category=LogCategory.DEPLOY, progress=94)

        log_manager.success(
            f'Serviço {runtime.label} criado e vinculado com sucesso. {service.env_key} sincronizada.',
            category=LogCategory.DATABASE,
            progress=100,
        )

        return ServiceCreated(service_id=service.id, service_name=dokku_service_name, service_type=runtime.service_type)

    def execute_standalone(self, cmd: CreateServiceStandaloneCommand) -> ServiceCreated:
        project = Project.objects.get(id=cmd.project_id)
        runtime = get_service_runtime(cmd.service_type)

        dokku_service_name = (
            slugify_dokku(cmd.name) if cmd.name else f'{runtime.default_prefix}-{uuid.uuid4().hex[:8]}'
        )
        password = (
            cmd.password if cmd.password is not None else (uuid.uuid4().hex if is_postgres_runtime(runtime) else '')
        )
        service_name = cmd.name or dokku_service_name

        service = self._prepare_standalone_service_record(
            project, runtime, service_name, password, cmd.task_id, cmd.service_id
        )

        output, _command, operation = create_dokku_service(self.dokku_port, runtime, dokku_service_name, password)
        if 'already exists' not in output.lower():
            check_dokku_output(output, operation)

        service.container_name = dokku_service_name
        service.host = f'{runtime.host_prefix}{dokku_service_name}'
        service.port = runtime.port
        service.save(update_fields=['container_name', 'host', 'port'])

        start_output = start_dokku_service(self.dokku_port, runtime, dokku_service_name)
        check_dokku_output(start_output, f'{runtime.default_prefix}:start', allow_empty=True)
        if is_postgres_runtime(runtime):
            time.sleep(2)

        initialize_dokku_service(self.dokku_port, runtime, dokku_service_name)

        service.task_id = None
        service.save(update_fields=['task_id'])

        return ServiceCreated(service_id=service.id, service_name=dokku_service_name, service_type=runtime.service_type)

    def _create_remote_service(  # noqa: PLR0913, PLR0917
        self,
        log_manager: AppLogManager,
        runtime: ServiceRuntime,
        dokku_service_name: str,
        password: str,
        service: Service | None,
    ) -> None:
        log_manager.info(
            f'Criando serviço {runtime.label}: {dokku_service_name}...', category=LogCategory.DATABASE, progress=10
        )
        output, _command, operation = create_dokku_service(self.dokku_port, runtime, dokku_service_name, password)
        log_manager.dokku(output, category=LogCategory.DATABASE, progress=40)
        if 'already exists' in output.lower():
            log_manager.info(
                f'Serviço {dokku_service_name} já existe, reutilizando...', category=LogCategory.DATABASE, progress=40
            )
        else:
            check_dokku_output(output, operation)

        if service:
            service.container_name = dokku_service_name
            service.host = f'{runtime.host_prefix}{dokku_service_name}'
            service.image = runtime.image
            service.image_version = runtime.image_version
            service.save(update_fields=['container_name', 'host', 'image', 'image_version'])

    def _link_remote_service(
        self,
        log_manager: AppLogManager,
        app: App,
        runtime: ServiceRuntime,
        dokku_service_name: str,
        env_key: str | None,
    ) -> None:
        log_manager.info(
            f'Vinculando serviço {dokku_service_name} ao app {app.name_dokku}...',
            category=LogCategory.DATABASE,
            progress=50,
        )
        output, _command, operation = link_dokku_service(
            self.dokku_port, runtime, dokku_service_name, app.name_dokku, no_restart=True, env_key=env_key
        )
        log_manager.dokku(output, category=LogCategory.DATABASE, progress=70)
        if 'already linked' in output.lower():
            log_manager.info(
                'Serviço já estava vinculado ao app, continuando...', category=LogCategory.DATABASE, progress=70
            )
        else:
            check_dokku_output(output, operation)

        sync_service_url_from_dokku(
            app=app, dokku_adapter=self.dokku_port, logger=log_manager, runtime=runtime, env_key=env_key, progress=72
        )

    def _start_remote_service(
        self, log_manager: AppLogManager, runtime: ServiceRuntime, dokku_service_name: str
    ) -> None:
        output = start_dokku_service(self.dokku_port, runtime, dokku_service_name, logger=log_manager)
        if dokku_output_failed(output):
            log_manager.warning(
                f'{runtime.default_prefix}:start retornou: {output}', category=LogCategory.DATABASE, progress=82
            )
        else:
            log_manager.info(
                f'Serviço {runtime.label} {dokku_service_name} iniciado', category=LogCategory.DATABASE, progress=82
            )
        if is_postgres_runtime(runtime):
            time.sleep(3)

    def _initialize_remote_service(
        self, log_manager: AppLogManager, runtime: ServiceRuntime, dokku_service_name: str
    ) -> None:
        initialized = initialize_dokku_service(self.dokku_port, runtime, dokku_service_name)
        if not initialized:
            return
        output, _command = initialized
        log_manager.dokku(output, category=LogCategory.DATABASE, progress=88)
        log_manager.info('Extensão PostGIS habilitada e validada.', category=LogCategory.DATABASE, progress=88)

    def _persist_local_service(  # noqa: PLR0913, PLR0917
        self,
        app: App,
        service: Service | None,
        runtime: ServiceRuntime,
        service_name: str,
        dokku_service_name: str,
        password: str,
    ) -> Service:
        service = service or Service(
            name=service_name, service_type=runtime.service_type, app=app, project=app.project, env_key=runtime.env_key
        )
        service.user = runtime.user
        service.password = password
        service.host = f'{runtime.host_prefix}{dokku_service_name}'
        service.port = runtime.port
        service.container_name = dokku_service_name
        service.image = runtime.image
        service.image_version = runtime.image_version
        service.task_id = None
        service.save()
        return service

    def _prepare_standalone_service_record(  # noqa: PLR0913, PLR0917
        self,
        project: Project,
        runtime: ServiceRuntime,
        service_name: str,
        password: str,
        task_id: str | None,
        service_id: int | None,
    ) -> Service:
        if not service_id:
            return Service.objects.create(
                name=service_name,
                service_type=runtime.service_type,
                user=runtime.user,
                password=password,
                host='provisionando...',
                port=runtime.port,
                app=None,
                project=project,
                container_name=None,
                image=runtime.image,
                image_version=runtime.image_version,
                task_id=task_id,
            )

        service = Service.objects.get(id=service_id, deleted_at__isnull=True)
        service.task_id = task_id
        service.name = service_name
        service.service_type = runtime.service_type
        service.user = runtime.user
        service.password = password
        service.port = runtime.port
        service.image = runtime.image
        service.image_version = runtime.image_version
        service.save(
            update_fields=['task_id', 'name', 'service_type', 'user', 'password', 'port', 'image', 'image_version']
        )
        return service
