# views.py
import requests
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from rest_framework.decorators import api_view
from rest_framework_simplejwt.tokens import RefreshToken

from core.auth_user.models import User


@api_view(['GET'])
def github_callback(request):
    try:
        code = request.GET.get("code")

        token_res = requests.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
            },
        )
        if token_res.status_code != 200:  # noqa: PLR2004
            return JsonResponse({"status": "error", "message": "Failed to obtain access token from GitHub."}, status=400)  # noqa: E501

        user_git = requests.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token_res.json().get('access_token')}",
                "Accept": "application/vnd.github+json",
            },
        )

        if user_git.status_code != 200:  # noqa: PLR2004
            return JsonResponse({"status": "error", "message": "Failed to obtain user info from GitHub."}, status=400)  # noqa: E501

        user_git_json = user_git.json()
        user_git_email = requests.get(
            "https://api.github.com/user/emails",
            headers={
                "Authorization": f"Bearer {token_res.json().get('access_token')}",
                "Accept": "application/vnd.github+json",
            },
        )

        if user_git_email.status_code != 200:  # noqa: PLR2004
            return JsonResponse({"status": "error", "message": "Failed to obtain user email from GitHub."}, status=400)  # noqa: E501

        token_json = token_res.json()
        access_token = token_json.get("access_token")

        User.objects.update_or_create(
            id=user_git_json.get("id"),
            defaults={
                "name": user_git_json.get("login"),
                "email": user_git_email.json()[0].get("email"),
                "git_token": access_token,
                "avatar_url": user_git_json.get("avatar_url"),
            },
        )
        user = User.objects.get(id=user_git_json.get("id"))
        refresh = RefreshToken.for_user(user)
        jwt_access_token = str(refresh.access_token)
        return redirect(f"{settings.FRONTEND_URL}/login/success#token={jwt_access_token}")
    except Exception as e:
        return JsonResponse({"status": "error", "message": 'Token invalido ou expirado', "error": str(e)})
