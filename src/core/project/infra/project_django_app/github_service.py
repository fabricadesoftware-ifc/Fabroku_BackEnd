import os
import tempfile
import subprocess
import shutil
from pathlib import Path
from github import Github
from django.conf import settings
from core.project.infra.project_django_app.models import Projeto  

class GitHubService:

    def __init__(self, projeto: Projeto):
        self.projeto = projeto
        self.temp_dir = None


        if self.projeto.github_token:
            return Github(self.projeto.github_token)
        else:
            token = getattr(settings, 'GITHUB_TOKEN', None)
            return Github(token) if token else Github()

    def _extract_repo_info(self, repo_url):
        repo_url = repo_url.replace('.git', '')
        if 'github.com' in repo_url:
            parts = repo_url.split('github.com/')
            if len(parts) > 1:
                owner_repo = parts[1].strip('/')
                return owner_repo
        return None

    def validate_repository(self):
        try:
            owner_repo = self._extract_repo_info(self.projeto.github_repo)
            if not owner_repo:
                return False, "URL do repositório inválida"

            github = self._get_github_client()
            repo = github.get_repo(owner_repo)

            try:
                repo.get_branch(self.projeto.github_branch)
            except Exception:
                return False, f"Branch '{self.projeto.github_branch}' não encontrada"

            return True, "Repositório válido"

        except Exception as e:
            return False, f"Erro ao validar repositório: {str(e)}"

    def clone_repository(self):
        try:
            self.temp_dir = tempfile.mkdtemp()
            clone_url = self.projeto.github_repo

            if self.projeto.github_token:
                clone_url = clone_url.replace(
                    'https://', f'https://{self.projeto.github_token}@')

            cmd = [
                'git', 'clone',
                '--branch', self.projeto.github_branch,
                '--depth', '1',
                clone_url,
                self.temp_dir
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                raise Exception(f"Erro ao clonar repositório: {result.stderr}")

            return True, "Repositório clonado com sucesso"

        except Exception as e:
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
            return False, f"Erro ao clonar repositório: {str(e)}"

    def detect_technology(self):
        if not self.temp_dir or not os.path.exists(self.temp_dir):
            return None

        files_to_check = [
            ('package.json', 'Vue.js'),
            ('requirements.txt', 'Django'),
            ('Pipfile', 'Python'),
            ('pyproject.toml', 'Python'),
        ]

        for filename, tech in files_to_check:
            if os.path.exists(os.path.join(self.temp_dir, filename)):
                return tech

        if os.path.exists(os.path.join(self.temp_dir, 'manage.py')):
            return 'Django'
        elif os.path.exists(os.path.join(self.temp_dir, 'index.html')):
            return 'HTML/CSS/JS'

        return 'Desconhecido'

    def get_default_commands(self, technology):
        commands = {
            'Vue.js': {
                'build': 'npm install && npm run build',
                'start': 'npm run dev',
                'port': 5173
            },
            'Django': {
                'build': 'pip install -r requirements.txt && python manage.py collectstatic --noinput',
                'start': 'python manage.py runserver 0.0.0.0:8000',
                'port': 8000
            },
            'HTML/CSS/JS': {
                'build': '',
                'start': 'python -m http.server 8000',
                'port': 8000
            }
        }

        return commands.get(technology, {
            'build': 'npm install',
            'start': 'npm run dev',
            'port': 3000
        })

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
