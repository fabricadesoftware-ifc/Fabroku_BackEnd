from celery.result import AsyncResult
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from core.apps.mixins import AppMixin

from .models import App
from .serializers import AppSerializer


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
