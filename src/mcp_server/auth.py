from channels.db import database_sync_to_async

from identity.models import CLIToken, User


@database_sync_to_async
def resolve_cli_token(token: str) -> User | None:
    cli_token = CLIToken.objects.select_related('user').filter(token=token, is_active=True).first()
    if not cli_token:
        return None
    cli_token.touch()
    return cli_token.user
