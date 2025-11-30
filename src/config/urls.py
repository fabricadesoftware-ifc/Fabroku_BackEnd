from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin as django_admin
from django.shortcuts import redirect
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.reverse import reverse

from core.adapters.utils.git_callback import github_callback
from core.adapters.utils.git_redirect import github_login
from core.adapters.utils.git_repos import get_git_repos
from core.auth_user.views import CustomTokenRefreshView


@api_view(['GET'])
def api_root(request, format=None):
    return Response({
        'users': reverse('user-root', request=request, format=format),
        'apps': reverse('app-root', request=request, format=format),
        'projects': reverse('project-root', request=request, format=format),
        'logs': reverse('logs-list', request=request, format=format),
    })


urlpatterns = [
    path('api/', api_root, name='api-root'),
    path('api/auth/', include('core.auth_user.urls')),
    path('api/apps/', include('core.apps.urls')),
    path('api/projects/', include('core.project.urls')),
    path('api/logs/', include('core.logs.urls')),
    path('api/token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('api/admin/', django_admin.site.urls),
    path('api/auth/github/callback/', github_callback),
    path('api/auth/github/login/', github_login),
    path('api/git/repos', get_git_repos),
    path('', lambda request: redirect('api/', permanent=True)),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


if settings.DEBUG:
    urlpatterns += [
        path('api/swagger/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
        path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    ]
