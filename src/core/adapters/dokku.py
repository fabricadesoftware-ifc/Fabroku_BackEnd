from core.adapters.ssh import SSHAdapter
from typing import Dict


class DokkuSSHAdapter(SSHAdapter):


    def _run_command(self, command: str) -> bool:
        return super()._run_command(command)

    #apps
    def create_app(self, app_name: str) -> bool:
        return self._run_command(f"dokku apps:create {app_name}")

    def delete_app(self, app_name: str) -> bool:
        return self._run_command(f"dokku apps:destroy {app_name} --force")

    def report_app(self, app_name: str) -> bool:
        return self._run_command(f"dokku apps:report {app_name}")

    def get_apps(self) -> bool:
        return self._run_command("dokku apps:list")

    def clone_app(self, source_app: str, new_app: str) -> bool:
        return self._run_command(f"dokku apps:clone {source_app} {new_app}")

    def exists_app(self, app_name: str) -> bool:
        return self._run_command(f"dokku apps:exists {app_name}")

    def lock_app(self, app_name: str) -> bool:
        return self._run_command(f"dokku apps:lock {app_name}")

    def unlock_app(self, app_name: str) -> bool:
        return self._run_command(f"dokku apps:unlock {app_name}")

    def rename_app(self, old_name: str, new_name: str) -> bool:
        return self._run_command(f"dokku apps:rename {old_name} {new_name}")

    #config
    def set_config(self, app_name: str, env_vars: Dict[str, str]) -> bool:
        for key, value in env_vars.items():
            command = f'dokku config:set {app_name} {key}="{value}"'
            if not self._run_command(command):
                return False
        return True

    def show_config(self, app_name: str) -> bool:
        return self._run_command(f"dokku config:show {app_name}")

    #git
    # TODO:integrar com git para ver repositiorios privados e websocket
    def sync_git(self, app_name: str, git_url: str, branch: str = "main") -> str:
        clone_command = f"git clone -b {branch} {git_url} /tmp/{app_name}"
        push_command = f"cd /tmp/{app_name} && git push dokku {branch}:master"

        if not self._run_command(clone_command):
            return "Failed to clone repository."

        if not self._run_command(push_command):
            return "Failed to push to Dokku."

        return "Git sync successful."




