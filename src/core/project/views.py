from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from core.auth_user.models import User

from .models import Project
from .serializers import ProjectSerializer


def _has_global_access(user) -> bool:
    """Retorna True para perfis com visibilidade administrativa global."""
    return bool(getattr(user, 'is_superuser', False))


@extend_schema(tags=['projects'])
class ProjectViewSet(ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Superusers veem todos os projetos, usuarios normais so os seus."""
        user_queryset = User.objects.only('id', 'name', 'email', 'avatar_url')
        queryset = (
            Project.objects.only('id', 'name', 'created_at', 'updated_at')
            .prefetch_related(Prefetch('users', queryset=user_queryset))
            .order_by('-created_at', '-id')
        )

        if _has_global_access(self.request.user):
            return queryset
        return queryset.filter(users=self.request.user).distinct()

    def perform_create(self, serializer):
        """Ao criar um projeto, adiciona o usuario atual automaticamente."""
        project = serializer.save()
        project.users.add(self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Apenas superusers ou donos do projeto podem deletar."""
        project = self.get_object()
        is_member = project.users.filter(id=request.user.id).exists()
        if not request.user.is_superuser and not is_member:
            return Response(
                {'error': 'Voce nao tem permissao para deletar este projeto'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)
