from typing import Dict
from abc import abstractmethod


class DokkuConfigMixin:


    @abstractmethod
    def _run_command(self, command: str) -> bool:
        """Executa um comando no servidor Dokku."""
        ...

    def set_config(self, app_name: str, env_vars: Dict[str, str]) -> bool:

        for key, value in env_vars.items():
            command = f'dokku config:set {app_name} {key}="{value}"'
            if not self._run_command(command):
                return False
        return True

    def unset_config(self, app_name: str, keys: Dict[str, str]) -> bool:

        for key in keys:
            command = f'dokku config:unset {app_name} {key}'
            if not self._run_command(command):
                return False
        return True

    def show_config(self, app_name: str) -> bool:
        """Exibe todas as configurações de uma aplicação."""
        return self._run_command(f"dokku config:show {app_name}")
