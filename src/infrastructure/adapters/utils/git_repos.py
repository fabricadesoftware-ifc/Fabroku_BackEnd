import re

import requests
from django.http import JsonResponse
from rest_framework.decorators import api_view


@api_view(['GET'])
def get_git_repos(request):
    git_token = request.user.git_token
    return get_git_repos_func(git_token)


def get_git_repos_func(git_token):
    try:
        repos_res = requests.get(
            'https://api.github.com/user/repos',
            headers={
                'Authorization': f'Bearer {git_token}',
                'Accept': 'application/vnd.github+json',
            },
        )
        if repos_res.status_code != 200:  # noqa: PLR2004
            return JsonResponse(
                {'status': 'error', 'message': 'Failed to obtain repositories from GitHub.'}, status=400
            )  # noqa: E501
        return JsonResponse(repos_res.json(), safe=False)
    except Exception as e:
        return JsonResponse(
            {'status': 'error', 'message': 'An error occurred while fetching repositories.', 'error': str(e)},
            status=500,
        )  # noqa: E501


# owner/repo do GitHub: o valor vai para a URL da API, entao nada fora disso passa.
_GITHUB_FULL_NAME_RE = re.compile(r'^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$')
_BRANCHES_PER_PAGE = 100
_BRANCHES_MAX_PAGES = 10


@api_view(['GET'])
def get_git_branches(request):
    """Lista as branches de um repositorio do usuario (`?repo=owner/nome`)."""
    full_name = request.GET.get('repo', '')
    if not _GITHUB_FULL_NAME_RE.match(full_name):
        return JsonResponse({'status': 'error', 'message': 'Parametro repo deve ser owner/nome.'}, status=400)
    return get_git_branches_func(request.user.git_token, full_name)


def _fetch_branch_names(git_token, full_name: str) -> list[str] | None:
    """Percorre as paginas de branches; None se o GitHub recusar (sem acesso, repo inexistente)."""
    branches: list[str] = []
    for page in range(1, _BRANCHES_MAX_PAGES + 1):
        res = requests.get(
            f'https://api.github.com/repos/{full_name}/branches',
            headers={
                'Authorization': f'Bearer {git_token}',
                'Accept': 'application/vnd.github+json',
            },
            params={'per_page': _BRANCHES_PER_PAGE, 'page': page},
            timeout=15,
        )
        if res.status_code != 200:  # noqa: PLR2004
            return None
        page_items = res.json()
        branches.extend(item['name'] for item in page_items)
        if len(page_items) < _BRANCHES_PER_PAGE:
            break
    return branches


def get_git_branches_func(git_token, full_name: str):
    try:
        branches = _fetch_branch_names(git_token, full_name)
    except Exception as e:
        return JsonResponse(
            {'status': 'error', 'message': 'An error occurred while fetching branches.', 'error': str(e)},
            status=500,
        )
    if branches is None:
        return JsonResponse({'status': 'error', 'message': 'Failed to obtain branches from GitHub.'}, status=400)
    return JsonResponse(branches, safe=False)
