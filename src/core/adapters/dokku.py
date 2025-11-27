from core.adapters.ssh import SSHAdapter
from core.adapters.dokku_apps import DokkuAppsMixin
from core.adapters.dokku_config import DokkuConfigMixin
from core.adapters.dokku_git import DokkuGitMixin


class DokkuSSHAdapter(SSHAdapter, DokkuAppsMixin, DokkuConfigMixin, DokkuGitMixin):

    def _run_command(self, command: str) -> bool:
        """Executa comando via SSH no servidor Dokku."""
        return super()._run_command(command)




