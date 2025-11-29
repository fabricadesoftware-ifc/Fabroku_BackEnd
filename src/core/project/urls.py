from django.urls import include, path, reverse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.reverse import reverse  # noqa: F811
from rest_framework.routers import DefaultRouter

from .views import ProjectViewSet

router = DefaultRouter()
router.register(r'projects', ProjectViewSet, basename='project')


@api_view(['GET'])
def authentication_root(request, format=None):
    return Response({
        'projects': reverse('project-list', request=request, format=format),
    })


urlpatterns = [
    path('', include(router.urls)),
    path('', authentication_root, name='project-root'),
]
