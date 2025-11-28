from abc import abstractmethod


class DokkuGitMixin():
    """Mixin que fornece métodos para integração Git com Dokku."""

    @abstractmethod
    def _run_command(self, command: str) -> str:
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

        if not self._run_command(f"dokku git:sync {app_name} {git_url} --branch {branch}"):
            return "Failed to sync Git repository and deploy."

        return "Git sync successful."

    def set_git_remote(self, app_name: str, git_url: str) -> str:
        """Configura o repositório Git remoto para a aplicação Dokku."""
        if not self.exists_app(app_name):
            return "Application not found."

        if not self._run_command(f"dokku git:remote-add {app_name} {git_url}"):
            return "Failed to set Git remote."

        return "Git remote set successfully."

    def remove_git_remote(self, app_name: str) -> str:
        """Remove o repositório Git remoto da aplicação Dokku."""
        if not self.exists_app(app_name):
            return "Application not found."

        if not self._run_command(f"dokku git:remote-remove {app_name}"):
            return "Failed to remove Git remote."

        return "Git remote removed successfully."

    def generate_git_deploy_key(self) -> str:
        """Gera uma chave de deploy Git para a aplicação Dokku."""

        if not self._run_command("dokku git:generate-deploy-key"):
            return "Failed to generate Git deploy key."

        return "Git deploy key generated successfully."

    def get_git_deploy_key(self) -> str:
        """Obtém a chave de deploy Git da aplicação Dokku."""

        deploy_key = self._run_command("dokku git:deploy-key")
        if not deploy_key:
            return "Failed to get Git deploy key."

        return str(deploy_key)
