from django.conf import settings
from django.db.models import Count
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from core.adapters.utils.git_callback import set_auth_cookies

from .models import User
from .serializers import UserAdminSerializer, UserRetrieveSerializer, UserSerializer


@extend_schema(tags=['users'])
class UserViewSet(ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    filterset_fields = ['id', 'name']
    search_fields = ['name', 'email']
    ordering_fields = ['id', 'name', 'date_joined', 'last_login']
    ordering = ['id']

    def get_serializer_class(self):  # type: ignore
        if self.action == 'retrieve':
            return UserRetrieveSerializer
        if self.action == 'admin_list':
            return UserAdminSerializer
        return UserSerializer

    @action(detail=False, methods=['get'])
    def me(self, request):
        user = request.user
        serializer = UserRetrieveSerializer(user)
        return Response(serializer.data)

    def _get_admin_queryset(self):
        return User.objects.annotate(
            annotated_apps_count=Count('projects__app__id', distinct=True),
            annotated_services_count=Count('projects__service__id', distinct=True),
        )

    @action(detail=False, methods=['get'], url_path='admin_list')
    def admin_list(self, request):
        """Lista todos os usuários (somente admin)."""
        if not request.user.is_superuser:
            return Response(
                {'error': 'Permissão negada'},
                status=status.HTTP_403_FORBIDDEN,
            )
        queryset = self.filter_queryset(self._get_admin_queryset())
        serializer = UserAdminSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='toggle_active')
    def toggle_active(self, request, pk=None):
        """Ativa/desativa um usuário (somente admin)."""
        if not request.user.is_superuser:
            return Response(
                {'error': 'Permissão negada'},
                status=status.HTTP_403_FORBIDDEN,
            )
        user = self.get_object()
        if user.id == request.user.id:
            return Response(
                {'error': 'Você não pode desabilitar sua própria conta'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        return Response(UserAdminSerializer(user).data)

    @action(detail=True, methods=['post'], url_path='toggle_admin')
    def toggle_admin(self, request, pk=None):
        """Promove ou remove privilégios administrativos de outro usuário."""
        if not request.user.is_superuser:
            return Response(
                {'error': 'Permissão negada'},
                status=status.HTTP_403_FORBIDDEN,
            )

        user = self.get_object()
        if user.id == request.user.id:
            return Response(
                {'error': 'Você não pode alterar seu próprio status de administrador'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.is_superuser = not user.is_superuser
        user.is_staff = user.is_superuser
        user.save(update_fields=['is_superuser', 'is_staff'])

        return Response(UserAdminSerializer(user).data)

    @action(detail=True, methods=['post'], url_path='set_quota')
    def set_quota(self, request, pk=None):
        """Define limites personalizados de apps/serviços para um usuário (somente admin)."""
        if not request.user.is_superuser:
            return Response(
                {'error': 'Permissão negada'},
                status=status.HTTP_403_FORBIDDEN,
            )
        user = self.get_object()
        max_apps = request.data.get('max_apps')
        max_services = request.data.get('max_services')

        update_fields = []
        if 'max_apps' in request.data:
            user.custom_max_apps = int(max_apps) if max_apps is not None else None
            update_fields.append('custom_max_apps')
        if 'max_services' in request.data:
            user.custom_max_services = int(max_services) if max_services is not None else None
            update_fields.append('custom_max_services')

        if update_fields:
            user.save(update_fields=update_fields)

        return Response(UserAdminSerializer(user).data)

    @action(detail=False, methods=['get'], url_path='my_quota')
    def my_quota(self, request):
        """Retorna as informações de quota do usuário autenticado."""
        user = request.user
        return Response({
            'max_apps': user.max_apps,
            'max_services': user.max_services,
            'apps_count': user.apps_count,
            'services_count': user.services_count,
            'can_create_app': user.can_create_app(),
            'can_create_service': user.can_create_service(),
        })


@extend_schema(tags=['auth'])
class CustomTokenRefreshView(TokenRefreshView):
    """
    View para refresh de tokens JWT.
    """

    pass


@extend_schema(tags=['auth'])
@api_view(['POST'])
@permission_classes([AllowAny])
def cookie_token_refresh(request):
    """
    Refresh do token JWT usando o refresh_token do cookie.
    Gera novos tokens e atualiza os cookies.
    """
    refresh_token = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH_NAME)

    if not refresh_token:
        return Response(
            {'error': 'Refresh token não encontrado nos cookies'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    try:
        refresh = RefreshToken(refresh_token)

        if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS', False):
            user_id = refresh.access_token.payload.get('user_id')
            user = User.objects.get(id=user_id)

            if hasattr(refresh, 'blacklist'):
                try:
                    refresh.blacklist()
                except Exception:
                    pass

            new_refresh = RefreshToken.for_user(user)
            access_token = str(new_refresh.access_token)
            refresh_token = str(new_refresh)
        else:
            access_token = str(refresh.access_token)

        response = Response({'message': 'Token atualizado com sucesso'})
        set_auth_cookies(response, access_token, refresh_token)

        return response

    except (InvalidToken, TokenError) as e:
        return Response(
            {'error': 'Token inválido ou expirado', 'detail': str(e)},
            status=status.HTTP_401_UNAUTHORIZED,
        )


@extend_schema(tags=['auth'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    """
    Logout: remove os cookies de autenticação e invalida o refresh token.
    """
    refresh_token = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH_NAME)

    # Tenta invalidar o refresh token (se blacklist estiver ativo)
    if refresh_token:
        try:
            token = RefreshToken(refresh_token)
            if hasattr(token, 'blacklist'):
                token.blacklist()
        except (InvalidToken, TokenError):
            pass  # Token já inválido, só remove os cookies

    response = Response({'message': 'Logout realizado com sucesso'})

    response.delete_cookie(
        settings.AUTH_COOKIE_NAME,
        path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
    )
    response.delete_cookie(
        settings.AUTH_COOKIE_REFRESH_NAME,
        path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
    )

    return response


@extend_schema(tags=['auth'])
@api_view(['GET'])
@permission_classes([AllowAny])
def check_auth(request):
    """
    Verifica se o usuário está autenticado.
    Retorna os dados do usuário se autenticado, ou erro se não.
    """
    if request.user.is_authenticated:
        serializer = UserRetrieveSerializer(request.user)
        return Response({
            'authenticated': True,
            'user': serializer.data,
        })

    return Response(
        {
            'authenticated': False,
            'user': None,
        },
        status=status.HTTP_401_UNAUTHORIZED,
    )
