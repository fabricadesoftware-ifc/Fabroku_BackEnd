"""Port (interface) for Dokku orchestration.

Mirrors the real methods already implemented by the `dokku_mixins/` that
`DokkuAdapter` composes, so `DokkuAdapter` satisfies this interface without
any bridging code. Postgres/Redis service-lifecycle methods were added in
Fase 4 as the use cases that actually call them (DeleteAppUseCase and the
service_mgmt use cases) were ported. `open_interactive_channel` was added in
ADJUSTS_REFACTOR.md's Fase E to isolate the raw paramiko PTY tunnel used by
live interactive terminal sessions (Django createsuperuser / postgres
connect) behind this port, same as every other Dokku operation.
"""
from abc import ABC, abstractmethod
from typing import Callable, Generator, Protocol


class InteractiveChannel(Protocol):
    """A duplex PTY channel for an interactive command, running to completion.

    Structural (not nominal) — anything with this shape works, so the fake
    used in tests doesn't need to import/subclass this. Mirrors exactly the
    paramiko operations `core/apps/mixins/apps/interactive_run.py` used to
    perform directly: read whatever output is currently buffered (empty
    string if none), write raw input, and poll for process completion.
    """

    def settimeout(self, timeout: float) -> None:
        """Set the timeout (seconds) for `read_output()` reads."""

    def write(self, data: str) -> None:
        """Write raw data to the remote process's stdin."""

    def read_output(self) -> str:
        """Return whatever stdout/stderr output is currently available (possibly empty)."""

    def exit_status_ready(self) -> bool:
        """Return True once the remote process has exited."""

    def exit_status(self) -> int:
        """Block until the remote process's exit status is available, then return it."""

    def close(self) -> None:
        """Release the underlying SSH connection."""


class IDokkuPort(ABC):
    """Interface for Dokku operations."""

    @abstractmethod
    def create_app(self, app_name: str) -> str:
        """Create a new app in Dokku."""

    @abstractmethod
    def delete_app(self, app_name: str) -> str:
        """Delete an app from Dokku."""

    @abstractmethod
    def exists_app(self, app_name: str) -> bool:
        """Check whether an app already exists in Dokku."""

    @abstractmethod
    def rename_app(self, old_name: str, new_name: str) -> str:
        """Rename an app in Dokku."""

    @abstractmethod
    def start_app(self, app_name: str) -> str:
        """Start an app."""

    @abstractmethod
    def stop_app(self, app_name: str) -> str:
        """Stop an app."""

    @abstractmethod
    def restart_app(self, app_name: str) -> str:
        """Restart an app."""

    @abstractmethod
    def get_app_status(self, app_name: str) -> str:
        """Get current status of an app (running, stopped, error, etc)."""

    @abstractmethod
    def sync_git_streaming(
        self,
        app_name: str,
        git_url: str,
        branch: str = 'main',
        on_line: Callable[[str], None] | None = None,
    ) -> str:
        """Sync (and build/deploy) an app's Git repository, streaming output lines via on_line."""

    @abstractmethod
    def set_git_remote(self, app_name: str, git_url: str) -> str:
        """Configure the Git remote for an app without triggering a build."""

    @abstractmethod
    def set_config(self, app_name: str, env_vars: dict[str, str], no_restart: bool = False) -> str:
        """Set one or more environment variables for an app."""

    @abstractmethod
    def unset_config(self, app_name: str, keys: list[str], no_restart: bool = False) -> str:
        """Remove one or more environment variables from an app."""

    @abstractmethod
    def get_config(self, app_name: str, key: str) -> str:
        """Get a single environment variable's value for an app."""

    @abstractmethod
    def show_config(self, app_name: str) -> str:
        """Get the raw dokku config:show output for an app."""

    @abstractmethod
    def get_app_domain(self, app_name: str) -> str | None:
        """Get the domain currently configured for an app."""

    @abstractmethod
    def enable_letsencrypt(self, app_name: str) -> str:
        """Enable Let's Encrypt TLS for an app."""

    @abstractmethod
    def run_in_app(self, app_name: str, command: str) -> str:
        """Run a one-off command in the app's container and return the full output."""

    @abstractmethod
    def run_in_app_streaming(self, app_name: str, command: str) -> Generator[str, None, int]:
        """Run a one-off command in the app's container, streaming output lines."""

    @abstractmethod
    def ps_scale(self, app_name: str, processes: dict[str, int], skip_deploy: bool = False) -> str:
        """Scale one or more process types to the given instance counts."""

    @abstractmethod
    def ps_scale_report(self, app_name: str) -> str:
        """Report the current process scale for an app."""

    @abstractmethod
    def start_database(self, db_name: str) -> str:
        """Start a linked Postgres database container (used before redeploying a dependent app)."""

    @abstractmethod
    def stop_database(self, db_name: str) -> str:
        """Stop a Postgres database container."""

    @abstractmethod
    def remove_postgres_container(self, db_name: str) -> str:
        """Force-remove a stuck Postgres container (e.g. Created state, bad hostname)."""

    @abstractmethod
    def create_database(
        self,
        db_name: str,
        password: str,
        *,
        image: str | None = None,
        image_version: str | None = None,
    ) -> str:
        """Create a new Postgres database container."""

    @abstractmethod
    def delete_database(self, db_name: str) -> str:
        """Delete a Postgres database container."""

    @abstractmethod
    def link_database(
        self, db_name: str, app_name: str, no_restart: bool = False, alias: str | None = None
    ) -> str:
        """Link a Postgres database to an app, exposing its connection URL as an env var."""

    @abstractmethod
    def unlink_database(self, db_name: str, app_name: str) -> str:
        """Unlink a Postgres database from an app."""

    @abstractmethod
    def promote_database(self, db_name: str, app_name: str) -> str:
        """Promote a linked Postgres database to be the app's primary DATABASE_URL."""

    @abstractmethod
    def enable_postgis(self, db_name: str) -> str:
        """Enable and verify the PostGIS extension on a Postgres database."""

    @abstractmethod
    def create_redis(self, service_name: str) -> str:
        """Create a new Redis instance."""

    @abstractmethod
    def delete_redis(self, service_name: str) -> str:
        """Delete a Redis instance."""

    @abstractmethod
    def link_redis(
        self, service_name: str, app_name: str, no_restart: bool = False, alias: str | None = None
    ) -> str:
        """Link a Redis instance to an app, exposing its connection URL as an env var."""

    @abstractmethod
    def unlink_redis(self, service_name: str, app_name: str) -> str:
        """Unlink a Redis instance from an app."""

    @abstractmethod
    def start_redis(self, service_name: str) -> str:
        """Start a Redis instance."""

    @abstractmethod
    def open_interactive_channel(self, command: str) -> InteractiveChannel:
        """Open a duplex PTY channel to run `command` interactively (get_pty=True equivalent).

        Used for live terminal sessions (Django createsuperuser / postgres connect) that need
        to read partial output and write input before the command finishes, unlike every other
        method on this port which runs a command to completion and returns its full output.
        """
