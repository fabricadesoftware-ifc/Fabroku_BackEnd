from celery.result import AsyncResult
from drf_spectacular.utils import extend_schema
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from core.apps.mixins import AppMixin
from core.apps.mixins.apps.run_command import ALLOWED_COMMANDS, ALLOWED_PREFIXES, is_command_allowed

from .models import App, Service
from .serializers import AppSerializer, ServiceSerializer


@extend_schema(tags=['apps'])
class AppViewSet(ModelViewSet):
    queryset = App.objects.all()
    serializer_class = AppSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['project', 'status', 'name', 'branch']

    def get_queryset(self):
        """Superusers veem todos os apps, usuários normais só os seus."""
        if self.request.user.is_superuser:
            return App.objects.all()
        return App.objects.filter(project__users=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Override destroy para lançar task de deleção no Dokku."""
        instance = self.get_object()

        # Atualiza status para indicar que está deletando
        instance.status = 'DELETING'
        instance.save(update_fields=['status'])

        # Lança a task de deleção
        task_result = AppMixin.delete_app.delay(app_id=instance.id)  # type: ignore

        return Response(
            {
                'status': 'DELETING',
                'message': f'Deletando aplicação {instance.name}...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Inicia uma aplicação parada."""
        app = self.get_object()

        if not app.name_dokku:
            return Response(
                {'error': 'App não tem name_dokku configurado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        app.status = 'STARTING'
        app.save(update_fields=['status'])

        task_result = AppMixin.manage_app.delay(app_id=app.id, action='start')  # type: ignore

        return Response(
            {
                'status': 'STARTING',
                'message': f'Iniciando aplicação {app.name}...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """Para uma aplicação em execução."""
        app = self.get_object()

        if not app.name_dokku:
            return Response(
                {'error': 'App não tem name_dokku configurado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        app.status = 'STOPPING'
        app.save(update_fields=['status'])

        task_result = AppMixin.manage_app.delay(app_id=app.id, action='stop')  # type: ignore

        return Response(
            {
                'status': 'STOPPING',
                'message': f'Parando aplicação {app.name}...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def restart(self, request, pk=None):
        """Reinicia uma aplicação."""
        app = self.get_object()

        if not app.name_dokku:
            return Response(
                {'error': 'App não tem name_dokku configurado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        app.status = 'RESTARTING'
        app.save(update_fields=['status'])

        task_result = AppMixin.manage_app.delay(app_id=app.id, action='restart')  # type: ignore

        return Response(
            {
                'status': 'RESTARTING',
                'message': f'Reiniciando aplicação {app.name}...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['get'])
    def get_app_status(self, request, pk=None):
        app = self.get_object()

        if not app.task_id:
            return Response({'state': 'UNKNOWN', 'status': 'Nenhuma task vinculada.'})

        task_result = AsyncResult(app.task_id)

        response_data = {
            'task_id': app.task_id,
            'state': task_result.state,  # PENDING, PROGRESS, SUCCESS, FAILURE
        }

        if task_result.state == 'PROGRESS':
            response_data.update(task_result.info)

        elif task_result.state == 'SUCCESS':
            response_data['status'] = 'Aplicação criada com sucesso!'
            response_data['current'] = 100

        elif task_result.state == 'FAILURE':
            response_data['status'] = str(task_result.result)

        return Response(response_data)

    @action(detail=True, methods=['post'])
    def run_command(self, request, pk=None):
        """Executa um comando dentro do container do app (ex: migrate, collectstatic)."""
        app = self.get_object()

        if not app.name_dokku:
            return Response(
                {'error': 'App não tem name_dokku configurado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        command = request.data.get('command', '').strip()
        if not command:
            return Response(
                {'error': 'O campo "command" é obrigatório'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not is_command_allowed(command):
            return Response(
                {
                    'error': f'Comando não permitido: {command}',
                    'allowed_commands': sorted(ALLOWED_COMMANDS),
                    'allowed_prefixes': list(ALLOWED_PREFIXES),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        task_result = AppMixin.run_command.delay(app_id=app.id, command=command)  # type: ignore

        app.task_id = task_result.id
        app.save(update_fields=['task_id'])

        return Response(
            {
                'status': 'RUNNING',
                'message': f'Executando: {command}',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['get'])
    def allowed_commands(self, request, pk=None):
        """Lista os comandos permitidos para execução."""
        return Response({
            'commands': sorted(ALLOWED_COMMANDS),
            'prefixes': list(ALLOWED_PREFIXES),
        })


@extend_schema(tags=['services'])
class ServiceViewSet(ModelViewSet):
    """ViewSet para gerenciamento de serviços (banco de dados, redis, etc.)."""

    queryset = Service.objects.all()
    serializer_class = ServiceSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['app', 'project', 'service_type']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        """Superusers veem todos os serviços, usuários normais só os seus."""
        if self.request.user.is_superuser:
            return Service.objects.all()
        return Service.objects.filter(project__users=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Dispara task de deleção do serviço no Dokku."""
        instance = self.get_object()

        task_result = AppMixin.delete_service.delay(service_id=instance.id)  # type: ignore

        return Response(
            {
                'status': 'DELETING',
                'message': f'Deletando serviço {instance.name}...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )
