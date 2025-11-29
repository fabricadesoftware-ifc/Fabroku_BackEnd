from abc import abstractmethod
from typing import Dict


class DokkuConfigMixin:

    @abstractmethod
    def _run_command(self, command: str) -> str:
        """Executa um comando no servidor Dokku."""
        ...

    def set_config(self, app_name: str, env_vars: Dict[str, str]) -> bool:

        for key, value in env_vars.items():
            if not self._run_command(f'config:set {app_name} {key}="{value}"'):
                return False
        return True

    def unset_config(self, app_name: str, keys: Dict[str, str]) -> bool:

        for key in keys:
            if not self._run_command(f'config:unset {app_name} {key}'):
                return False
        return True

    def show_config(self, app_name: str) -> str:
        """Exibe todas as configurações de uma aplicação."""
        return self._run_command(f"config:show {app_name}")
