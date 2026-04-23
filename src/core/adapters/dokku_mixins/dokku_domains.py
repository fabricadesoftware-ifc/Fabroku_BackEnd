from abc import abstractmethod
from typing import Dict


class DokkuDomainsMixin:
    @abstractmethod
    def _run_command(self, command: str) -> str:
        """Executa um comando no servidor Dokku."""
        ...

    def set_domain(self, app_name: str, domain: str) -> str:
        """Define o domínio para a aplicação Dokku."""
        return self._run_command(f'domains:set {app_name} {domain}')

    def unset_domain(self, app_name: str, domain: str) -> str:
        """Remove um domínio da aplicação Dokku."""
        return self._run_command(f'domains:unset {app_name} {domain}')

    def get_app_domain(self, app_name: str) -> str | None:
        """
        Obtém o domínio principal da aplicação.
        Prioriza 'app vhosts', depois 'global vhosts'.
        Retorna None se não houver domínio configurado.
        """
        report = self._run_command(f'domains:report {app_name}')

        # Parseia o relatório linha por linha — suporta tabs e espaços extras
        app_vhosts = None
        global_vhosts = None

        for raw_line in report.splitlines():
            line = raw_line.strip()

            # Suporta formato com tab: "Domains app vhosts:\t..."
            # e formato com espaço: "Domains app vhosts: ..."
            if 'app vhosts' in line and ':' in line:
                # Pega tudo após os dois pontos
                value = line.split(':', 1)[1].strip()
                if value:
                    app_vhosts = value.split()[0]

            elif 'global vhosts' in line and ':' in line:
                value = line.split(':', 1)[1].strip()
                if value:
                    global_vhosts = value.split()[0]

        # Prioriza app vhosts, depois global vhosts
        return app_vhosts or global_vhosts
