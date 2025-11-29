from drf_spectacular.utils import extend_schema
from rest_framework.viewsets import ModelViewSet

from .models import Project
from .serializers import ProjectSerializer


@extend_schema(tags=['projects'])
class ProjectViewSet(ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
