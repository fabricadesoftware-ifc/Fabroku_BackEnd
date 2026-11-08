"""
Autenticação customizada via cookies HTTP-only e CLIToken.
"""

from functools import lru_cache
from urllib.parse import urlsplit

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken


def _origin_of(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f'{parts.scheme.lower()}://{parts.netloc.lower()}'


@lru_cache(maxsize=1)
def trusted_cookie_origins() -> frozenset[str]:
    """Origens que podem fazer requisicoes com efeito usando o cookie de sessao.

    Lista exata (sem wildcard/regex): o frontend, o proprio backend (browsable API) e
    CORS_ALLOWED_ORIGINS. Apps hospedados em `*.class.<dominio>` NAO entram aqui.
    """
    origins = set()
    for raw in [settings.FRONTEND_URL, settings.BACKEND_URL, *getattr(settings, 'CORS_ALLOWED_ORIGINS', [])]:
        origin = _origin_of(raw)
        if origin:
            origins.add(origin)
    return frozenset(origins)


def _request_origin(request) -> str | None:
    """Origem declarada pelo navegador: header Origin, senao a do Referer."""
    origin = request.META.get('HTTP_ORIGIN')
    if origin:
        return origin.strip().lower()
    return _origin_of(request.META.get('HTTP_REFERER'))


def reject_cross_site_cookie_request(request) -> None:
    """Protecao CSRF para autenticacao por cookie.

    O DRF nao aplica CsrfViewMiddleware em APIView; so SessionAuthentication checa CSRF.
    Como o cookie JWT e enviado automaticamente pelo navegador (SameSite=None em
    producao e dominio pai compartilhado com os apps dos alunos), qualquer pagina
    poderia disparar POST/PATCH/DELETE autenticados. Navegadores sempre mandam
    `Origin` em requisicoes cross-origin com efeito (e `Origin: null` em alguns
    casos); se vier e nao for de uma origem confiavel, recusa. Sem Origin nem
    Referer (clientes nao-navegador) segue, igual ao que o header Authorization ja permite.
    """
    if request.method in SAFE_METHODS:
        return
    origin = _request_origin(request)
    if origin is None:
        return
    if origin == 'null' or origin not in trusted_cookie_origins():
        raise PermissionDenied('Origem não autorizada para requisição autenticada por cookie.')


class CookieJWTAuthentication(JWTAuthentication):
    """
    Autenticação JWT que lê o token dos cookies HTTP-only.
    Também suporta o header Authorization como fallback.
    """

    def authenticate(self, request):
        # Primeiro tenta o header Authorization (compatibilidade)
        header = self.get_header(request)
        if header is not None:
            raw_token = self.get_raw_token(header)
            if raw_token is not None:
                validated_token = self.get_validated_token(raw_token)
                return self.get_user(validated_token), validated_token

        # Se não tem header, tenta o cookie
        raw_token = request.COOKIES.get(settings.AUTH_COOKIE_NAME)
        if raw_token is None:
            return None

        try:
            validated_token = self.get_validated_token(raw_token.encode())
        except InvalidToken:
            return None

        reject_cross_site_cookie_request(request)

        return self.get_user(validated_token), validated_token


class CLITokenAuthentication(BaseAuthentication):
    """
    Autenticação via token da CLI Fabroku.
    Header: Authorization: CLI <token>
    """

    keyword = 'CLI'

    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith(f'{self.keyword} '):
            return None

        token = auth_header[len(self.keyword) + 1 :].strip()
        if not token:
            return None

        from identity.models import CLIToken

        try:
            cli_token = CLIToken.objects.select_related('user').get(token=token, is_active=True)
        except CLIToken.DoesNotExist:
            raise AuthenticationFailed('Token CLI inválido ou revogado.')

        cli_token.touch()
        return (cli_token.user, cli_token)
