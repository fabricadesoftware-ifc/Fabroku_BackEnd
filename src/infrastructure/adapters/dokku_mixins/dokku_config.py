import shlex
from abc import abstractmethod
from typing import Dict


class DokkuConfigMixin:
    @abstractmethod
    def _run_command(self, command: str) -> str:
        """Executa um comando no servidor Dokku."""
        ...

    def set_config(self, app_name: str, env_vars: Dict[str, str], no_restart: bool = False) -> str:
        """Configura variáveis de ambiente para uma aplicação."""
        if not env_vars:
            return ''

        flags = ' --no-restart' if no_restart else ''
        assignments = ' '.join(shlex.quote(f'{key}={value}') for key, value in env_vars.items())
        return self._run_command(f'config:set{flags} {shlex.quote(app_name)} {assignments}')

    def unset_config(self, app_name: str, keys: list[str], no_restart: bool = False) -> str:
        """Remove variáveis de ambiente de uma aplicação."""
        if not keys:
            return ''

        flags = ' --no-restart' if no_restart else ''
        keys_arg = ' '.join(shlex.quote(key) for key in keys)
        return self._run_command(f'config:unset{flags} {shlex.quote(app_name)} {keys_arg}')

    def show_config(self, app_name: str) -> str:
        """Exibe todas as configurações de uma aplicação."""
        return self._run_command(f'config:show {app_name}')

    def get_config(self, app_name: str, key: str) -> str:
        """Obtém o valor de uma variável de ambiente específica."""
        return self._run_command(f'config:get {app_name} {key}').strip()
