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

        # Parseia o relatório linha por linha
        app_vhosts = None
        global_vhosts = None

        for raw_line in report.split('\n'):
            line = raw_line.strip()

            # Procura por "Domains app vhosts:" e extrai o valor após
            if line.startswith('Domains app vhosts:'):
                # Remove o prefixo e pega o valor
                value = line.replace('Domains app vhosts:', '').strip()
                if value:
                    app_vhosts = value.split()[0]  # Pega o primeiro domínio

            # Procura por "Domains global vhosts:" e extrai o valor após
            elif line.startswith('Domains global vhosts:'):
                value = line.replace('Domains global vhosts:', '').strip()
                if value:
                    global_vhosts = value.split()[0]  # Pega o primeiro domínio

        # Prioriza app vhosts, depois global vhosts
        return app_vhosts or global_vhosts
