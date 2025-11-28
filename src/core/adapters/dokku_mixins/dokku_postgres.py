from abc import abstractmethod


class DokkuPostgresMixin:
    """Mixin para gerenciar bancos de dados PostgreSQL no Dokku via SSH."""

    @abstractmethod
    def _run_command(self, command: str) -> bool:
        """Executa um comando no servidor Dokku."""
        ...

    def create_database(self, db_name: str) -> bool:
        """Cria um novo banco de dados PostgreSQL no Dokku."""
        return self._run_command(f"dokku postgres:create {db_name}")

    def delete_database(self, db_name: str) -> bool:
        """Deleta um banco de dados PostgreSQL do Dokku."""
        return self._run_command(f"dokku postgres:destroy {db_name} --force")

    def link_database(self, db_name: str, app_name: str) -> bool:
        """Vincula um banco de dados PostgreSQL a uma aplicação Dokku."""
        return self._run_command(f"dokku postgres:link {db_name} {app_name}")

    def unlink_database(self, db_name: str, app_name: str) -> bool:
        """Desvincula um banco de dados PostgreSQL de uma aplicação Dokku."""
        return self._run_command(f"dokku postgres:unlink {db_name} {app_name}")

    def get_databases(self) -> bool:
        """Lista todos os bancos de dados PostgreSQL no Dokku."""
        return self._run_command("dokku postgres:list")

    def export_database(self, db_name: str, output_file: str) -> bool:
        """Exporta um banco de dados PostgreSQL para um arquivo."""
        return self._run_command(f"dokku postgres:export {db_name} > {output_file}")

    def import_database(self, db_name: str, input_file: str) -> bool:
        """Importa um banco de dados PostgreSQL a partir de um arquivo."""
        return self._run_command(f"dokku postgres:import {db_name} < {input_file}")

    def app_links(self, app_name: str) -> bool:
        """Lista os bancos de dados vinculados a uma aplicação Dokku."""
        return self._run_command(f"dokku postgres:app-links {app_name}")

    def pause_database(self, db_name: str) -> bool:
        """Pausa um banco de dados PostgreSQL no Dokku."""
        return self._run_command(f"dokku postgres:pause {db_name}")

    def start_database(self, db_name: str) -> bool:
        """Inicia um banco de dados PostgreSQL no Dokku."""
        return self._run_command(f"dokku postgres:start {db_name}")

    def logs_database(self, db_name: str) -> bool:
        """Exibe os logs de um banco de dados PostgreSQL no Dokku."""
        return self._run_command(f"dokku postgres:logs {db_name}")

    def expose_database(self, db_name: str, port: int) -> bool:
        """Expõe um banco de dados PostgreSQL em uma porta específica."""
        return self._run_command(f"dokku postgres:expose {db_name} {port}")

    def unexpose_database(self, db_name: str) -> bool:
        """Remove a exposição de um banco de dados PostgreSQL."""
        return self._run_command(f"dokku postgres:unexpose {db_name}")

    def clone_database(self, source_db: str, new_db: str) -> bool:
        """Clona um banco de dados PostgreSQL existente."""
        return self._run_command(f"dokku postgres:clone {source_db} {new_db}")
