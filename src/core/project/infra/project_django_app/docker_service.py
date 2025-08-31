import os
import tempfile
import shutil
import tarfile
import json
import subprocess
from pathlib import Path
from core.project.infra.project_django_app.models import Projeto


VUE_DOCKERFILE = '''FROM node:22 AS frontend

WORKDIR /app

COPY package.json .

RUN npm install

COPY . .

RUN npm run build

FROM nginx:alpine

RUN rm -rf /usr/share/nginx/html/*

COPY nginx.conf /etc/nginx/nginx.conf

COPY --from=frontend /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
'''

VUE_NGINX_CONF = '''worker_processes 1;

events {
    worker_connections 1024;
}

http {
    include       mime.types;
    default_type  application/octet-stream;

    sendfile        on;
    keepalive_timeout  65;

    server {
        listen       80;
        server_name  localhost;

        root   /usr/share/nginx/html;
        index  index.html;

        location / {
            try_files $uri $uri/ /index.html;
        }


        gzip on;
        gzip_types text/plain application/javascript application/x-javascript text/javascript text/xml text/css application/json;
        gzip_min_length 256;
    }
}
'''

DJANGO_DOCKERFILE = '''FROM python:3.12-slim

WORKDIR /app


RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONFAULTHANDLER=1


COPY pyproject.toml pdm.lock ./


RUN pip install --upgrade pip && \
    pip install pdm && \
    pdm config python.use_venv false && \
    pdm install --prod


COPY . .


EXPOSE 8000


CMD ["sh", "-c", \
    "pdm run python src/manage.py makemigrations && " \
    "pdm run python src/manage.py migrate && " \
    "pdm run python src/manage.py populate --all && " \
    "pdm run python src/manage.py createsuperuser --noinput || true && " \
    "pdm run python src/manage.py runserver 0.0.0.0:8000"]
'''


class DockerService:

    def __init__(self, projeto: Projeto):
        self.projeto = projeto
        self.temp_dir = None

    def _full_image(self):
        repo = getattr(self.projeto, 'image_repo', None)
        tag = getattr(self.projeto, 'image_tag', None) or 'latest'
        if not repo:
            return None
        return f"{repo}:{tag}"

    def _env_args(self):
        envs = self.projeto.variables or {}
        if isinstance(envs, str):
            try:
                envs = json.loads(envs)
            except Exception:
                envs = {}
        args = []
        for k, v in (envs.items() if isinstance(envs, dict) else []):
            args.extend(['-e', f'{k}={v}'])
        return args

    def _port_mapping(self, detected_tech=None):
        # determina porta interna e porta host para mapear
        if self.projeto.port:
            host_port = self.projeto.port
        else:
            host_port = None

        if detected_tech == 'Vue':
            internal = 80
        elif detected_tech == 'Django':
            internal = 8000
        else:
            internal = None

        if internal and host_port is None:
            host_port = internal

        if internal:
            return ['-p', f'{host_port}:{internal}']
        return []

    def _run_cmd(self, cmd, timeout=None):
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res

    def pull_and_run_image(self):

        image = self._full_image()
        if not image:
            return False, 'Imagem ou tag não configuradas no projeto'

        try:

            pull = self._run_cmd(['docker', 'pull', image], timeout=600)
            if pull.returncode != 0:
                return False, f'Erro ao puxar imagem: {pull.stderr.strip()}'


            cmd = ['docker', 'run', '-d']
            # porta padrão não mapeada porque não sabemos a tech — se porta personalizada estiver setada, mapeia sem saber a interna
            if self.projeto.port:
                # apresenta um mapeamento simples: host_port:host_port (não ideal, mas atende caso usuário queira expor)
                cmd += ['-p', f'{self.projeto.port}:{self.projeto.port}']

            cmd += self._env_args()
            cmd.append(image)

            run = self._run_cmd(cmd, timeout=60)
            if run.returncode != 0:
                return False, f'Erro ao executar container: {run.stderr.strip() or run.stdout.strip()}'

            container_id = run.stdout.strip()
            return True, {'container_id': container_id}

        except Exception as e:
            return False, f'Erro no pull_and_run_image: {str(e)}'

    def build_from_source_and_run(self, source_path: Path, detected_tech: str):
        
        image = self._full_image()
        if not image:
            return False, 'Imagem e tag devem estar configuradas para build/push locais'

        tmp_dir = tempfile.mkdtemp()
        try:
            
            shutil.copytree(source_path, tmp_dir, dirs_exist_ok=True)

            
            if detected_tech == 'Vue':
                (Path(tmp_dir) / 'Dockerfile').write_text(VUE_DOCKERFILE)
                (Path(tmp_dir) / 'nginx.conf').write_text(VUE_NGINX_CONF)
            elif detected_tech == 'Django':
                (Path(tmp_dir) / 'Dockerfile').write_text(DJANGO_DOCKERFILE)
            else:
                
                return False, 'Tecnologia desconhecida — não foi possível gerar Dockerfile'

            
            build = self._run_cmd(['docker', 'build', '-t', image, tmp_dir], timeout=1800)
            if build.returncode != 0:
                return False, f'Erro ao buildar imagem: {build.stderr.strip()}'

            
            cmd = ['docker', 'run', '-d']
            cmd += self._port_mapping(detected_tech)
            cmd += self._env_args()
            cmd.append(image)

            run = self._run_cmd(cmd, timeout=60)
            if run.returncode != 0:
                return False, f'Erro ao executar container: {run.stderr.strip() or run.stdout.strip()}'

            container_id = run.stdout.strip()
            return True, {'container_id': container_id}

        except Exception as e:
            return False, f'Erro no build_from_source_and_run: {str(e)}'
        finally:
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass

    def deploy(self, source_path: Path = None, detected_tech: str = None):
    
        if self.projeto.tipo_fonte == 'Docker':
            return self.pull_and_run_image()
        elif self.projeto.tipo_fonte == 'Github':
            if not source_path or not detected_tech:
                return False, 'source_path e detected_tech são necessários para deploy a partir do GitHub'
            return self.build_from_source_and_run(source_path, detected_tech)
        else:
            return False, 'Tipo de fonte desconhecido'

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
