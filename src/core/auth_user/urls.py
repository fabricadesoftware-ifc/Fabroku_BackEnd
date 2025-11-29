from django.urls import include, path, reverse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.reverse import reverse  # noqa: F811
from rest_framework.routers import DefaultRouter

from .views import UserViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')


@api_view(['GET'])
def authentication_root(request, format=None):
    return Response({
        'auth': reverse('user-root', request=request, format=format),
    })


urlpatterns = [
    path('', include(router.urls)),
    path('', authentication_root, name='user-root'),
]
