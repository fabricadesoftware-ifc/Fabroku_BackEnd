from abc import abstractmethod


class DokkuGitMixin():
    """Mixin que fornece métodos para integração Git com Dokku."""

    @abstractmethod
    def _run_command(self, command: str) -> bool:
        """Executa um comando no servidor Dokku."""
        ...

    @abstractmethod
    def exists_app(self, app_name: str) -> bool:
        """Verifica se uma aplicação existe."""
        ...

    def sync_git(self, app_name: str, git_url: str, branch: str = "main") -> str:
        """Sincroniza repositório Git com aplicação Dokku."""
        if not self.exists_app(app_name):
            return "Application not found."

        deploy_command = f"dokku git:sync {app_name} {git_url} --branch {branch}"

        if not self._run_command(deploy_command):
            return "Failed to sync Git repository and deploy."

        return "Git sync successful."
