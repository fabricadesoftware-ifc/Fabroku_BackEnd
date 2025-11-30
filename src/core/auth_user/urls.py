from django.urls import include, path, reverse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.reverse import reverse  # noqa: F811
from rest_framework.routers import DefaultRouter

from .views import UserViewSet, check_auth, cookie_token_refresh, logout

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')


@api_view(['GET'])
def authentication_root(request, format=None):
    return Response({
        'auth': reverse('user-root', request=request, format=format),
        'check': reverse('auth-check', request=request, format=format),
        'refresh': reverse('auth-refresh', request=request, format=format),
        'logout': reverse('auth-logout', request=request, format=format),
    })


urlpatterns = [
    path('', include(router.urls)),
    path('', authentication_root, name='user-root'),
    path('check/', check_auth, name='auth-check'),
    path('refresh/', cookie_token_refresh, name='auth-refresh'),
    path('logout/', logout, name='auth-logout'),
]
