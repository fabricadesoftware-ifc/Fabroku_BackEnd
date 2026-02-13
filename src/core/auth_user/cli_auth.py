"""
Endpoint de callback OAuth para autenticação da CLI.

Fluxo:
1. CLI inicia servidor local em localhost:<port>
2. CLI abre o browser em /api/auth/cli/login/?port=<port>
3. Backend redireciona para GitHub OAuth com state=cli:<port>
4. GitHub faz callback normal
5. /api/auth/cli/callback/ gera CLIToken e redireciona para localhost:<port>/callback?token=<token>
"""

from urllib.parse import urlencode

import requests
from django.conf import settings
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from core.adapters.utils.git_email import verify_git_email
from core.auth_user.models import CLIToken, User


@api_view(['GET'])
@permission_classes([AllowAny])
def cli_login(request):
    """
    Inicia o fluxo OAuth para a CLI.
    Query param: port (porta do servidor local da CLI)
    """
    port = request.GET.get('port', '9876')
    client_id = settings.GITHUB_CLIENT_ID
    # Usa um redirect_uri específico para CLI
    redirect_uri = f'{settings.BACKEND_URL}/api/auth/cli/callback/'

    url = (
        'https://github.com/login/oauth/authorize'
        f'?client_id={client_id}'
        f'&redirect_uri={redirect_uri}'
        f'&scope=repo%20user:email'
        f'&state=cli:{port}'
    )
    return redirect(url)


@api_view(['GET'])
@permission_classes([AllowAny])
def cli_callback(request):
    """
    Callback OAuth para a CLI.
    Gera um CLIToken e redireciona para o servidor local da CLI.
    """
    try:
        code = request.GET.get('code')
        state = request.GET.get('state', '')

        # Extrai a porta do state
        if not state.startswith('cli:'):
            return redirect(f'{settings.FRONTEND_URL}/callback?error=invalid_state')

        port = state.split(':', 1)[1]

        # Troca code por access_token no GitHub
        token_res = requests.post(
            'https://github.com/login/oauth/access_token',
            headers={'Accept': 'application/json'},
            data={
                'client_id': settings.GITHUB_CLIENT_ID,
                'client_secret': settings.GITHUB_CLIENT_SECRET,
                'code': code,
            },
        )
        if token_res.status_code != 200:  # noqa: PLR2004
            error_params = urlencode({'error': 'auth_failed'})
            return redirect(f'http://localhost:{port}/callback?{error_params}')

        git_access_token = token_res.json().get('access_token')
        if not git_access_token:
            error_params = urlencode({'error': 'no_token'})
            return redirect(f'http://localhost:{port}/callback?{error_params}')

        # Busca dados do usuário
        user_res = requests.get(
            'https://api.github.com/user',
            headers={
                'Authorization': f'Bearer {git_access_token}',
                'Accept': 'application/vnd.github+json',
            },
        )
        if user_res.status_code != 200:  # noqa: PLR2004
            error_params = urlencode({'error': 'user_info_failed'})
            return redirect(f'http://localhost:{port}/callback?{error_params}')

        user_json = user_res.json()

        # Busca emails
        email_res = requests.get(
            'https://api.github.com/user/emails',
            headers={
                'Authorization': f'Bearer {git_access_token}',
                'Accept': 'application/vnd.github+json',
            },
        )
        if email_res.status_code != 200:  # noqa: PLR2004
            error_params = urlencode({'error': 'email_failed'})
            return redirect(f'http://localhost:{port}/callback?{error_params}')

        # Verifica email IFC
        if verify_git_email(email_res.json()) is None:
            error_params = urlencode({'error': 'invalid_email', 'message': 'Email não autorizado.'})
            return redirect(f'http://localhost:{port}/callback?{error_params}')

        # Cria/atualiza usuário
        User.objects.update_or_create(
            id=user_json.get('id'),
            defaults={
                'name': user_json.get('login'),
                'email': email_res.json()[0].get('email'),
                'git_token': git_access_token,
                'avatar_url': user_json.get('avatar_url'),
            },
        )
        user = User.objects.get(id=user_json.get('id'))
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        # Gera CLIToken
        cli_token = CLIToken.objects.create(user=user, name='CLI Login')

        # Redireciona para o servidor local da CLI com o token
        return redirect(f'http://localhost:{port}/callback?token={cli_token.token}&user={user.name}')

    except Exception as e:
        # Tenta redirecionar para a CLI com erro
        port = request.GET.get('state', 'cli:9876').split(':', 1)[-1]
        error_params = urlencode({'error': 'unexpected_error', 'message': str(e)})
        return redirect(f'http://localhost:{port}/callback?{error_params}')
