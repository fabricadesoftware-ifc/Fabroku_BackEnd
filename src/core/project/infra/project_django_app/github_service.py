import os
import tempfile
import subprocess
import shutil
from pathlib import Path
from github import Github
from django.conf import settings
from core.project.infra.project_django_app.models import Projeto
# - Se necessário, o token global pode ser configurado em `settings.GITHUB_TOKEN`. Quando for repo privado o github irá procurar o token nesse lugar

class GitHubService:

    def __init__(self, projeto: Projeto):
        self.projeto = projeto
        self.temp_dir = None

    def _get_clone_url(self):
        url = self.projeto.github_repo
        if not url:
            return None
        token = getattr(settings, 'GITHUB_TOKEN', None)
        if token and url.startswith('https://'):
            return url.replace('https://', f'https://{token}@')
        return url

    def clone_repository(self):

        repo_url = self.projeto.github_repo
        if not repo_url:
            return False, 'URL do repositório não configurada'

        try:
            self.temp_dir = tempfile.mkdtemp()
            clone_url = self._get_clone_url()
            branch = self.projeto.github_branch or 'main'

            cmd = ['git', 'clone', '--branch', branch, '--depth', '1', clone_url, self.temp_dir]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if res.returncode != 0:
                raise Exception(res.stderr.strip() or res.stdout.strip())

            return True, Path(self.temp_dir)
        except Exception as e:
            if self.temp_dir and os.path.exists(self.temp_dir):
                try:
                    shutil.rmtree(self.temp_dir)
                except Exception:
                    pass
            self.temp_dir = None
            return False, f'Erro ao clonar repositório: {str(e)}'

    def cleanup(self):
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception:
                pass
            self.temp_dir = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()