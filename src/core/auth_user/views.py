from django.conf import settings
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

# from config.permission import CustomUserPermission
from .models import User
from .serializers import UserRetrieveSerializer, UserSerializer


@extend_schema(tags=['users'])
class UserViewSet(ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    filterset_fields = ['id', 'name']
    search_fields = ['name', 'email']
    ordering_fields = ['id', 'name']
    ordering = ['id']

    # permission_classes = [CustomUserPermission]

    def get_serializer_class(self):  # type: ignore
        if self.action == 'retrieve':
            return UserRetrieveSerializer
        return UserSerializer

    @action(detail=False, methods=['get'])
    def me(self, request):
        user = request.user
        serializer = UserRetrieveSerializer(user)
        return Response(serializer.data)


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

        # Se ROTATE_REFRESH_TOKENS está ativo, gera novo refresh token
        if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS', False):
            # Busca o usuário pelo ID no payload
            user_id = refresh.access_token.payload.get('user_id')
            user = User.objects.get(id=user_id)

            # Blacklist o token antigo se disponível
            if hasattr(refresh, 'blacklist'):
                try:
                    refresh.blacklist()
                except Exception:
                    pass

            # Gera novos tokens
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

    # Remove os cookies
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
