from abc import abstractmethod
from typing import Dict


class DokkuConfigMixin:
    @abstractmethod
    def _run_command(self, command: str) -> str:
        """Executa um comando no servidor Dokku."""
        ...

    def set_config(self, app_name: str, env_vars: Dict[str, str]) -> str:
        """Configura variáveis de ambiente para uma aplicação."""
        outputs = []
        for key, value in env_vars.items():
            output = self._run_command(f'config:set {app_name} {key}="{value}"')
            outputs.append(f'{key}: {output}')
        return '\n'.join(outputs)

    def unset_config(self, app_name: str, keys: list[str]) -> str:
        """Remove variáveis de ambiente de uma aplicação."""
        outputs = []
        for key in keys:
            output = self._run_command(f'config:unset {app_name} {key}')
            outputs.append(f'{key}: {output}')
        return '\n'.join(outputs)

    def show_config(self, app_name: str) -> str:
        """Exibe todas as configurações de uma aplicação."""
        return self._run_command(f'config:show {app_name}')

    def get_config(self, app_name: str, key: str) -> str:
        """Obtém o valor de uma variável de ambiente específica."""
        return self._run_command(f'config:get {app_name} {key}').strip()
