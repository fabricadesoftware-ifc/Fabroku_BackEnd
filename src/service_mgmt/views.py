from celery.result import AsyncResult
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from applications.models import App
from core.apps.mixins.services.service_env import allocate_service_env_key
from core.apps.utils import has_global_access
from service_mgmt.models import Service
from service_mgmt.service_types import get_service_runtime
from service_mgmt.tasks import delete_service_task, link_service_task, unlink_service_task

from .serializers import ServiceSerializer


@extend_schema(tags=['services'])
class ServiceViewSet(ModelViewSet):
    """ViewSet para gerenciamento de serviços (banco de dados, redis, etc.)."""

    queryset = Service.objects.filter(deleted_at__isnull=True)
    serializer_class = ServiceSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['app', 'project', 'service_type']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        """Superusers veem todos os serviços, usuários normais só os seus."""
        queryset = Service.objects.filter(deleted_at__isnull=True)
        if has_global_access(self.request.user):
            return queryset.order_by('-created_at', '-id')
        return queryset.filter(project__users=self.request.user).order_by('-created_at', '-id')

    def destroy(self, request, *args, **kwargs):
        """Dispara task de deleção do serviço no Dokku."""
        instance = self.get_object()

        task_result = delete_service_task.delay(service_id=instance.id, deleted_by_id=request.user.id)

        if instance.app:
            instance.app.task_id = task_result.id
            instance.app.save(update_fields=['task_id'])
        else:
            instance.task_id = task_result.id
            instance.save(update_fields=['task_id'])

        return Response(
            {
                'status': 'DELETING',
                'message': f'Deletando serviço {instance.name}...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def link(self, request, pk=None):
        """Vincula o serviço a um app. Requer app_id no body."""
        service = self.get_object()
        app_id = request.data.get('app_id')
        if not app_id:
            return Response(
                {'error': 'O campo app_id é obrigatório'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if service.app_id:
            return Response(
                {'error': f'Serviço já vinculado ao app {service.app_id}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        app = App.objects.filter(id=app_id, deleted_at__isnull=True).first()
        if not app:
            return Response(
                {'error': 'App nao encontrado'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if service.project_id != app.project_id:
            return Response(
                {'error': 'Servico e app devem pertencer ao mesmo projeto'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not service.container_name:
            return Response(
                {
                    'error': (
                        'Servico ainda nao foi provisionado. Aguarde finalizar a criacao antes de vincular.'
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        if not app.name_dokku:
            return Response(
                {'error': 'App ainda nao foi provisionado no Dokku'},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            runtime = get_service_runtime(service.service_type)
            with transaction.atomic():
                locked_app = App.objects.select_for_update().get(id=app.id)
                locked_service = Service.objects.select_for_update().get(id=service.id)
                locked_service.env_key = allocate_service_env_key(
                    app=locked_app,
                    service_name=locked_service.name,
                    runtime=runtime,
                    exclude_service_id=locked_service.id,
                )
                locked_service.app = locked_app
                locked_service.save(update_fields=['app', 'env_key'])

            task_result = link_service_task.delay(
                service_id=service.id,
                app_id=int(app_id),
            )
        except Exception:
            Service.objects.filter(id=service.id, task_id__isnull=True).update(app=None, env_key=None)
            raise

        app.task_id = task_result.id
        app.save(update_fields=['task_id'])
        Service.objects.filter(id=service.id).update(task_id=task_result.id)

        return Response(
            {
                'status': 'LINKING',
                'message': 'Vinculando serviço ao app...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def unlink(self, request, pk=None):
        """Desvincula o serviço do app."""
        service = self.get_object()

        if not service.app_id:
            return Response(
                {'error': 'Serviço não está vinculado a nenhum app'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task_result = unlink_service_task.delay(service_id=service.id)

        app = service.app
        app.task_id = task_result.id
        app.save(update_fields=['task_id'])

        return Response(
            {
                'status': 'UNLINKING',
                'message': 'Desvinculando serviço do app...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['get'])
    def get_service_status(self, request, pk=None):
        """Retorna o status da task em execução (criação, link, unlink, delete)."""
        service = self.get_object()

        task_id = service.task_id or (service.app.task_id if service.app else None)
        if not task_id:
            # Task já concluiu e limpou task_id; se tem container_name, foi provisionado
            if service.container_name:
                return Response({
                    'state': 'SUCCESS',
                    'status': 'Serviço provisionado com sucesso!',
                    'current': 100,
                })
            return Response({'state': 'UNKNOWN', 'status': 'Nenhuma task vinculada.'})

        task_result = AsyncResult(task_id)
        response_data = {
            'task_id': task_id,
            'state': task_result.state,
        }
        if task_result.state == 'PROGRESS':
            response_data.update(task_result.info)
        elif task_result.state == 'SUCCESS':
            response_data['status'] = 'Operação concluída com sucesso!'
            response_data['current'] = 100
        elif task_result.state == 'FAILURE':
            response_data['status'] = str(task_result.result)

        return Response(response_data)
