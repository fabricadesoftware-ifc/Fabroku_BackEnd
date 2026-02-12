from abc import abstractmethod
from collections.abc import Generator


class DokkuRunMixin:
    """Mixin para executar comandos dentro do container de uma aplicação Dokku."""

    @abstractmethod
    def _run_command(self, command: str) -> str:
        """Executa um comando no servidor Dokku."""
        ...

    @abstractmethod
    def _run_command_streaming(self, command: str) -> Generator[str, None, int]:
        """Executa um comando SSH com streaming."""
        ...

    def run_in_app(self, app_name: str, command: str) -> str:
        """
        Executa um comando dentro do container de uma aplicação.
        Equivalente a: dokku run <app> <command>
        """
        return self._run_command(f'run {app_name} {command}')

    def run_in_app_streaming(self, app_name: str, command: str) -> Generator[str, None, int]:
        """
        Executa um comando dentro do container com streaming de output.
        Equivalente a: dokku run <app> <command>
        """
        return self._run_command_streaming(f'run {app_name} {command}')
