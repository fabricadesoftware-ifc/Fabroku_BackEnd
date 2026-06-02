from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser

from core.auth_user.models import CLIToken


def _authorization_header(scope) -> str:
    for key, value in scope.get('headers', []):
        if key == b'authorization':
            return value.decode('utf-8', errors='ignore')
    return ''


@database_sync_to_async
def _authenticate_cli_token(token: str):
    cli_token = CLIToken.objects.select_related('user').filter(token=token, is_active=True).first()
    if not cli_token:
        return AnonymousUser(), 'Token CLI invalido ou revogado.'

    cli_token.touch()
    return cli_token.user, None


class CLITokenAuthMiddleware:
    """Autentica WebSockets da CLI usando o mesmo header REST: Authorization: CLI <token>."""

    keyword = 'CLI'

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        auth_header = _authorization_header(scope)

        if not auth_header.startswith(f'{self.keyword} '):
            scope['user'] = AnonymousUser()
            scope['cli_auth_error'] = 'Header Authorization CLI ausente.'
            return await self.app(scope, receive, send)

        token = auth_header[len(self.keyword) + 1 :].strip()
        if not token:
            scope['user'] = AnonymousUser()
            scope['cli_auth_error'] = 'Token CLI vazio.'
            return await self.app(scope, receive, send)

        user, error = await _authenticate_cli_token(token)
        scope['user'] = user
        scope['cli_auth_error'] = error
        return await self.app(scope, receive, send)
