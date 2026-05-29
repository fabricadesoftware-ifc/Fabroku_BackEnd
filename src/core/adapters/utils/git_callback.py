from urllib.parse import urlencode

import requests
from django.conf import settings
from django.shortcuts import redirect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken

from core.adapters.utils.git_email import verify_git_email
from core.auth_user.models import CLIToken, User


def set_auth_cookies(response, access_token: str, refresh_token: str):
    """Define os cookies de autenticação na resposta."""
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=access_token,
        max_age=int(settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds()),
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=settings.AUTH_COOKIE_HTTP_ONLY,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
    )

    response.set_cookie(
        key=settings.AUTH_COOKIE_REFRESH_NAME,
        value=refresh_token,
        max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()),
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=settings.AUTH_COOKIE_HTTP_ONLY,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
    )

    return response


@api_view(['GET'])
@permission_classes([AllowAny])
def github_callback(request):
    """Callback OAuth do GitHub — funciona tanto para Web quanto para CLI."""
    state = request.GET.get('state', '')
    is_cli = state.startswith('cli:')
    cli_port = state.split(':', 1)[1] if is_cli else None

    def _error_redirect(params: dict):
        """Redireciona erro para CLI (localhost) ou Frontend."""
        qs = urlencode(params)
        if is_cli:
            return redirect(f'http://localhost:{cli_port}/callback?{qs}')
        return redirect(f'{settings.FRONTEND_URL}/callback?{qs}')

    try:
        code = request.GET.get('code')

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
            return _error_redirect({'error': 'auth_failed', 'message': 'Falha ao obter token de acesso do GitHub.'})

        user_git = requests.get(
            'https://api.github.com/user',
            headers={
                'Authorization': f'Bearer {token_res.json().get("access_token")}',
                'Accept': 'application/vnd.github+json',
            },
        )

        if user_git.status_code != 200:  # noqa: PLR2004
            return _error_redirect({
                'error': 'user_info_failed',
                'message': 'Falha ao obter informações do usuário do GitHub.',
            })

        user_git_json = user_git.json()
        user_git_email = requests.get(
            'https://api.github.com/user/emails',
            headers={
                'Authorization': f'Bearer {token_res.json().get("access_token")}',
                'Accept': 'application/vnd.github+json',
            },
        )

        if user_git_email.status_code != 200:  # noqa: PLR2004
            return _error_redirect({'error': 'email_failed', 'message': 'Falha ao obter email do usuário do GitHub.'})

        approved_email = verify_git_email(user_git_email.json())
        if approved_email is None:
            return _error_redirect({'error': 'invalid_email', 'message': settings.AUTH_EMAIL_REJECTION_MESSAGE})

        token_json = token_res.json()
        access_token = token_json.get('access_token')

        User.objects.update_or_create(
            id=user_git_json.get('id'),
            defaults={
                'name': user_git_json.get('login'),
                'email': approved_email,
                'git_token': access_token,
                'avatar_url': user_git_json.get('avatar_url'),
            },
        )
        user = User.objects.get(id=user_git_json.get('id'))

        if not user.is_active:
            return _error_redirect({
                'error': 'user_disabled',
                'message': 'Sua conta foi desabilitada pelo administrador. Entre em contato com o suporte.',
            })

        from django.utils import timezone

        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        if is_cli:
            cli_token = CLIToken.objects.create(user=user, name='CLI Login')
            return redirect(f'http://localhost:{cli_port}/callback?token={cli_token.token}&user={user.name}')

        refresh = RefreshToken.for_user(user)
        response = redirect(f'{settings.FRONTEND_URL}/callback')
        set_auth_cookies(response, str(refresh.access_token), str(refresh))

        return response
    except Exception as e:
        return _error_redirect({'error': 'unexpected_error', 'message': f'Erro inesperado: {str(e)}'})
