from abc import abstractmethod


class DokkuLetsencryptMixin:
    """Mixin for Dokku Let's Encrypt functionality."""

    @abstractmethod
    def run_command(self, command: str) -> bool:
        """Run a Dokku command."""
        ...

    def active_letsencrypt(self, app_name: str) -> bool:
        """Activate Let's Encrypt for a Dokku application."""
        return self.run_command(f"dokku letsencrypt:active {app_name}")

    def disable_letsencrypt(self, app_name: str) -> bool:
        """Deactivate Let's Encrypt for a Dokku application."""
        return self.run_command(f"dokku letsencrypt:disable {app_name}")

    def enable_letsencrypt(self) -> bool:
        """Enable Let's Encrypt globally on Dokku."""
        return self.run_command("dokku letsencrypt:enable")

    def set_property_letsencrypt(self, property_name: str, value: str) -> bool:
        """Set a Let's Encrypt property."""
        return self.run_command(f"dokku letsencrypt:set {property_name} {value}")

    def list_letsencrypt(self,) -> bool:
        """list Let's Encrypt information for a Dokku application."""
        return self.run_command("dokku letsencrypt:list")
