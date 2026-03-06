import io
import logging
from abc import abstractmethod
from collections.abc import Callable, Generator

import paramiko

logger = logging.getLogger(__name__)


class DokkuGitMixin:
    """Mixin que fornece métodos para integração Git com Dokku."""

    @abstractmethod
    def _run_command(self, command: str) -> str:
        """Executa um comando no servidor Dokku."""
        ...

    @abstractmethod
    def _run_command_streaming(self, command: str) -> Generator[str, None, int]:
        """Executa um comando SSH e faz yield de cada linha."""
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
    ) -> str:
        """
        Sincroniza repositório Git com streaming de logs em tempo real.

        Args:
            app_name: Nome da aplicação no Dokku
            git_url: URL do repositório Git
            branch: Branch a sincronizar (default: main)
            on_line: Callback chamado para cada linha de output

        Returns:
            Output completo do comando
        """
        if not self.exists_app(app_name):
            return 'Application not found.'

        command = f'git:sync --build {app_name} {git_url} {branch}'
        lines = []

        for line in self._run_command_streaming(command):
            lines.append(line)
            if on_line:
                on_line(line)

        output = '\n'.join(lines)

        output_lower = output.lower()
        if (
            '[error]' in output_lower
            or '[ssh error]' in output_lower
            or 'app build failed' in output_lower
            or 'could not read from remote repository' in output_lower
            or 'permission denied' in output_lower
        ):
            return 'Failed to sync Git repository and deploy.'

        return output

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

        NOTA: Método legado — usa chave global do Dokku.
        Para novos deploys, preferir generate_app_deploy_key().
        """
        # Primeiro tenta obter a chave existente
        existing_key = self._run_command('git:public-key')

        # Se já existe uma chave válida (começa com ssh-), retorna ela
        if existing_key and existing_key.strip().startswith('ssh-'):
            return existing_key.strip()

        # Se não existe, gera uma nova
        self._run_command('git:generate-deploy-key')
        return self._run_command('git:public-key').strip()

    def generate_app_deploy_key(self, app_name: str) -> str:
        """
        Gera um par de chaves SSH exclusivo para o app e configura no Dokku.
        Usa dokku git:set <app> deploy-key para que cada app tenha sua
        própria chave, evitando o erro "key is already in use" do GitHub.

        Retorna a chave pública no formato OpenSSH para registrar no GitHub.
        """
        key = paramiko.RSAKey.generate(4096)

        # Chave privada em formato PEM
        private_io = io.StringIO()
        key.write_private_key(private_io)
        private_key = private_io.getvalue()

        # Chave pública em formato OpenSSH
        public_key = f'ssh-rsa {key.get_base64()}'

        # Configurar a chave privada no Dokku para este app
        # PEM keys são ASCII puro (sem aspas simples), seguro para shell quoting
        result = self._run_command(f"git:set {app_name} deploy-key '{private_key}'")

        if 'Failed to execute command' in result or 'SSH Connection Error' in result:
            logger.error(f'Falha ao configurar deploy key para {app_name}: {result}')
            raise Exception(f'Falha ao configurar deploy key para {app_name}: {result}')

        logger.info(f'Deploy key per-app configurada com sucesso para {app_name}')
        return public_key

    def get_git_deploy_key(self) -> str:
        """Obtém a chave de deploy Git pública existente (global)."""
        return self._run_command('git:public-key').strip()
