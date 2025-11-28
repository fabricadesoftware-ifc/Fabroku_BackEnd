# views.py
from django.shortcuts import redirect
from django.conf import settings

def github_login(request):
    client_id = settings.GITHUB_CLIENT_ID
    redirect_uri = settings.GITHUB_REDIRECT_URI

    url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        "&scope=repo"
    )
    return redirect(url)
