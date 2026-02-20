import logging

from celery.result import AsyncResult
from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from core.adapters import GitHubAdapter
from core.apps.mixins import AppMixin
from core.apps.mixins.apps.run_command import ALLOWED_COMMANDS, ALLOWED_PREFIXES, is_command_allowed

from .models import App, Service
from .serializers import AppSerializer, ServiceSerializer

logger = logging.getLogger(__name__)


@extend_schema(tags=['apps'])
class AppViewSet(ModelViewSet):
    queryset = App.objects.all()
    serializer_class = AppSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['project', 'status', 'name', 'branch']

    def get_queryset(self):
        """Superusers veem todos os apps, usuários normais só os seus."""
        if self.request.user.is_superuser:
            return App.objects.all()
        return App.objects.filter(project__users=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Override destroy para lançar task de deleção no Dokku."""
        instance = self.get_object()

        # Atualiza status para indicar que está deletando
        instance.status = 'DELETING'
        instance.save(update_fields=['status'])

        # Lança a task de deleção
        task_result = AppMixin.delete_app.delay(app_id=instance.id)  # type: ignore

        return Response(
            {
                'status': 'DELETING',
                'message': f'Deletando aplicação {instance.name}...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Inicia uma aplicação parada."""
        app = self.get_object()

        if not app.name_dokku:
            return Response(
                {'error': 'App não tem name_dokku configurado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        app.status = 'STARTING'
        app.save(update_fields=['status'])

        task_result = AppMixin.manage_app.delay(app_id=app.id, action='start')  # type: ignore

        return Response(
            {
                'status': 'STARTING',
                'message': f'Iniciando aplicação {app.name}...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """Para uma aplicação em execução."""
        app = self.get_object()

        if not app.name_dokku:
            return Response(
                {'error': 'App não tem name_dokku configurado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        app.status = 'STOPPING'
        app.save(update_fields=['status'])

        task_result = AppMixin.manage_app.delay(app_id=app.id, action='stop')  # type: ignore

        return Response(
            {
                'status': 'STOPPING',
                'message': f'Parando aplicação {app.name}...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def restart(self, request, pk=None):
        """Reinicia uma aplicação."""
        app = self.get_object()

        if not app.name_dokku:
            return Response(
                {'error': 'App não tem name_dokku configurado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        app.status = 'RESTARTING'
        app.save(update_fields=['status'])

        task_result = AppMixin.manage_app.delay(app_id=app.id, action='restart')  # type: ignore

        return Response(
            {
                'status': 'RESTARTING',
                'message': f'Reiniciando aplicação {app.name}...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def redeploy(self, request, pk=None):
        """Dispara um redeploy manual da aplicação (re-sync com o repositório Git)."""
        app = self.get_object()

        if not app.name_dokku:
            return Response(
                {'error': 'App não tem name_dokku configurado. Aguarde o deploy inicial completar.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if app.status in ('DEPLOYING', 'DELETING', 'STARTING'):
            return Response(
                {'error': f'App está em estado {app.status}. Aguarde a operação atual terminar.'},
                status=status.HTTP_409_CONFLICT,
            )

        app.status = 'DEPLOYING'
        app.save(update_fields=['status'])

        commit = request.data.get('commit')
        task_result = AppMixin.redeploy_app.delay(app_id=app.id, commit=commit)  # type: ignore

        return Response(
            {
                'status': 'DEPLOYING',
                'message': f'Iniciando redeploy de {app.name}...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['get'])
    def get_app_status(self, request, pk=None):
        app = self.get_object()

        if not app.task_id:
            return Response({'state': 'UNKNOWN', 'status': 'Nenhuma task vinculada.'})

        task_result = AsyncResult(app.task_id)

        response_data = {
            'task_id': app.task_id,
            'state': task_result.state,  # PENDING, PROGRESS, SUCCESS, FAILURE
        }

        if task_result.state == 'PROGRESS':
            response_data.update(task_result.info)

        elif task_result.state == 'SUCCESS':
            response_data['status'] = 'Aplicação criada com sucesso!'
            response_data['current'] = 100

        elif task_result.state == 'FAILURE':
            # Retorna erro persistido no App
            response_data['status'] = app.error_details or str(task_result.result)
            if app.error_type:
                response_data['error_type'] = app.error_type
            if app.error_details:
                response_data['error_details'] = app.error_details
            if app.help_url:
                response_data['help_url'] = app.help_url
            # Compatibilidade: deploy_keys_disabled legacy
            if app.error_type == 'DeployKeysDisabled':
                response_data['deploy_keys_disabled'] = True

        return Response(response_data)

    @action(detail=True, methods=['post'])
    def run_command(self, request, pk=None):
        """Executa um comando dentro do container do app (ex: migrate, collectstatic)."""
        app = self.get_object()

        if not app.name_dokku:
            return Response(
                {'error': 'App não tem name_dokku configurado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        command = request.data.get('command', '').strip()
        if not command:
            return Response(
                {'error': 'O campo "command" é obrigatório'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not is_command_allowed(command):
            return Response(
                {
                    'error': f'Comando não permitido: {command}',
                    'allowed_commands': sorted(ALLOWED_COMMANDS),
                    'allowed_prefixes': list(ALLOWED_PREFIXES),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        task_result = AppMixin.run_command.delay(app_id=app.id, command=command)  # type: ignore

        app.task_id = task_result.id
        app.save(update_fields=['task_id'])

        return Response(
            {
                'status': 'RUNNING',
                'message': f'Executando: {command}',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['get'])
    def allowed_commands(self, request, pk=None):
        """Lista os comandos permitidos para execução."""
        return Response({
            'commands': sorted(ALLOWED_COMMANDS),
            'prefixes': list(ALLOWED_PREFIXES),
        })

    @action(detail=True, methods=['post'])
    def setup_webhook(self, request, pk=None):
        """Verifica e (re)cria o webhook do GitHub para deploy automático."""
        app = self.get_object()
        user = request.user

        if not user.git_token:
            return Response(
                {'error': 'Você precisa estar autenticado com o GitHub (git_token ausente).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not app.git:
            return Response(
                {'error': 'App não tem URL do repositório Git configurada.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        repo_name = app.git.rsplit('.com/', maxsplit=1)[-1].replace('.git', '')
        github_adapter = GitHubAdapter()

        try:
            result = github_adapter.create_webhook(
                repo_name=repo_name,
                app_id=app.id,
                user_id=user.id,
            )
            webhook_url = f'{settings.BACKEND_URL}/api/webhooks/github/{app.id}/'
            logger.info('Webhook setup para app %s: %s (URL: %s)', app.name, result, webhook_url)

            return Response({
                'status': result.get('status', 'unknown'),
                'webhook_url': webhook_url,
                'backend_url': settings.BACKEND_URL,
                'repo': repo_name,
                'hook_id': result.get('hook_id'),
            })
        except Exception as e:
            logger.exception('Erro ao configurar webhook para app %s', app.name)
            return Response(
                {'error': f'Erro ao configurar webhook: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['get'])
    def diagnose_webhook(self, request, pk=None):
        """Diagnóstico completo do webhook e commit status de um app."""
        app = self.get_object()
        user = request.user

        diag = {
            'app': {
                'id': app.id,
                'name': app.name,
                'git_url': app.git,
                'branch': app.branch,
                'name_dokku': app.name_dokku,
            },
            'backend_url': settings.BACKEND_URL,
            'webhook_url': f'{settings.BACKEND_URL}/api/webhooks/github/{app.id}/',
            'checks': {},
        }

        # 1. Verificar BACKEND_URL
        backend_url = settings.BACKEND_URL
        is_localhost = 'localhost' in backend_url or '127.0.0.1' in backend_url
        diag['checks']['backend_url_public'] = {
            'ok': not is_localhost,
            'value': backend_url,
            'message': 'BACKEND_URL aponta para localhost! GitHub não consegue entregar webhooks.'
            if is_localhost
            else 'BACKEND_URL parece público.',
        }

        # 2. Verificar git_token do usuário
        has_token = bool(user.git_token)
        diag['checks']['user_git_token'] = {
            'ok': has_token,
            'message': 'Token GitHub disponível.' if has_token else 'Seu usuário não tem git_token salvo.',
        }

        # 3. Verificar git_token de algum usuário do projeto
        project_user_with_token = app.project.users.exclude(git_token__isnull=True).exclude(git_token='').first()
        diag['checks']['project_git_token'] = {
            'ok': project_user_with_token is not None,
            'user': project_user_with_token.username if project_user_with_token else None,
            'message': f'Token disponível via {project_user_with_token.username}.'
            if project_user_with_token
            else 'Nenhum usuário do projeto tem git_token! Commit status não funciona.',
        }

        # 4. Verificar git_url parseable
        import re

        git_url = app.git or ''
        match_https = re.match(r'https://github\.com/([^/]+/[^/]+?)(?:\.git)?$', git_url)
        match_ssh = re.match(r'git@github\.com:([^/]+/[^/]+?)(?:\.git)?$', git_url)
        repo_name = (match_https or match_ssh).group(1) if (match_https or match_ssh) else None
        diag['checks']['git_url_parseable'] = {
            'ok': repo_name is not None,
            'repo_name': repo_name,
            'message': f'URL parseada como {repo_name}.'
            if repo_name
            else f'Não foi possível extrair owner/repo de: {git_url}',
        }

        # 5. Verificar webhook no GitHub
        if has_token and repo_name:
            try:
                from github import Github

                gh = Github(user.git_token)
                repo = gh.get_repo(repo_name)
                hooks = list(repo.get_hooks())
                expected_url = f'{settings.BACKEND_URL}/api/webhooks/github/{app.id}/'
                matching = [h for h in hooks if h.config.get('url') == expected_url]
                all_hooks = [{'id': h.id, 'url': h.config.get('url'), 'active': h.active} for h in hooks]

                diag['checks']['webhook_exists'] = {
                    'ok': len(matching) > 0,
                    'matching_hooks': len(matching),
                    'all_hooks': all_hooks,
                    'expected_url': expected_url,
                    'message': f'{len(matching)} webhook(s) encontrado(s) apontando para o Fabroku.'
                    if matching
                    else f'Nenhum webhook aponta para {expected_url}. Use setup_webhook para criar.',
                }

                # 6. Verificar último commit e testar commit status
                try:
                    branch = repo.get_branch(app.branch)
                    sha = branch.commit.sha
                    statuses = list(branch.commit.get_statuses())
                    fabroku_statuses = [s for s in statuses if s.context == 'fabroku/deploy']
                    diag['checks']['last_commit'] = {
                        'ok': True,
                        'sha': sha,
                        'branch': app.branch,
                        'total_statuses': len(statuses),
                        'fabroku_statuses': [
                            {'state': s.state, 'description': s.description, 'created_at': str(s.created_at)}
                            for s in fabroku_statuses[:5]
                        ],
                        'message': f'{len(fabroku_statuses)} status fabroku/deploy encontrado(s) no commit {sha[:7]}.'
                        if fabroku_statuses
                        else f'Nenhum status fabroku/deploy no commit {sha[:7]}.',
                    }
                except Exception as e:
                    diag['checks']['last_commit'] = {'ok': False, 'message': str(e)}

            except Exception as e:
                diag['checks']['webhook_exists'] = {'ok': False, 'message': f'Erro ao acessar GitHub API: {e}'}

        return Response(diag)

    @action(detail=True, methods=['post'])
    def test_commit_status(self, request, pk=None):
        """Testa diretamente a criação de um commit status no GitHub."""
        app = self.get_object()
        user = request.user

        if not user.git_token:
            return Response({'error': 'git_token ausente'}, status=status.HTTP_400_BAD_REQUEST)

        git_url = app.git or ''
        repo_name = git_url.rsplit('.com/', maxsplit=1)[-1].replace('.git', '') if '.com/' in git_url else None

        if not repo_name:
            return Response(
                {'error': f'Não foi possível extrair repo de: {git_url}'}, status=status.HTTP_400_BAD_REQUEST
            )

        result = {
            'git_url': git_url,
            'repo_name': repo_name,
            'branch': app.branch,
            'token_preview': f'{user.git_token[:4]}...{user.git_token[-4:]}' if len(user.git_token) > 8 else '***',
        }

        try:
            from github import Github, GithubException

            gh = Github(user.git_token)

            # Teste 1: acessar o repo
            try:
                repo = gh.get_repo(repo_name)
                result['repo_access'] = {'ok': True, 'full_name': repo.full_name, 'private': repo.private}
            except GithubException as e:
                result['repo_access'] = {'ok': False, 'error': f'[{e.status}] {e.data}'}
                return Response(result)

            # Teste 2: obter branch/commit
            try:
                branch = repo.get_branch(app.branch)
                sha = branch.commit.sha
                result['branch_access'] = {'ok': True, 'sha': sha}
            except GithubException as e:
                result['branch_access'] = {'ok': False, 'error': f'[{e.status}] {e.data}'}
                return Response(result)

            # Teste 3: criar commit status
            try:
                commit = repo.get_commit(sha)
                commit.create_status(
                    state='pending',
                    target_url=f'{settings.FRONTEND_URL}/dashboard',
                    description=f'Teste de commit status — {app.name}',
                    context='fabroku/deploy',
                )
                result['create_status'] = {'ok': True, 'sha': sha[:7], 'state': 'pending'}

                # Limpar: setar success para tirar o pending
                commit.create_status(
                    state='success',
                    target_url=f'{settings.FRONTEND_URL}/dashboard',
                    description=f'Teste OK — {app.name}',
                    context='fabroku/deploy',
                )
                result['create_status']['cleaned'] = True
                result['create_status']['message'] = f'Status criado e limpo com sucesso no commit {sha[:7]}!'

            except GithubException as e:
                result['create_status'] = {
                    'ok': False,
                    'error': f'[{e.status}] {e.data}',
                    'message': 'Token pode não ter permissão repo:status. Revogue e refaça o login.',
                }
                return Response(result)

        except Exception as e:
            result['unexpected_error'] = str(e)

        return Response(result)


@extend_schema(tags=['services'])
class ServiceViewSet(ModelViewSet):
    """ViewSet para gerenciamento de serviços (banco de dados, redis, etc.)."""

    queryset = Service.objects.all()
    serializer_class = ServiceSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['app', 'project', 'service_type']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        """Superusers veem todos os serviços, usuários normais só os seus."""
        if self.request.user.is_superuser:
            return Service.objects.all()
        return Service.objects.filter(project__users=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Dispara task de deleção do serviço no Dokku."""
        instance = self.get_object()

        task_result = AppMixin.delete_service.delay(service_id=instance.id)  # type: ignore

        return Response(
            {
                'status': 'DELETING',
                'message': f'Deletando serviço {instance.name}...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )
