from abc import abstractmethod
from collections.abc import Callable, Generator


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

        if '[ERROR]' in output or '[SSH ERROR]' in output:
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
