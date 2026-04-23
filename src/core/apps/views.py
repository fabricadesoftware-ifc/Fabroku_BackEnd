import logging
import json
import time
from pathlib import PurePosixPath

from celery.result import AsyncResult
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, StreamingHttpResponse
from django.db.models import Prefetch, Q
from django.utils import timezone
from django.utils.http import content_disposition_header
from drf_spectacular.utils import extend_schema
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from core.adapters import GitHubAdapter
from core.apps.mixins import AppMixin
from core.apps.mixins.apps.interactive_run import (
    TERMINAL_SESSION_STATUSES,
    cleanup_expired_interactive_sessions,
    get_interactive_driver,
    get_interactive_session_expires_at,
    request_interactive_session_cancel,
    submit_interactive_session_answer,
)
from core.apps.mixins.apps.run_command import ALLOWED_COMMANDS, ALLOWED_PREFIXES, is_command_allowed
from core.apps.mixins.apps.run_data import (
    cleanup_expired_run_artifacts,
    get_run_artifact_expires_at,
    validate_dump_args,
    validate_manage_path,
)
from core.auth_user.models import User
from core.cache_versioning import APP_LAST_COMMIT_CACHE_NAMESPACE, build_versioned_cache_key, get_cache_ttl
from core.logs.models import AppLogManager, LogCategory

from .models import (
    App,
    AppRunArtifact,
    AppRunArtifactKind,
    InteractiveRunCommandKind,
    InteractiveRunEvent,
    InteractiveRunEventType,
    InteractiveRunSession,
    InteractiveRunSessionStatus,
    Service,
)
from .serializers import AppSerializer, ServiceSerializer

logger = logging.getLogger(__name__)


def _has_global_access(user) -> bool:
    """Retorna True para perfis com visibilidade administrativa global."""
    return bool(getattr(user, 'is_superuser', False))


def _display_user(user) -> str:
    """Retorna um identificador amigÃ¡vel do usuÃ¡rio para logs e diagnÃ³sticos."""
    return user.name or user.email or f'user#{user.id}'


def _parse_github_repo_name(git_url: str | None) -> str | None:
    """Extrai owner/repo de URLs HTTPS ou SSH do GitHub."""
    import re

    git_url = git_url or ''
    match_https = re.match(r'https://github\.com/([^/]+/[^/]+?)(?:\.git)?$', git_url)
    match_ssh = re.match(r'git@github\.com:([^/]+/[^/]+?)(?:\.git)?$', git_url)
    match = match_https or match_ssh
    return match.group(1) if match else None


def _safe_json_filename(filename: str | None, *, default: str = 'dump.json') -> str:
    normalized = (filename or default).strip().replace('\\', '/')
    safe_name = PurePosixPath(normalized).name or default
    if not safe_name.lower().endswith('.json'):
        raise ValueError('O arquivo deve ter extensao .json.')
    return safe_name


def _serialize_interactive_session(session: InteractiveRunSession, *, app_id) -> dict:
    return {
        'session_id': str(session.id),
        'status': session.status,
        'command_kind': session.command_kind,
        'expires_at': session.expires_at.isoformat() if session.expires_at else None,
        'stream_url': f'/api/apps/apps/{app_id}/interactive_sessions/{session.id}/events/',
    }


def _format_sse_event(event: InteractiveRunEvent) -> str:
    payload = json.dumps({'id': event.id, **event.payload}, ensure_ascii=True)
    return f'id: {event.id}\nevent: {event.event_type}\ndata: {payload}\n\n'


class InteractiveSessionCreateSerializer(drf_serializers.Serializer):
    command_kind = drf_serializers.ChoiceField(choices=InteractiveRunCommandKind.choices)
    manage_path = drf_serializers.CharField(required=False, allow_blank=False, default='manage.py')


class InteractiveSessionAnswerSerializer(drf_serializers.Serializer):
    prompt_id = drf_serializers.CharField()
    value = drf_serializers.CharField(allow_blank=True)


