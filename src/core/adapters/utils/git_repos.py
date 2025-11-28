import requests
from django.http import JsonResponse
from rest_framework.decorators import api_view


@api_view(['GET'])
def get_git_repos(request):
    git_token = request.GET.get("git_token")
    return get_git_repos_func(git_token)


def get_git_repos_func(git_token):
    try:
        repos_res = requests.get(
            "https://api.github.com/user/repos",
            headers={
                "Authorization": f"Bearer {git_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        if repos_res.status_code != 200:  # noqa: PLR2004
            return JsonResponse({"status": "error", "message": "Failed to obtain repositories from GitHub."}, status=400)  # noqa: E501
        return JsonResponse(repos_res.json(), safe=False)
    except Exception as e:
        return JsonResponse({"status": "error", "message": "An error occurred while fetching repositories.", "error": str(e)}, status=500)  # noqa: E501
