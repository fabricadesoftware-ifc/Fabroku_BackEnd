from django.db import transaction
from django.db.models import Prefetch, Q
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from applications.models import App, AppStatus
from applications.tasks import delete_app_task
from identity.models import User
from service_mgmt.models import Service
from service_mgmt.tasks import delete_service_task

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
        """Soft delete do projeto; apps e servicos saem do Dokku pelas tasks de delecao."""
        project = self.get_object()
        is_member = project.users.filter(id=request.user.id).exists()
        if not request.user.is_superuser and not is_member:
            return Response(
                {'error': 'Voce nao tem permissao para deletar este projeto'},
                status=status.HTTP_403_FORBIDDEN,
            )

        app_ids = list(App.objects.filter(project=project, deleted_at__isnull=True).values_list('id', flat=True))
        # Services vinculados a app ativa saem junto com ela pelo delete_app_task.
        service_ids = list(
            Service.objects.filter(project=project, deleted_at__isnull=True)
            .filter(Q(app__isnull=True) | Q(app__deleted_at__isnull=False))
            .values_list('id', flat=True)
        )

        with transaction.atomic():
            project.soft_delete(deleted_by_id=request.user.id)
            App.objects.filter(id__in=app_ids).update(status=AppStatus.DELETING)

        for app_id in app_ids:
            delete_app_task.delay(app_id=app_id, deleted_by_id=request.user.id)
        for service_id in service_ids:
            delete_service_task.delay(service_id=service_id, deleted_by_id=request.user.id)

        return Response(
            {
                'status': 'DELETING',
                'message': f'Deletando projeto {project.name}...',
                'apps': len(app_ids),
                'services': len(service_ids),
            },
            status=status.HTTP_202_ACCEPTED,
        )
