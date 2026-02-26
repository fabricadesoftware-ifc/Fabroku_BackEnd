from abc import abstractmethod


class DokkuPostgresMixin:
    """Mixin para gerenciar bancos de dados PostgreSQL no Dokku via SSH."""

    @abstractmethod
    def _run_command(self, command: str) -> str:
        """Executa um comando no servidor Dokku."""
        ...

    def create_database(self, db_name: str, password: str) -> str:
        """Cria um novo banco de dados PostgreSQL no Dokku."""
        return self._run_command(f'postgres:create {db_name} -p {password}')

    def delete_database(self, db_name: str) -> str:
        """Deleta um banco de dados PostgreSQL do Dokku."""
        return self._run_command(f'postgres:destroy {db_name} --force')

    def link_database(self, db_name: str, app_name: str, no_restart: bool = False) -> str:
        """Vincula um banco de dados PostgreSQL a uma aplicação Dokku."""
        flags = ' --no-restart' if no_restart else ''
        return self._run_command(f'postgres:link {db_name} {app_name}{flags}')

    def unlink_database(self, db_name: str, app_name: str) -> str:
        """Desvincula um banco de dados PostgreSQL de uma aplicação Dokku."""
        return self._run_command(f'postgres:unlink {db_name} {app_name}')

    def get_databases(self) -> str:
        """Lista todos os bancos de dados PostgreSQL no Dokku."""
        return self._run_command('postgres:list')

    def export_database(self, db_name: str, output_file: str) -> str:
        """Exporta um banco de dados PostgreSQL para um arquivo."""
        return self._run_command(f'postgres:export {db_name} > {output_file}')

    def import_database(self, db_name: str, input_file: str) -> str:
        """Importa um banco de dados PostgreSQL a partir de um arquivo."""
        return self._run_command(f'postgres:import {db_name} < {input_file}')

    def app_links(self, app_name: str) -> str:
        """Lista os bancos de dados vinculados a uma aplicação Dokku."""
        return self._run_command(f'postgres:app-links {app_name}')

    def pause_database(self, db_name: str) -> str:
        """Pausa um banco de dados PostgreSQL no Dokku."""
        return self._run_command(f'postgres:pause {db_name}')

    def stop_database(self, db_name: str) -> str:
        """Para um banco de dados PostgreSQL no Dokku."""
        return self._run_command(f'postgres:stop {db_name}')

    def remove_postgres_container(self, db_name: str) -> str:
        """
        Remove um container Postgres travado (ex: por hostname inválido/sethostname).
        Usado quando o container está em estado Created e não inicia.
        O volume de dados permanece; postgres:start recria o container.
        """
        container_name = f'dokku.postgres.{db_name}'
        return self._run_command(f'docker rm -f {container_name}')

    def start_database(self, db_name: str) -> str:
        """Inicia um banco de dados PostgreSQL no Dokku."""
        return self._run_command(f'postgres:start {db_name}')

    def logs_database(self, db_name: str) -> str:
        """Exibe os logs de um banco de dados PostgreSQL no Dokku."""
        return self._run_command(f'postgres:logs {db_name}')

    def expose_database(self, db_name: str, port: int) -> str:
        """Expõe um banco de dados PostgreSQL em uma porta específica."""
        return self._run_command(f'postgres:expose {db_name} {port}')

    def unexpose_database(self, db_name: str) -> str:
        """Remove a exposição de um banco de dados PostgreSQL."""
        return self._run_command(f'postgres:unexpose {db_name}')

    def clone_database(self, source_db: str, new_db: str) -> str:
        """Clona um banco de dados PostgreSQL existente."""
        return self._run_command(f'postgres:clone {source_db} {new_db}')
