"""
Endpoint de login OAuth para a CLI.

Fluxo:
1. CLI inicia servidor HTTP local em localhost:<port>
2. CLI abre o browser em /api/auth/cli/login/?port=<port>
3. Backend redireciona para GitHub OAuth usando o MESMO redirect_uri já
   cadastrado no GitHub App, mas com state=cli:<port>
4. GitHub faz callback para /api/auth/github/callback/ (rota existente)
5. O callback detecta state=cli:*, gera CLIToken e redireciona para
   localhost:<port>/callback?token=<token>
"""

from django.conf import settings
from django.shortcuts import redirect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny


@api_view(['GET'])
@permission_classes([AllowAny])
def cli_login(request):
    """
    Inicia o fluxo OAuth para a CLI.
    Query param: port (porta do servidor local da CLI)

    Usa o MESMO redirect_uri já cadastrado no GitHub OAuth App,
    diferenciando CLI vs Web pelo parâmetro state=cli:<port>.
    """
    port = request.GET.get('port', '9876')
    client_id = settings.GITHUB_CLIENT_ID
    redirect_uri = settings.GITHUB_REDIRECT_URI  # Mesmo URI do login web

    url = (
        'https://github.com/login/oauth/authorize'
        f'?client_id={client_id}'
        f'&redirect_uri={redirect_uri}'
        '&scope=repo%20user:email'
        f'&state=cli:{port}'
    )
    return redirect(url)
