from celery.result import AsyncResult
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from .models import App
from .serializers import AppSerializer


class AppViewSet(ModelViewSet):
    queryset = App.objects.all()
    serializer_class = AppSerializer

    # @action(detail=True, methods=['post'])
    # def deploy(self, request, pk=None):
    #     app = self.get_object()
    #     # Logic to trigger deployment
    #     return Response({'status': 'deployment started'})

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