def _iter_project_users_with_git_token(app: App, preferred_user=None):
    """Itera pelos membros do projeto com token, priorizando o usuÃ¡rio atual."""
    yielded_ids = set()

    if preferred_user and preferred_user.git_token:
        yielded_ids.add(preferred_user.id)
        yield preferred_user

    queryset = app.project.users.exclude(git_token__isnull=True).exclude(git_token='')
    if yielded_ids:
        queryset = queryset.exclude(id__in=yielded_ids)

    for project_user in queryset:
        yield project_user


def _find_project_user_for_github_repo(app: App, preferred_user=None, *, require_hook_access: bool = False):
    """
    Procura um membro do projeto cujo token consiga acessar o repositÃ³rio.

    Quando require_hook_access=True, tambÃ©m exige permissÃ£o para listar webhooks.
    """
    from github import Github, GithubException  # noqa: PLC0415

    repo_name = _parse_github_repo_name(app.git)
    attempts = []

    if not repo_name:
        return None, None, attempts

    for project_user in _iter_project_users_with_git_token(app, preferred_user=preferred_user):
        try:
            gh = Github(project_user.git_token)
            repo = gh.get_repo(repo_name)
            if require_hook_access:
                list(repo.get_hooks())
            return project_user, repo, attempts
        except GithubException as e:
            attempts.append({
                'user': _display_user(project_user),
                'status': e.status,
                'message': str(e.data),
            })
        except Exception as e:
            attempts.append({
                'user': _display_user(project_user),
                'status': 'unexpected',
                'message': str(e),
            })

    return None, None, attempts


