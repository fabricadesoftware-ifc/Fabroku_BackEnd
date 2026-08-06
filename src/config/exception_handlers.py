"""Exception handlers for Django REST Framework.

Maps domain exceptions to appropriate HTTP responses.
Register this in settings.py under REST_FRAMEWORK['EXCEPTION_HANDLER']
"""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from applications.domain.exceptions import (
    AppLimitExceeded,
    AppNameConflict,
    AppNotFound,
    DeploymentFailed,
    GitError,
    InfrastructureError,
    InvalidEnvVar,
    ServiceLimitExceeded,
    ServiceNotFound,
)


def fabroku_exception_handler(exc, context):
    """
    Custom exception handler that maps domain exceptions to HTTP responses.
    
    Falls back to Django REST Framework's default handler for other exceptions.
    """

    # Handle domain exceptions
    if isinstance(exc, AppLimitExceeded):
        return Response(
            {
                'code': 'app_limit_exceeded',
                'detail': str(exc),
                'current': exc.current,
                'limit': exc.limit,
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, AppNameConflict):
        return Response(
            {
                'code': 'app_name_conflict',
                'detail': str(exc),
                'name': exc.name,
            },
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, AppNotFound):
        return Response(
            {
                'code': 'app_not_found',
                'detail': str(exc),
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, DeploymentFailed):
        return Response(
            {
                'code': 'deployment_failed',
                'detail': str(exc),
                'reason': exc.reason,
                'step': exc.step,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, InfrastructureError):
        return Response(
            {
                'code': 'infrastructure_error',
                'detail': str(exc),
                'message': exc.message,
                'details': exc.details,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, ServiceLimitExceeded):
        return Response(
            {
                'code': 'service_limit_exceeded',
                'detail': str(exc),
                'current': exc.current,
                'limit': exc.limit,
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, ServiceNotFound):
        return Response(
            {
                'code': 'service_not_found',
                'detail': str(exc),
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, InvalidEnvVar):
        return Response(
            {
                'code': 'invalid_env_var',
                'detail': str(exc),
                'key': exc.key,
                'reason': exc.reason,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, GitError):
        return Response(
            {
                'code': 'git_error',
                'detail': str(exc),
                'message': exc.message,
                'git_url': exc.git_url,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Fall back to DRF's default exception handler
    return drf_exception_handler(exc, context)
