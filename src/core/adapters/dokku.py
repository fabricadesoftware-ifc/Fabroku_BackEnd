from core.adapters.mixins import DokkuAppsMixin, DokkuConfigMixin, DokkuGitMixin, DokkuPostgresMixin
from core.adapters.ssh import SSHAdapter


class DokkuSSHAdapter(SSHAdapter, DokkuAppsMixin, DokkuConfigMixin, DokkuGitMixin, DokkuPostgresMixin):
    def _run_command(self, command: str) -> bool:
        """Executa comando via SSH no servidor Dokku."""
        return super()._run_command(command)
