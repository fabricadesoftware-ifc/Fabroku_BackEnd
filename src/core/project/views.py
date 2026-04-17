from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from .models import Project
from .serializers import ProjectSerializer


def _has_global_access(user) -> bool:
    """Retorna True para perfis com visibilidade administrativa global."""
    return bool(getattr(user, 'is_superuser', False) or getattr(user, 'is_fabric', False))


@extend_schema(tags=['projects'])
class ProjectViewSet(ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Superusers veem todos os projetos, usuários normais só os seus."""
        if _has_global_access(self.request.user):
            return Project.objects.all()
        return Project.objects.filter(users=self.request.user)

    def perform_create(self, serializer):
        """Ao criar um projeto, adiciona o usuário atual automaticamente."""
        project = serializer.save()
        project.users.add(self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Apenas superusers ou donos do projeto podem deletar."""
        project = self.get_object()
        is_member = project.users.filter(id=request.user.id).exists()
        if not request.user.is_superuser and not is_member:
            return Response(
                {'error': 'Você não tem permissão para deletar este projeto'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)
