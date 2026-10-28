import base64
import codecs
import json
import logging
import re
import time
import uuid
from abc import abstractmethod
from collections.abc import Callable, Generator

from django.conf import settings

logger = logging.getLogger(__name__)

GIT_SYNC_FAILED_MESSAGE = 'Failed to sync Git repository and deploy.'
REMOTE_DEPLOY_POLL_SECONDS = 2
# ~1 min sem conseguir ler o log: desiste de acompanhar (o build segue no servidor).
REMOTE_DEPLOY_MAX_POLL_FAILURES = 30
REMOTE_DEPLOY_ID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
REMOTE_DEPLOY_FINISHED_STATES = frozenset({'succeeded', 'failed', 'cancelled', 'lost'})
# A partir desta versão o plugin tem fabroku:deploy-follow (uma conexão por deploy).
REMOTE_DEPLOY_FOLLOW_MIN_VERSION = (0, 2, 0)
# Nenhum byte nesse tempo: reconecta do último offset (conexão morta não avisa).
REMOTE_DEPLOY_FOLLOW_IDLE_SECONDS = 120

GIT_SYNC_FAILURE_MARKERS = (
    '[error]',
    '[ssh error]',
    'app build failed',
    'authentication failed',
    'could not read from remote repository',
    'could not read username',
    'fatal:',
    'not found',
    'permission denied',
    'repository not found',
    'terminal prompts disabled',
)


class RemoteDeployError(Exception):
    """O plugin fabroku respondeu algo que não é JSON (plugin ausente, SSH caiu...)."""


def _last_json_line(output: str) -> dict | None:
    for raw_line in reversed((output or '').splitlines()):
        line = raw_line.strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


def _version_tuple(version) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in str(version).split('.')[:3])
    except ValueError:
        return ()


class _LogLines:
    """Junta bytes do log em linhas; caractere UTF-8 partido entre pedaços não se perde."""

    def __init__(self, emit: Callable[[str], None]):
        self._emit = emit
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self._pending = ''

    def feed(self, raw: bytes) -> None:
        *lines, self._pending = (self._pending + self._decoder.decode(raw)).split('\n')
        for line in lines:
            self._emit(line)

    def close(self) -> None:
        tail = self._pending + self._decoder.decode(b'', final=True)
        self._pending = ''
        if tail:
            self._emit(tail)


