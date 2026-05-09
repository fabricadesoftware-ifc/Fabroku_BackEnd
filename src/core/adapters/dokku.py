from django.conf import settings

from core.adapters.dokku_mixins import (
    DokkuAppsMixin,
    DokkuConfigMixin,
    DokkuDomainsMixin,
    DokkuGitMixin,
    DokkuLetsencryptMixin,
    DokkuPortsMixin,
    DokkuPostgresMixin,
    DokkuPsMixin,
    DokkuRedisMixin,
    DokkuRunMixin,
)
from core.adapters.ssh import SSHAdapter


class DokkuAdapter(
    SSHAdapter,
    DokkuAppsMixin,
    DokkuConfigMixin,
    DokkuGitMixin,
    DokkuPostgresMixin,
    DokkuRedisMixin,
    DokkuPsMixin,
    DokkuPortsMixin,
    DokkuLetsencryptMixin,
    DokkuDomainsMixin,
    DokkuRunMixin,
):
    def __init__(
        self,
    ):
        self.host = settings.DOKKU_SSH_HOST
        self.username = settings.DOKKU_SSH_USERNAME
        self.ssh_key_path = settings.DOKKU_SSH_KEY
        self.port = settings.DOKKU_SSH_PORT
        super().__init__(self.host, self.username, self.ssh_key_path, self.port)

    def _run_command(self, command: str) -> str:
        """Executa comando via SSH no servidor Dokku."""
        return super()._run_command(command)
