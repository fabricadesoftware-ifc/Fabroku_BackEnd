"""
Autenticação customizada via cookies HTTP-only e CLIToken.
"""

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken


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

        from core.auth_user.models import CLIToken

        try:
            cli_token = CLIToken.objects.select_related('user').get(token=token, is_active=True)
        except CLIToken.DoesNotExist:
            raise AuthenticationFailed('Token CLI inválido ou revogado.')

        cli_token.touch()
        return (cli_token.user, cli_token)
