from core.adapters.git_mixins import GitRepoMixin
from django.conf import settings


class GitAdapter(GitRepoMixin):
    def __init__(self):
        self.client_id = settings.GITHUB_CLIENT_ID
        self.client_secret = settings.GITHUB_CLIENT_SECRET
