from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from .models import Project
from .serializers import ProjectSerializer


@extend_schema(tags=['projects'])
class ProjectViewSet(ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Retorna apenas os projetos do usuário logado."""
        return Project.objects.filter(users=self.request.user)

    def perform_create(self, serializer):
        """Ao criar um projeto, adiciona o usuário atual automaticamente."""
        project = serializer.save()
        project.users.add(self.request.user)
