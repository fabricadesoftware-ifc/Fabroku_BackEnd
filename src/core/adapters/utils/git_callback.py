# views.py
import requests
from django.conf import settings
from django.http import JsonResponse
from rest_framework.decorators import api_view


@api_view(['GET'])
def github_callback(request):
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

    token_json = token_res.json()
    access_token = token_json.get("access_token")

    user = request.user
    user.github_token = access_token
    user.save()

    return JsonResponse({"status": "ok", "token": access_token})
