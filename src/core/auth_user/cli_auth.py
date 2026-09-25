"""
Endpoint de login OAuth para a CLI.

Fluxo:
1. CLI inicia servidor HTTP local em localhost:<port>
2. CLI abre o browser em /api/auth/cli/login/?port=<port>
3. Backend valida a porta, gera um state opaco de uso unico vinculado a ela
   (ver infrastructure/adapters/utils/oauth_state.py) e redireciona para o
   GitHub OAuth usando o MESMO redirect_uri ja cadastrado no GitHub App
4. GitHub faz callback para /api/auth/github/callback/ (rota existente)
5. O callback resolve o state, gera CLIToken e redireciona para
   localhost:<port>/callback?token=<token>
"""

from django.conf import settings
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from infrastructure.adapters.utils.oauth_state import generate_oauth_state, validate_cli_port


@api_view(['GET'])
@permission_classes([AllowAny])
def cli_login(request):
    """
    Inicia o fluxo OAuth para a CLI.
    Query param: port (porta do servidor local da CLI)
    """
    port = validate_cli_port(request.GET.get('port'))
    if port is None:
        return Response(
            {
                'error': 'invalid_port',
                'message': 'Parametro port deve ser um numero inteiro entre 1024 e 65535.',
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    state = generate_oauth_state(cli_port=port)
    client_id = settings.GITHUB_CLIENT_ID

    # NÃO envia redirect_uri — GitHub usa a URL padrão cadastrada na OAuth App.
    url = f'https://github.com/login/oauth/authorize?client_id={client_id}&scope=repo%20user:email&state={state}'
    return redirect(url)
