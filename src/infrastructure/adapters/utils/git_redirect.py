# views.py
from django.conf import settings
from django.shortcuts import redirect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from infrastructure.adapters.utils.oauth_state import generate_oauth_state


@api_view(['GET'])
@permission_classes([AllowAny])
def github_login(request):
    client_id = settings.GITHUB_CLIENT_ID
    redirect_uri = settings.GITHUB_REDIRECT_URI
    state = generate_oauth_state()

    url = (
        'https://github.com/login/oauth/authorize'
        f'?client_id={client_id}'
        f'&redirect_uri={redirect_uri}'
        '&scope=repo%20user:email'
        f'&state={state}'
    )
    return redirect(url)
