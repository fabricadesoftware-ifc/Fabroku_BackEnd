from abc import abstractmethod


class DokkuAppsMixin:
    """Mixin que fornece métodos para gerenciar aplicações no Dokku."""
    @abstractmethod
    def _run_command(self, command: str) -> str:
        """Executa um comando no servidor Dokku."""
        ...

    def create_app(self, app_name: str) -> str:
        """Cria uma nova aplicação no Dokku."""
        return self._run_command(f"dokku apps:create {app_name}")

    def delete_app(self, app_name: str) -> str:
        """Deleta uma aplicação do Dokku (força a deleção)."""
        return self._run_command(f"dokku apps:destroy {app_name} --force")

    def report_app(self, app_name: str) -> str:
        """Exibe relatório detalhado de uma aplicação."""
        return self._run_command(f"dokku apps:report {app_name}")

    def get_apps(self) -> str:
        """Lista todas as aplicações do Dokku."""
        return self._run_command("dokku apps:list")

    def clone_app(self, source_app: str, new_app: str) -> str:
        """Clona uma aplicação existente."""
        return self._run_command(f"dokku apps:clone {source_app} {new_app}")

    def exists_app(self, app_name: str) -> str:
        """Verifica se uma aplicação existe."""
        return self._run_command(f"dokku apps:exists {app_name}")

    def lock_app(self, app_name: str) -> str:
        """Bloqueia uma aplicação (previne deploys)."""
        return self._run_command(f"dokku apps:lock {app_name}")

    def unlock_app(self, app_name: str) -> str:
        """Desbloqueia uma aplicação."""
        return self._run_command(f"dokku apps:unlock {app_name}")

    def rename_app(self, old_name: str, new_name: str) -> str:
        """Renomeia uma aplicação."""
        return self._run_command(f"dokku apps:rename {old_name} {new_name}")