@extend_schema(tags=['apps'])
class AppViewSet(ModelViewSet):
    queryset = App.objects.all()
    serializer_class = AppSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['project', 'status', 'name', 'branch']

    def get_queryset(self):
        """Superusers veem todos os apps, usuários normais só os seus."""
        queryset = App.objects.select_related('project')

        if getattr(self, 'action', None) in {'list', 'retrieve'}:
            queryset = queryset.prefetch_related(
                Prefetch('services', queryset=Service.objects.all()),
                Prefetch('project__users', queryset=User.objects.only('id')),
            )

        if _has_global_access(self.request.user):
            return queryset
        return queryset.filter(project__users=self.request.user)

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

    @action(detail=False, methods=['get'], url_path='check_name')
    def check_name(self, request):
        """Verifica se um nome de app já está em uso. Retorna available: true/false."""
        name = request.query_params.get('name', '').strip().lower()
        if not name:
            return Response(
                {'available': False, 'reason': 'Nome é obrigatório.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Valida formato: apenas letras minúsculas, números e hífens
        import re

        if not re.match(r'^[a-z0-9][a-z0-9\-]*[a-z0-9]$', name) and len(name) > 1:
            return Response({'available': False, 'reason': 'Use apenas letras minúsculas, números e hífens.'})
        if len(name) < 2:
            return Response({'available': False, 'reason': 'Nome deve ter pelo menos 2 caracteres.'})
        if len(name) > 60:
            return Response({'available': False, 'reason': 'Nome deve ter no máximo 60 caracteres.'})
        exists = App.objects.filter(name__iexact=name).exists()
        return Response({'available': not exists, 'name': name})

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

        task_result = AppMixin.manage_app_task.delay(app_id=app.id, action='start')  # type: ignore

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

        task_result = AppMixin.manage_app_task.delay(app_id=app.id, action='stop')  # type: ignore

        return Response(
            {
                'status': 'STOPPING',
                'message': f'Parando aplicação {app.name}...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """Para uma aplicaÃ§Ã£o em execuÃ§Ã£o ou cancela um redeploy ativo."""
        app = self.get_object()

        if app.status == 'DEPLOYING' and app.task_id:
            current_task = AsyncResult(app.task_id)
            if current_task.state not in ('SUCCESS', 'FAILURE', 'REVOKED'):
                current_task.revoke(terminate=True, signal='SIGTERM')

            AppLogManager(app, app.task_id).warning(
                'Redeploy cancelado pelo usuÃ¡rio.',
                category=LogCategory.DEPLOY,
                progress=100,
            )

            app.status = 'RUNNING'
            app.save(update_fields=['status'])

            return Response(
                {
                    'status': 'RUNNING',
                    'message': f'Redeploy de {app.name} cancelado.',
                    'task_id': app.task_id,
                    'cancelled_task_id': app.task_id,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        if not app.name_dokku:
            return Response(
                {'error': 'App nÃ£o tem name_dokku configurado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        app.status = 'STOPPING'
        app.save(update_fields=['status'])

        task_result = AppMixin.manage_app_task.delay(app_id=app.id, action='stop')  # type: ignore

        return Response(
            {
                'status': 'STOPPING',
                'message': f'Parando aplicaÃ§Ã£o {app.name}...',
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

        task_result = AppMixin.manage_app_task.delay(app_id=app.id, action='restart')  # type: ignore

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

        elif task_result.state == 'REVOKED':
            response_data['status'] = 'OperaÃ§Ã£o cancelada pelo usuÃ¡rio.'
            response_data['current'] = 100

        return Response(response_data)

    @action(detail=True, methods=['get'])
    def get_app_status(self, request, pk=None):
        app = self.get_object()

        if not app.task_id:
            return Response({'state': 'UNKNOWN', 'status': 'Nenhuma task vinculada.'})

        task_result = AsyncResult(app.task_id)
        response_data = {
            'task_id': app.task_id,
            'state': task_result.state,
        }

        if task_result.state == 'PROGRESS':
            response_data.update(task_result.info)
        elif task_result.state == 'SUCCESS':
            task_payload = task_result.result if isinstance(task_result.result, dict) else {}
            response_data['status'] = task_payload.get('message') or 'Operacao concluida com sucesso!'
            response_data['current'] = 100
            if isinstance(task_payload, dict):
                for key in ('output', 'command', 'lines', 'app_id', 'action', 'dokku_app', 'commit', 'artifact'):
                    if key in task_payload:
                        response_data[key] = task_payload[key]
        elif task_result.state == 'FAILURE':
            response_data['status'] = app.error_details or str(task_result.result)
            if app.error_type:
                response_data['error_type'] = app.error_type
            if app.error_details:
                response_data['error_details'] = app.error_details
            if app.help_url:
                response_data['help_url'] = app.help_url
            if app.error_type == 'DeployKeysDisabled':
                response_data['deploy_keys_disabled'] = True
        elif task_result.state == 'REVOKED':
            response_data['status'] = 'Operacao cancelada pelo usuario.'
            response_data['current'] = 100

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

    @action(detail=True, methods=['post'], url_path='run_loaddata', parser_classes=[MultiPartParser, FormParser])
    def run_loaddata(self, request, pk=None):
        """Recebe um fixture JSON da CLI e executa Django loaddata no app."""
        app = self.get_object()

        if not app.name_dokku:
            return Response(
                {'error': 'App nao tem name_dokku configurado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fixture = request.FILES.get('fixture')
        if not fixture:
            return Response({'error': 'O campo fixture e obrigatorio.'}, status=status.HTTP_400_BAD_REQUEST)

        max_size = int(getattr(settings, 'CLI_RUN_ARTIFACT_MAX_BYTES', 50 * 1024 * 1024))
        if fixture.size > max_size:
            return Response(
                {'error': f'Fixture excede o limite de {max_size} bytes.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            filename = _safe_json_filename(fixture.name, default='fixture.json')
            manage_path = validate_manage_path(request.data.get('manage_path'))
            content = fixture.read()
            content.decode('utf-8')
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except UnicodeDecodeError:
            return Response({'error': 'Fixture deve ser JSON UTF-8.'}, status=status.HTTP_400_BAD_REQUEST)

        cleanup_expired_run_artifacts()
        artifact = AppRunArtifact.objects.create(
            app=app,
            created_by=request.user,
            kind=AppRunArtifactKind.LOAD_DATA_UPLOAD,
            filename=filename,
            content_type='application/json',
            size=len(content),
            content=content,
            expires_at=get_run_artifact_expires_at(),
        )

        task_result = AppMixin.run_loaddata.delay(
            app_id=app.id,
            artifact_id=str(artifact.id),
            manage_path=manage_path,
            user_id=request.user.id,
        )  # type: ignore
        app.task_id = task_result.id
        app.save(update_fields=['task_id'])

        return Response(
            {
                'status': 'RUNNING',
                'message': f'Executando loaddata com {filename}',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'], url_path='run_dumpdata')
    def run_dumpdata(self, request, pk=None):
        """Executa Django dumpdata no app e gera um artefato para download pela CLI."""
        app = self.get_object()

        if not app.name_dokku:
            return Response(
                {'error': 'App nao tem name_dokku configurado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            manage_path = validate_manage_path(request.data.get('manage_path'))
            dump_args = validate_dump_args(request.data.get('dump_args', []))
            output_filename = _safe_json_filename(request.data.get('output_filename'), default='dump.json')
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        cleanup_expired_run_artifacts()
        task_result = AppMixin.run_dumpdata.delay(
            app_id=app.id,
            manage_path=manage_path,
            dump_args=dump_args,
            output_filename=output_filename,
            user_id=request.user.id,
        )  # type: ignore
        app.task_id = task_result.id
        app.save(update_fields=['task_id'])

        return Response(
            {
                'status': 'RUNNING',
                'message': f'Gerando dumpdata para {output_filename}',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['get'], url_path=r'artifacts/(?P<artifact_id>[^/.]+)/download')
    def download_artifact(self, request, pk=None, artifact_id=None):
        """Baixa um artefato temporario gerado pelo dumpdata."""
        app = self.get_object()
        artifact = AppRunArtifact.objects.filter(
            id=artifact_id,
            app=app,
            kind=AppRunArtifactKind.DUMP_DATA_EXPORT,
            expires_at__gt=timezone.now(),
        ).first()

        if not artifact:
            return Response({'error': 'Artefato nao encontrado ou expirado.'}, status=status.HTTP_404_NOT_FOUND)

        response = HttpResponse(bytes(artifact.content), content_type=artifact.content_type)
        response['Content-Length'] = str(artifact.size)
        response['Content-Disposition'] = content_disposition_header(True, artifact.filename)
        return response

    def _get_interactive_session(self, app: App, session_id: str, user) -> InteractiveRunSession | None:
        return InteractiveRunSession.objects.filter(id=session_id, app=app, created_by=user).first()

    @action(detail=True, methods=['post'], url_path='interactive_sessions')
    def create_interactive_session(self, request, pk=None):
        """Inicia uma sessao interativa controlada pela CLI para comandos registrados."""
        app = self.get_object()
        if not app.name_dokku:
            return Response({'error': 'App nao tem name_dokku configurado'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = InteractiveSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        command_kind = serializer.validated_data['command_kind']
        try:
            manage_path = validate_manage_path(serializer.validated_data.get('manage_path'))
            get_interactive_driver(command_kind)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        cleanup_expired_interactive_sessions()
        session = InteractiveRunSession.objects.create(
            app=app,
            created_by=request.user,
            command_kind=command_kind,
            status=InteractiveRunSessionStatus.PENDING,
            manage_path=manage_path,
            expires_at=get_interactive_session_expires_at(),
            last_activity_at=timezone.now(),
        )

        task_result = AppMixin.run_interactive_session.delay(session_id=str(session.id))  # type: ignore
        session.task_id = task_result.id
        session.save(update_fields=['task_id'])

        payload = _serialize_interactive_session(session, app_id=app.id)
        payload['task_id'] = task_result.id
        return Response(payload, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'], url_path=r'interactive_sessions/(?P<session_id>[^/.]+)/events')
    def interactive_session_events(self, request, pk=None, session_id=None):
        """Stream SSE com eventos da sessao interativa."""
        app = self.get_object()
        session = self._get_interactive_session(app, session_id, request.user)
        if not session:
            return Response({'error': 'Sessao interativa nao encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            after_event_id = int(request.query_params.get('after', '0') or 0)
        except ValueError:
            after_event_id = 0

        def event_stream():
            nonlocal after_event_id
            keepalive_at = time.monotonic()

            while True:
                events = list(
                    InteractiveRunEvent.objects.filter(session=session, id__gt=after_event_id).order_by('id')[:50]
                )
                if events:
                    for interactive_event in events:
                        after_event_id = interactive_event.id
                        yield _format_sse_event(interactive_event)
                    keepalive_at = time.monotonic()
                    continue

                current_session = self._get_interactive_session(app, session_id, request.user)
                if not current_session:
                    break

                if (
                    current_session.status in TERMINAL_SESSION_STATUSES
                    and not InteractiveRunEvent.objects.filter(session=current_session, id__gt=after_event_id).exists()
                ):
                    break

                if time.monotonic() - keepalive_at >= 5:
                    keepalive_at = time.monotonic()
                    yield ': keep-alive\n\n'

                time.sleep(0.5)

        response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response

    @action(detail=True, methods=['post'], url_path=r'interactive_sessions/(?P<session_id>[^/.]+)/answer')
    def answer_interactive_session(self, request, pk=None, session_id=None):
        """Envia a resposta para o prompt atual da sessao interativa."""
        app = self.get_object()
        session = self._get_interactive_session(app, session_id, request.user)
        if not session:
            return Response({'error': 'Sessao interativa nao encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = InteractiveSessionAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            submit_interactive_session_answer(
                str(session.id),
                serializer.validated_data['prompt_id'],
                serializer.validated_data['value'],
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)

        session.refresh_from_db()
        return Response(_serialize_interactive_session(session, app_id=app.id))

    @action(detail=True, methods=['post'], url_path=r'interactive_sessions/(?P<session_id>[^/.]+)/cancel')
    def cancel_interactive_session(self, request, pk=None, session_id=None):
        """Solicita o cancelamento de uma sessao interativa ativa."""
        app = self.get_object()
        session = self._get_interactive_session(app, session_id, request.user)
        if not session:
            return Response({'error': 'Sessao interativa nao encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        request_interactive_session_cancel(str(session.id))
        session.refresh_from_db()
        return Response(_serialize_interactive_session(session, app_id=app.id))

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

        if not app.git:
            return Response(
                {'error': 'App não tem URL do repositório Git configurada.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        repo_name = _parse_github_repo_name(app.git)
        if not repo_name:
            return Response(
                {'error': f'Nao foi possivel extrair owner/repo de: {app.git}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        candidate_users = list(_iter_project_users_with_git_token(app, preferred_user=user))
        if not candidate_users:
            return Response(
                {'error': 'Nenhum usuario do projeto tem git_token salvo para configurar o webhook.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        github_adapter = GitHubAdapter()
        webhook_url = f'{settings.BACKEND_URL}/api/webhooks/github/{app.id}/'
        attempts = []

        for candidate_user in candidate_users:
            result = github_adapter.create_webhook(
                repo_name=repo_name,
                app_id=app.id,
                user_id=candidate_user.id,
            )

            logger.info(
                'Webhook setup para app %s via %s: %s (URL: %s)',
                app.name,
                _display_user(candidate_user),
                result,
                webhook_url,
            )

            status_value = result.get('status', 'unknown')
            if status_value == 'webhook criado' or (status_value.startswith('webhook') and 'existe' in status_value):
                return Response({
                    'status': status_value,
                    'webhook_url': webhook_url,
                    'backend_url': settings.BACKEND_URL,
                    'repo': repo_name,
                    'hook_id': result.get('hook_id'),
                    'configured_by': _display_user(candidate_user),
                })

            attempts.append({
                'user': _display_user(candidate_user),
                'status': status_value,
                'error': result.get('error'),
            })

        logger.warning('Nao foi possivel configurar webhook para app %s. Tentativas: %s', app.name, attempts)
        return Response(
            {
                'error': (
                    'Nao foi possivel configurar o webhook com nenhum token do projeto. '
                    'Verifique se ao menos um membro tem permissao de Webhooks no repositorio GitHub.'
                ),
                'repo': repo_name,
                'attempts': attempts,
            },
            status=status.HTTP_400_BAD_REQUEST,
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
        project_user_with_token, repo_for_status, repo_access_attempts = _find_project_user_for_github_repo(
            app,
            preferred_user=user,
        )
        diag['checks']['project_git_token'] = {
            'ok': project_user_with_token is not None,
            'user': _display_user(project_user_with_token) if project_user_with_token else None,
            'message': f'Token com acesso ao repositorio disponivel via {_display_user(project_user_with_token)}.'
            if project_user_with_token
            else 'Nenhum usuario do projeto tem git_token com acesso ao repositorio.',
        }
        if repo_access_attempts:
            diag['checks']['project_git_token']['attempts'] = repo_access_attempts

        # 4. Verificar git_url parseable
        git_url = app.git or ''
        repo_name = _parse_github_repo_name(git_url)
        diag['checks']['git_url_parseable'] = {
            'ok': repo_name is not None,
            'repo_name': repo_name,
            'message': f'URL parseada como {repo_name}.'
            if repo_name
            else f'Não foi possível extrair owner/repo de: {git_url}',
        }

        # 5. Verificar webhook no GitHub
        if repo_name:
            try:
                project_user_with_hook_access, repo_with_hook_access, hook_attempts = _find_project_user_for_github_repo(
                    app,
                    preferred_user=user,
                    require_hook_access=True,
                )
                expected_url = f'{settings.BACKEND_URL}/api/webhooks/github/{app.id}/'
                if project_user_with_hook_access and repo_with_hook_access:
                    hooks = list(repo_with_hook_access.get_hooks())
                    matching = [h for h in hooks if h.config.get('url') == expected_url]
                    all_hooks = [{'id': h.id, 'url': h.config.get('url'), 'active': h.active} for h in hooks]

                    diag['checks']['webhook_exists'] = {
                        'ok': len(matching) > 0,
                        'matching_hooks': len(matching),
                        'all_hooks': all_hooks,
                        'expected_url': expected_url,
                        'checked_as': _display_user(project_user_with_hook_access),
                        'message': f'{len(matching)} webhook(s) encontrado(s) apontando para o Fabroku.'
                        if matching
                        else f'Nenhum webhook aponta para {expected_url}. Use setup_webhook para criar.',
                    }
                else:
                    diag['checks']['webhook_exists'] = {
                        'ok': False,
                        'expected_url': expected_url,
                        'attempts': hook_attempts,
                        'message': (
                            'Nenhum token do projeto conseguiu listar os webhooks no GitHub. '
                            'Verifique se ao menos um membro tem permissao de Webhooks no repositorio.'
                        ),
                    }
            except Exception as e:
                diag['checks']['webhook_exists'] = {'ok': False, 'message': f'Erro ao acessar GitHub API: {e}'}

        # 6. Verificar último commit e testar commit status
        if repo_for_status:
            try:
                branch = repo_for_status.get_branch(app.branch)
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

    @action(detail=True, methods=['get'], url_path='last_commit')
    def last_commit(self, request, pk=None):
        """Retorna informações do último commit deployado (via GitHub API)."""
        app = self.get_object()

        if not app.last_commit_sha:
            return Response({'error': 'Nenhum commit deployado ainda.'}, status=status.HTTP_404_NOT_FOUND)

        force_refresh = request.query_params.get('refresh') in {'1', 'true', 'True'}
        cache_ttl = get_cache_ttl(APP_LAST_COMMIT_CACHE_NAMESPACE, default=300)
        cache_key = build_versioned_cache_key(
            APP_LAST_COMMIT_CACHE_NAMESPACE,
            suffix=f'app-{app.id}-sha-{app.last_commit_sha}',
        )

        if cache_ttl and not force_refresh:
            cached_payload = cache.get(cache_key)
            if cached_payload is not None:
                return Response(cached_payload)

        user = app.project.users.exclude(git_token__isnull=True).exclude(git_token='').first()
        if not user:
            payload = {'sha': app.last_commit_sha[:7], 'message': 'Sem token GitHub disponível para detalhes.'}
            if cache_ttl:
                cache.set(cache_key, payload, cache_ttl)
            return Response(payload, status=status.HTTP_200_OK)

        try:
            from github import Github  # noqa: PLC0415

            repo_name = app.git.rsplit('.com/', maxsplit=1)[-1].replace('.git', '') if '.com/' in app.git else None
            if not repo_name:
                payload = {'sha': app.last_commit_sha[:7], 'error': 'Não foi possível extrair repo da URL.'}
                if cache_ttl:
                    cache.set(cache_key, payload, cache_ttl)
                return Response(payload)

            gh = Github(user.git_token)
            repo = gh.get_repo(repo_name)
            commit = repo.get_commit(app.last_commit_sha)

            payload = {
                'sha': app.last_commit_sha,
                'sha_short': app.last_commit_sha[:7],
                'message': commit.commit.message,
                'author': commit.commit.author.name or 'Unknown',
                'date': commit.commit.author.date.isoformat() if commit.commit.author.date else None,
                'url': commit.html_url,
            }
            if cache_ttl:
                cache.set(cache_key, payload, cache_ttl)
            return Response(payload)
        except Exception as e:
            payload = {
                'sha': app.last_commit_sha,
                'sha_short': app.last_commit_sha[:7],
                'error': str(e),
            }
            if cache_ttl:
                cache.set(cache_key, payload, cache_ttl)
            return Response(payload)


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
        if _has_global_access(self.request.user):
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

    @action(detail=True, methods=['post'])
    def link(self, request, pk=None):
        """Vincula o serviço a um app. Requer app_id no body."""
        service = self.get_object()
        app_id = request.data.get('app_id')
        if not app_id:
            return Response(
                {'error': 'O campo app_id é obrigatório'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if service.app_id:
            return Response(
                {'error': f'Serviço já vinculado ao app {service.app_id}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task_result = AppMixin.link_service.delay(service_id=service.id, app_id=int(app_id))  # type: ignore

        app = App.objects.filter(id=app_id).first()
        if app:
            app.task_id = task_result.id
            app.save(update_fields=['task_id'])

        return Response(
            {
                'status': 'LINKING',
                'message': f'Vinculando serviço ao app...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def unlink(self, request, pk=None):
        """Desvincula o serviço do app."""
        service = self.get_object()

        if not service.app_id:
            return Response(
                {'error': 'Serviço não está vinculado a nenhum app'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task_result = AppMixin.unlink_service.delay(service_id=service.id)  # type: ignore

        app = service.app
        app.task_id = task_result.id
        app.save(update_fields=['task_id'])

        return Response(
            {
                'status': 'UNLINKING',
                'message': 'Desvinculando serviço do app...',
                'task_id': task_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['get'])
    def get_service_status(self, request, pk=None):
        """Retorna o status da task em execução (criação, link, unlink, delete)."""
        service = self.get_object()

        task_id = service.task_id or (service.app.task_id if service.app else None)
        if not task_id:
            # Task já concluiu e limpou task_id; se tem container_name, foi provisionado
            if service.container_name:
                return Response({
                    'state': 'SUCCESS',
                    'status': 'Serviço provisionado com sucesso!',
                    'current': 100,
                })
            return Response({'state': 'UNKNOWN', 'status': 'Nenhuma task vinculada.'})

        task_result = AsyncResult(task_id)
        response_data = {
            'task_id': task_id,
            'state': task_result.state,
        }
        if task_result.state == 'PROGRESS':
            response_data.update(task_result.info)
        elif task_result.state == 'SUCCESS':
            response_data['status'] = 'Operação concluída com sucesso!'
            response_data['current'] = 100
        elif task_result.state == 'FAILURE':
            response_data['status'] = str(task_result.result)

        return Response(response_data)
