from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from .models import App
from .serializers import AppSerializer


class AppViewSet(ModelViewSet):
    queryset = App.objects.all()
    serializer_class = AppSerializer

    @action(detail=True, methods=['post'])
    def deploy(self, request, pk=None):
        app = self.get_object()
        # Logic to trigger deployment
        return Response({'status': 'deployment started'})
