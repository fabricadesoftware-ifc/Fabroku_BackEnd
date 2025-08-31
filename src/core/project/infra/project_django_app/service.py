import json
import subprocess
import shlex
from core.project.infra.project_django_app.models import Project

class DockerService:

    def __init__(self, project: Project):
        self.project = project

    def run_cmd(self, cmd, timeout=None):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            return subprocess.CompletedProcess(
                args=e.cmd,
                returncode=1,
                stdout='',
                stderr=f"TimeoutExpired após {e.timeout} segundos"
            )

    def dokku_cmd(self, *args):
        return self.run_cmd(['dokku', *args])

    def image(self):
        return getattr(self.project, 'source_docker', None)

    def repo_git(self):
        return getattr(self.project, 'source_git', None)

    def create_app(self):
        return self.dokku_cmd('apps:create', self.project.name)

    def set_env_args(self):
        envs = self.project.variables or {}
        if isinstance(envs, str):
            try:
                envs = json.loads(envs)
            except Exception:
                envs = {}
        args = []
        for key, value in envs.items():
            args.extend(['dokku', 'config:set', self.project.name, f'{key}={shlex.quote(str(value))}'])
        return args

    def deploy_via_image(self):
        img = self.image()
        if not img:
            return False, 'error: imagem não informada'
        set_env = self.run_cmd(self.set_env_args(), timeout=120)
        if set_env.returncode != 0:
            return False, f'Erro ao declarar variaveis de ambiente: {set_env.stderr.strip()}'
        run_deploy = self.dokku_cmd('git:from-image', self.project.name, img)
        if run_deploy.returncode != 0:
            return False, f'Erro ao executar container: {run_deploy.stderr.strip()}'
        container_id = run_deploy.stdout.strip()
        configs = self.dokku_cmd('config', self.project.name)
        return True, {'container_id': container_id}, {'variables': configs}

    def deploy_via_git(self):
        repo = self.repo_git()
        if not repo:
            return False, 'error: repositório não informado'
        add_remote = self.run_cmd(['git', 'remote', 'add', 'dokku', f'dokku@app2.fabricadesoftware.ifc.edu.br:{self.project.name}'])
        if add_remote.returncode != 0:
            return False, f"Erro ao adicionar remoto: {add_remote.stderr.strip()}"
        set_env = self.run_cmd(self.set_env_args(), timeout=120)
        if set_env.returncode != 0:
            return False, f'Erro ao declarar variaveis de ambiente: {set_env.stderr.strip()}'
        push = self.run_cmd(['git', 'push', 'dokku', 'main'], timeout=600)
        if push.returncode != 0:
            return False, f'Erro ao dar push pro Dokku: {push.stderr.strip()}'
        return True, {'result': push.stdout.strip()}

    def deploy(self):
        if self.project.source_docker == 'Docker':
            return self.deploy_via_image()
        elif self.project.source_git == 'Github':
            return self.deploy_via_git()
        return False, 'Tipo de fonte desconhecido'

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