class DokkuGitMixin:
    """Mixin que fornece métodos para integração Git com Dokku."""

    @abstractmethod
    def _run_command(self, command: str, *, audit: bool = True) -> str:
        """Executa um comando no servidor Dokku."""
        ...

    @abstractmethod
    def _run_command_streaming(self, command: str) -> Generator[str, None, int]:
        """Executa um comando SSH e faz yield de cada linha."""
        ...

    @abstractmethod
    def _run_command_bytes_streaming(self, command: str, *, idle_timeout: float) -> Generator[bytes, None, int]:
        """Executa um comando SSH sem PTY e faz yield do stdout cru; erros de conexão sobem."""
        ...

    @abstractmethod
    def exists_app(self, app_name: str) -> bool:
        """Verifica se uma aplicação existe."""
        ...

    def sync_git(self, app_name: str, git_url: str, branch: str = 'main') -> str:
        """Sincroniza repositório Git com aplicação Dokku."""
        if not self.exists_app(app_name):
            return 'Application not found.'

        command_output = self._run_command(f'git:sync --build {app_name} {git_url} {branch}')
        if 'Failed to execute command' in command_output:
            return 'Failed to sync Git repository and deploy.'

        return command_output

    def sync_git_streaming(
        self,
        app_name: str,
        git_url: str,
        branch: str = 'main',
        on_line: Callable[[str], None] | None = None,
        deploy_id: str | None = None,
    ) -> str:
        """
        Sincroniza repositório Git com streaming de logs em tempo real.

        Args:
            app_name: Nome da aplicação no Dokku
            git_url: URL do repositório Git
            branch: Branch a sincronizar (default: main)
            on_line: Callback chamado para cada linha de output
            deploy_id: ID do deploy no plugin fabroku (o task_id); gerado se ausente

        Returns:
            Output completo do comando
        """
        if not self.exists_app(app_name):
            return 'Application not found.'

        if settings.DOKKU_REMOTE_DEPLOY_PLUGIN:
            version = self.remote_deploy_version()
            if version:
                follow = _version_tuple(version) >= REMOTE_DEPLOY_FOLLOW_MIN_VERSION
                return self._sync_git_remote(
                    app_name, git_url, branch, on_line, deploy_id or str(uuid.uuid4()), follow=follow
                )

        command = f'git:sync --build {app_name} {git_url} {branch}'
        lines = []

        for line in self._run_command_streaming(command):
            lines.append(line)
            if on_line:
                on_line(line)

        output = '\n'.join(lines)

        output_lower = output.lower()
        if any(marker in output_lower for marker in GIT_SYNC_FAILURE_MARKERS):
            return GIT_SYNC_FAILED_MESSAGE

        return output

    # --- Plugin fabroku (Fabroku_Plugin): build roda no servidor, fora da sessão SSH ---

    def _remote_deploy_json(self, command: str, *, audit: bool = True) -> dict:
        data = _last_json_line(self._run_command(command, audit=audit))
        if data is None:
            raise RemoteDeployError(f'Resposta inesperada do plugin fabroku para "{command.split(maxsplit=1)[0]}"')
        return data

    def remote_deploy_version(self) -> str | None:
        """Versão do plugin instalado, ou None se ele não responde."""
        try:
            return self._remote_deploy_json('fabroku:version').get('version')
        except Exception:
            logger.warning('Plugin fabroku indisponível; usando git:sync pela sessão SSH.', exc_info=True)
            return None

    def remote_deploy_available(self) -> bool:
        return self.remote_deploy_version() is not None

    def get_remote_deploy_status(self, deploy_id: str) -> dict | None:
        """Estado do deploy no plugin, ou None se o plugin não conhece esse id."""
        if not REMOTE_DEPLOY_ID_PATTERN.match(deploy_id or ''):
            return None
        data = self._remote_deploy_json(f'fabroku:deploy-status {deploy_id}')
        return None if 'error' in data else data

    def cancel_remote_deploy(self, deploy_id: str) -> dict | None:
        """Cancela o deploy no servidor (SIGTERM, SIGKILL após o prazo, dokku cleanup)."""
        if not REMOTE_DEPLOY_ID_PATTERN.match(deploy_id or ''):
            return None
        data = self._remote_deploy_json(f'fabroku:deploy-cancel {deploy_id}')
        return None if 'error' in data else data

    def _sync_git_remote(  # noqa: PLR0913
        self,
        app_name: str,
        git_url: str,
        branch: str,
        on_line: Callable[[str], None] | None,
        deploy_id: str,
        *,
        follow: bool = False,
    ) -> str:
        def emit(line: str) -> None:
            if on_line:
                on_line(line.rstrip('\r'))

        started = self._remote_deploy_json(f'fabroku:deploy {app_name} {git_url} {branch} {deploy_id}')
        if 'error' in started:
            emit(f'[ERROR] {started.get("message") or started["error"]}')
            return f'{GIT_SYNC_FAILED_MESSAGE} ({started["error"]})'

        log = _LogLines(emit)
        state = self._follow_remote_log(deploy_id, log) if follow else self._poll_remote_log(deploy_id, log)
        log.close()
        if state is None:
            emit(f'[SSH ERROR] Não foi possível acompanhar o deploy {deploy_id}.')
            return f'{GIT_SYNC_FAILED_MESSAGE} (log indisponível)'

        if state == 'succeeded':
            # O exit code é a verdade: não procura marcadores de erro no log.
            return f'Remote deploy {deploy_id} succeeded'
        return f'{GIT_SYNC_FAILED_MESSAGE} ({state})'

    def _follow_remote_log(self, deploy_id: str, log: _LogLines) -> str | None:
        """Uma conexão aberta enquanto o build roda; se cair, reconecta do último byte recebido."""
        offset, failures = 0, 0
        while failures < REMOTE_DEPLOY_MAX_POLL_FAILURES:
            stream = self._run_command_bytes_streaming(
                f'fabroku:deploy-follow {deploy_id} {offset}', idle_timeout=REMOTE_DEPLOY_FOLLOW_IDLE_SECONDS
            )
            exit_status = None
            try:
                while True:
                    chunk = next(stream)
                    offset += len(chunk)
                    failures = 0
                    log.feed(chunk)
            except StopIteration as stop:
                exit_status = stop.value
            except Exception:
                logger.info('Conexão do deploy-follow %s caiu; reconectando do byte %d.', deploy_id, offset)
            finally:
                stream.close()

            if exit_status == 0:
                # O follow só termina sozinho quando o runner termina.
                try:
                    state = self._remote_deploy_json(f'fabroku:deploy-status {deploy_id}').get('state')
                except RemoteDeployError:
                    state = None
                if state in REMOTE_DEPLOY_FINISHED_STATES:
                    return state
            failures += 1
            time.sleep(REMOTE_DEPLOY_POLL_SECONDS)
        return None

    def _poll_remote_log(self, deploy_id: str, log: _LogLines) -> str | None:
        """Plugin 0.1.x: lê o log por offset a cada REMOTE_DEPLOY_POLL_SECONDS."""
        offset, failures = 0, 0
        while True:
            try:
                # Sem auditoria: um registro por leitura de log seriam centenas por deploy.
                data = self._remote_deploy_json(f'fabroku:deploy-log {deploy_id} {offset}', audit=False)
                if 'error' in data:
                    raise RemoteDeployError(data.get('message') or data['error'])
            except RemoteDeployError:
                failures += 1
                if failures >= REMOTE_DEPLOY_MAX_POLL_FAILURES:
                    return None
                time.sleep(REMOTE_DEPLOY_POLL_SECONDS)
                continue

            failures = 0
            log.feed(base64.b64decode(data['chunk']))
            offset = data['next_offset']
            if data['eof']:
                return data['state']
            if offset >= data['size']:
                time.sleep(REMOTE_DEPLOY_POLL_SECONDS)

    def set_git_remote(self, app_name: str, git_url: str) -> str:
        """Configura o repositório Git remoto para a aplicação Dokku."""
        return self.sync_git(app_name, git_url)

    def remove_git_remote(self, app_name: str) -> str:
        """Remove o repositório Git remoto da aplicação Dokku."""
        if not self.exists_app(app_name):
            return 'Application not found.'

        if not self._run_command(f'git:remote-remove {app_name}'):
            return 'Failed to remove Git remote.'

        return 'Git remote removed successfully.'

    def generate_git_deploy_key(self) -> str:
        """
        Obtém a chave de deploy Git existente ou gera uma nova se não existir.
        Retorna a chave pública no formato OpenSSH.
        """
        # Primeiro tenta obter a chave existente
        existing_key = self._run_command('git:public-key')

        # Se já existe uma chave válida (começa com ssh-), retorna ela
        if existing_key and existing_key.strip().startswith('ssh-'):
            return existing_key.strip()

        # Se não existe, gera uma nova
        self._run_command('git:generate-deploy-key')
        return self._run_command('git:public-key').strip()

    def get_git_deploy_key(self) -> str:
        """Obtém a chave de deploy Git pública existente."""
        return self._run_command('git:public-key').strip()
