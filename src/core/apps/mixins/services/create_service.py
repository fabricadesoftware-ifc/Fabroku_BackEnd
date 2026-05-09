import time
import uuid
from dataclasses import dataclass
from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.mixins.services.service_dokku import (
    check_dokku_output,
    create_dokku_service,
    dokku_output_failed,
    link_dokku_service,
    start_dokku_service,
    sync_service_url_from_dokku,
)
from core.apps.models import App, Service, ServiceType
from core.apps.service_types import ServiceRuntime, get_service_runtime
from core.apps.utils import slugify_dokku
from core.logs.models import AppLogManager, LogCategory


@dataclass
class CreateServiceContext:
    task: Task
    logger: AppLogManager
    dokku_adapter: DokkuAdapter
    app: App
    runtime: ServiceRuntime
    service_name: str
    dokku_service_name: str
    password: str


def _create_remote_service(ctx: CreateServiceContext):
    ctx.task.update_state(
        state='PROGRESS',
        meta={
            'current': 10,
            'total': 100,
            'status': f'Criando servico {ctx.runtime.label} {ctx.dokku_service_name}...',
        },
    )
    ctx.logger.info(
        f'Criando servico {ctx.runtime.label}: {ctx.dokku_service_name}...',
        category=LogCategory.DATABASE,
        progress=10,
    )

    output, command, operation = create_dokku_service(
        ctx.dokku_adapter,
        ctx.runtime,
        ctx.dokku_service_name,
        ctx.password,
    )
    ctx.logger.dokku(output, command=command, category=LogCategory.DATABASE, progress=40)
    if 'already exists' in output.lower():
        ctx.logger.info(
            f'Servico {ctx.dokku_service_name} ja existe, reutilizando...',
            category=LogCategory.DATABASE,
            progress=40,
        )
        return

    check_dokku_output(output, operation)


def _link_remote_service(ctx: CreateServiceContext):
    ctx.task.update_state(
        state='PROGRESS',
        meta={'current': 50, 'total': 100, 'status': 'Vinculando servico ao app...'},
    )
    ctx.logger.info(
        f'Vinculando servico {ctx.dokku_service_name} ao app {ctx.app.name_dokku}...',
        category=LogCategory.DATABASE,
        progress=50,
    )

    output, command, operation = link_dokku_service(
        ctx.dokku_adapter,
        ctx.runtime,
        ctx.dokku_service_name,
        ctx.app.name_dokku,
        no_restart=True,
    )
    ctx.logger.dokku(output, command=command, category=LogCategory.DATABASE, progress=70)
    if 'already linked' in output.lower():
        ctx.logger.info(
            'Servico ja estava vinculado ao app, continuando...',
            category=LogCategory.DATABASE,
            progress=70,
        )
    else:
        check_dokku_output(output, operation)

    sync_service_url_from_dokku(
        app=ctx.app,
        dokku_adapter=ctx.dokku_adapter,
        logger=ctx.logger,
        runtime=ctx.runtime,
        progress=72,
    )


def _start_remote_service(ctx: CreateServiceContext):
    ctx.task.update_state(
        state='PROGRESS',
        meta={'current': 80, 'total': 100, 'status': 'Iniciando servico...'},
    )
    output = start_dokku_service(ctx.dokku_adapter, ctx.runtime, ctx.dokku_service_name, logger=ctx.logger)
    if dokku_output_failed(output):
        ctx.logger.warning(
            f'{ctx.runtime.default_prefix}:start retornou: {output}',
            category=LogCategory.DATABASE,
            progress=82,
        )
    else:
        ctx.logger.info(
            f'Servico {ctx.runtime.label} {ctx.dokku_service_name} iniciado',
            category=LogCategory.DATABASE,
            progress=82,
        )
    if ctx.runtime.service_type == ServiceType.POSTGRES.value:
        time.sleep(3)


def _create_local_service(ctx: CreateServiceContext) -> Service:
    return Service.objects.create(
        name=ctx.service_name,
        service_type=ctx.runtime.service_type,
        user=ctx.runtime.user,
        password=ctx.password,
        host=f'{ctx.runtime.host_prefix}{ctx.dokku_service_name}',
        port=ctx.runtime.port,
        app=ctx.app,
        project=ctx.app.project,
        container_name=ctx.dokku_service_name,
    )


def _restart_app(ctx: CreateServiceContext):
    ctx.task.update_state(
        state='PROGRESS',
        meta={'current': 94, 'total': 100, 'status': f'Reiniciando app para aplicar {ctx.runtime.env_key}...'},
    )
    restart_output = ctx.dokku_adapter.restart_app(ctx.app.name_dokku)
    ctx.logger.dokku(
        restart_output,
        command=f'ps:restart {ctx.app.name_dokku}',
        category=LogCategory.DEPLOY,
        progress=94,
    )


class CreateServiceMixin:
    """Mixin para criacao de servicos via Celery."""

    @shared_task(bind=True)
    def create_service(
        self,
        app_id: int,
        service_type: str,
    ) -> dict:
        """
        Cria um servico no Dokku, vincula ao app e espelha a URL de conexao.

        O link com --no-restart evita restart automatico no meio do fluxo. Depois
        que a variavel foi sincronizada no banco local, reiniciamos o app uma vez
        para que o runtime enxergue a nova configuracao.
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            app = App.objects.get(id=app_id)
        except App.DoesNotExist:
            return {'status': 'error', 'message': f'App {app_id} not found'}

        try:
            runtime = get_service_runtime(service_type)
        except ValueError as exc:
            return {'status': 'error', 'message': str(exc)}

        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()
        service_name = f'{app.name}-{runtime.attached_suffix}'
        dokku_service_name = slugify_dokku(f'{service_name}-{app.id}')
        dokku_service_password = uuid.uuid4().hex if runtime.service_type == ServiceType.POSTGRES.value else ''

        if not app.name_dokku:
            logger.error('App sem name_dokku configurado', category=LogCategory.DATABASE)
            return {'status': 'error', 'message': 'App sem name_dokku'}

        try:
            context = CreateServiceContext(
                task=task,
                logger=logger,
                dokku_adapter=dokku_adapter,
                app=app,
                runtime=runtime,
                service_name=service_name,
                dokku_service_name=dokku_service_name,
                password=dokku_service_password,
            )
            _create_remote_service(context)
            _link_remote_service(context)
            _start_remote_service(context)

            task.update_state(
                state='PROGRESS',
                meta={'current': 90, 'total': 100, 'status': 'Salvando informacoes do servico...'},
            )
            service = _create_local_service(context)
            _restart_app(context)

            logger.success(
                f'Servico {runtime.label} criado e vinculado com sucesso. {runtime.env_key} sincronizada.',
                category=LogCategory.DATABASE,
                progress=100,
            )

            return {
                'status': 'created',
                'service_id': service.id,  # type: ignore
                'service_name': dokku_service_name,
                'service_type': runtime.service_type,
            }

        except Exception as e:
            logger.error(
                f'Erro ao criar servico: {str(e)}',
                category=LogCategory.DATABASE,
                metadata={'error_type': type(e).__name__, 'error_details': str(e)},
            )
            raise
