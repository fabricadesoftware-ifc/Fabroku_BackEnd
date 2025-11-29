from abc import abstractmethod


class DokkuLetsencryptMixin:
    """Mixin for Dokku Let's Encrypt functionality."""

    @abstractmethod
    def _run_command(self, command: str) -> str:
        """Run a Dokku command."""
        ...

    def active_letsencrypt(self, app_name: str) -> str:
        """Activate Let's Encrypt for a Dokku application."""
        return self._run_command(f'letsencrypt:active {app_name}')

    def disable_letsencrypt(self, app_name: str) -> str:
        """Deactivate Let's Encrypt for a Dokku application."""
        return self._run_command(f'letsencrypt:disable {app_name}')

    def enable_letsencrypt(self, app_name: str) -> str:
        """Enable Let's Encrypt for a Dokku application."""
        return self._run_command(f'letsencrypt:enable {app_name}')

    def set_property_letsencrypt(self, property_name: str, value: str) -> str:
        """Set a Let's Encrypt property."""
        return self._run_command(f'letsencrypt:set {property_name} {value}')

    def list_letsencrypt(self) -> str:
        """List Let's Encrypt information for all Dokku applications."""
        return self._run_command('letsencrypt:list')
