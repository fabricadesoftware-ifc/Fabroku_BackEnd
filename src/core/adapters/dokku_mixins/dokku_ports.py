from abc import abstractmethod


class DokkuPortsMixin:
    @abstractmethod
    def _run_command(self, command: str) -> str:
        """Executa um comando no servidor Dokku."""
        ...

    def set_port(self, app_name: str, port_out: int = 80, port_in: int = 5000, protocol: str = 'http') -> bool:
        """Define a porta para a aplicação Dokku."""
        result = self._run_command(f'ports:set {app_name} {protocol}:{port_out}:{port_in} --no-restart')
        return 'OK' in result

    def unset_port(self, app_name: str, port: int, protocol: str = 'http') -> bool:
        """Remove uma porta da aplicação Dokku."""
        result = self._run_command(f'ports:unset {app_name} {protocol}:{port} --no-restart')
        return 'OK' in result

    def add_port(self, app_name: str, port_out: int = 80, port_in: int = 5000, protocol: str = 'http') -> bool:
        """Adiciona uma porta mapeada para a aplicação Dokku."""
        result = self._run_command(f'ports:add {app_name} {protocol}:{port_out}:{port_in} --no-restart')
        return 'OK' in result

    def list_ports(self, app_name: str) -> str:
        """Lista todas as portas mapeadas para a aplicação Dokku."""
        return self._run_command(f'ports:list {app_name}')
