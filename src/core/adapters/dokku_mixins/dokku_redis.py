from abc import abstractmethod


class DokkuRedisMixin:
    """Mixin que fornece métodos para integração Redis com Dokku."""

    @abstractmethod
    def _run_command(self, command: str) -> str:
        """Executa um comando no servidor Dokku."""
        ...

    def create_redis(self, service_name: str) -> str:
        """Cria uma instância do serviço Redis."""
        return self._run_command(f'redis:create {service_name}')

    def delete_redis(self, service_name: str) -> str:
        """Deleta uma instância do serviço Redis."""
        return self._run_command(f'redis:destroy {service_name} --force')

    def link_redis(self, service_name: str, app_name: str, no_restart: bool = False) -> str:
        """Vincula uma instância do Redis a uma aplicação Dokku."""
        flags = ' --no-restart' if no_restart else ''
        return self._run_command(f'redis:link {service_name} {app_name}{flags}')

    def unlink_redis(self, service_name: str, app_name: str) -> str:
        """Desvincula uma instância do Redis de uma aplicação Dokku."""
        return self._run_command(f'redis:unlink {service_name} {app_name}')

    def list_redis(self) -> str:
        """Lista todas as instâncias do serviço Redis."""
        return self._run_command('redis:list')

    def info_redis(self, service_name: str) -> str:
        """Exibe informações sobre uma instância específica do Redis."""
        return self._run_command(f'redis:info {service_name}')

    def export_redis(self, service_name: str, output_file: str) -> str:
        """Exporta os dados de uma instância do Redis para um arquivo."""
        return self._run_command(f'redis:export {service_name} {output_file}')

    def import_redis(self, service_name: str, input_file: str) -> str:
        """Importa os dados de uma instância do Redis a partir de um arquivo."""
        return self._run_command(f'redis:import {service_name} {input_file}')

    def start_redis(self, service_name: str) -> str:
        """Inicia uma instância do serviço Redis."""
        return self._run_command(f'redis:start {service_name}')

    def stop_redis(self, service_name: str) -> str:
        """Para uma instância do serviço Redis."""
        return self._run_command(f'redis:stop {service_name}')

    def restart_redis(self, service_name: str) -> str:
        """Reinicia uma instância do serviço Redis."""
        return self._run_command(f'redis:restart {service_name}')

    def expose_redis(self, service_name: str, port: int) -> str:
        """Exibe uma instância do serviço Redis em uma porta específica."""
        return self._run_command(f'redis:expose {service_name} {port}')
