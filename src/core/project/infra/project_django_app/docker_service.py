#Mudei coisa pra krl aqui pq porque o cursor imbecil por algum motivo tava fazendo o servidor rodar um 
#container docker ao invés de usar o dokku

import os
import tempfile
import shutil
import tarfile
import json
import subprocess
from pathlib import Path
from core.project.infra.project_django_app.models import Project

#to repensando essa ideia de transformar todo código em imagem docker
# não sei se vale a pena o esforço
# VUE_DOCKERFILE = '''FROM node:22 AS frontend

# WORKDIR /app

# COPY package.json .

# RUN npm install

# COPY . .

# RUN npm run build

# FROM nginx:alpine

# RUN rm -rf /usr/share/nginx/html/*

# COPY nginx.conf /etc/nginx/nginx.conf

# COPY --from=frontend /app/dist /usr/share/nginx/html

# EXPOSE 80

# CMD ["nginx", "-g", "daemon off;"]
# '''

# VUE_NGINX_CONF = '''worker_processes 1;

# events {
#     worker_connections 1024;
# }

# http {
#     include       mime.types;
#     default_type  application/octet-stream;

#     sendfile        on;
#     keepalive_timeout  65;

#     server {
#         listen       80;
#         server_name  localhost;

#         root   /usr/share/nginx/html;
#         index  index.html;

#         location / {
#             try_files $uri $uri/ /index.html;
#         }


#         gzip on;
#         gzip_types text/plain application/javascript application/x-javascript text/javascript text/xml text/css application/json;
#         gzip_min_length 256;
#     }
# }
# '''

# DJANGO_DOCKERFILE = '''FROM python:3.12-slim

# WORKDIR /app


# RUN apt-get update && apt-get install -y \
#     build-essential \
#     libpq-dev \
#     postgresql-client \
#     && rm -rf /var/lib/apt/lists/*

# ENV PYTHONPATH=/app
# ENV PYTHONUNBUFFERED=1
# ENV PIP_NO_CACHE_DIR=1
# ENV PYTHONFAULTHANDLER=1


# COPY pyproject.toml pdm.lock ./


# RUN pip install --upgrade pip && \
#     pip install pdm && \
#     pdm config python.use_venv false && \
#     pdm install --prod


# COPY . .


# EXPOSE 8000


# CMD ["sh", "-c", \
#     "pdm run python src/manage.py makemigrations && " \
#     "pdm run python src/manage.py migrate && " \
#     "pdm run python src/manage.py populate --all && " \
#     "pdm run python src/manage.py createsuperuser --noinput || true && " \
#     "pdm run python src/manage.py runserver 0.0.0.0:8000"]
# '''


class DockerService:


    def __init__(self, project: Project):
        self.project = project
        self.temp_dir = None

    #função para adicionar novo processo no servidor(nesse caso cmd seria o cli do servidor)
    def run_cmd(self, deploy, timeout=None):
        res = subprocess.run(deploy, capture_output=True, text=True, timeout=timeout)
        return res

    #a ideia desse trecho é pedir a imagem e a tag parar dar fazer deploy a partir de uma imagem no dockerhub
    def full_image(self):
        image = getattr(self.project, 'source_docker', None)
        if not image:
            return None
        return f"{image}"

    #cria um app no dokku usando o nome do project(o nome vai ser unico para evitar possiveis problemas com o nome das apps)
    def create_app(self):
        app = self._run_cmd(['dokku', 'apps:create', f'{self.project.name}'])
        return app

    #aqui ele vai validar que as variveis estejam no formato json({"key"="value"}) coloca em uma array 
    #pra ser declarado para a app

    def set_env_args(self):
        envs = self.project.variables or {}
        if isinstance(envs, str):
            try:
                envs = json.loads(envs)
            except Exception:
                envs = {}
        args = []
        for key, value in (envs.items() if isinstance(envs, dict) else []):
            args.extend(['dokku', 'config:set', f'{self.project.name}', f'{key}={value}'])
        return args

    #isso faz sentido? tipo, como vamos saber que porta vai estar liberado para uso no servidor? 
    # tenho que pensar em uma solução pra isso

    # def _port_mapping(self, detected_tech=None):
        
    #     if self.project.port:
    #         host_port = self.project.port
    #     else:
    #         host_port = None

    #     if detected_tech == 'Vue':
    #         internal = 80
    #     elif detected_tech == 'Django':
    #         internal = 8000
    #     else:
    #         internal = None

    #     if internal and host_port is None:
    #         host_port = internal

    #     if internal:
    #         return ['-p', f'{host_port}:{internal}']
    #     return []

    #faz declara variaveis de ambiente, 

    def deploy_via_image(self):
        image = self.full_image

        if not image:
            return False, 'error: imagem não informada'

        try:

            env = self.env_args()
            deploy = self.run_cmd(['dokku', 'git:from-image', f'{self.project.name}', f'{self.full_image}'], timeout=120)

            set_env = self.run_cmd(env, timeout=120)

            if set_env.returncode != 0:
                 return False, f'Erro ao declarar variaveis de ambiente: {set_env.stderr.strip() or set_env.stdout.strip()}'
            
            run_deploy = self.run_cmd(deploy, timeout=120)

            if run_deploy.returncode != 0:
                 return False, f'Erro ao executar container: {run_deploy.stderr.strip() or run_deploy.stdout.strip()}'
            

            container_id = run_deploy.stdout.strip()
            configs = self.run_cmd(['dokku', 'config', f'{self.project.name}'])

            return True, {'container_id': container_id}, {'variables': configs}

        except Exception as e:
            return False, f'Erro no deploy_via_image: {str(e)}'

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
            cmd += self.env_args()
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
    
        if self.project.source_docker == 'Docker':
            return self.pull_and_run_image()
        elif self.project.source_git == 'Github':
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
