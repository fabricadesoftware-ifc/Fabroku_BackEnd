from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


def get_public_platform_config() -> dict[str, str]:
    """Retorna configuracoes publicas que mudam entre instalacoes do Fabroku."""
    return {
        'organization_name': settings.FABROKU_ORGANIZATION_NAME,
        'privileged_role_label': settings.FABROKU_PRIVILEGED_ROLE_LABEL,
        'regular_role_label': settings.FABROKU_REGULAR_ROLE_LABEL,
        'app_domain_suffix': settings.FABROKU_APP_DOMAIN_SUFFIX,
    }


@api_view(['GET'])
@permission_classes([AllowAny])
def platform_config(request):
    return Response(get_public_platform_config())
