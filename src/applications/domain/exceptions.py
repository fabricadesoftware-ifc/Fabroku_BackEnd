"""Domain exceptions for applications context.

These exceptions are raised by use cases and represent domain-level errors.
They are mapped to HTTP responses by the exception handler in config/exceptions.py
"""


class ApplicationDomainError(Exception):
    """Base exception for all application domain errors."""
    pass


class AppLimitExceeded(ApplicationDomainError):
    """User has reached the maximum number of apps allowed by their quota."""

    def __init__(self, current: int, limit: int):
        self.current = current
        self.limit = limit
        super().__init__(
            f'App limit exceeded: {current} apps created, limit is {limit}'
        )


class AppNameConflict(ApplicationDomainError):
    """An app with this name already exists."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f'App name already exists: {name}')


class AppNotFound(ApplicationDomainError):
    """App does not exist or user does not have access."""

    def __init__(self, app_id: int | str):
        self.app_id = app_id
        super().__init__(f'App not found: {app_id}')


class DeploymentFailed(ApplicationDomainError):
    """Deployment operation failed at a specific step."""

    def __init__(self, reason: str, step: str):
        self.reason = reason
        self.step = step
        super().__init__(f'Deployment failed at {step}: {reason}')


class InfrastructureError(ApplicationDomainError):
    """Error from external infrastructure (Dokku, GitHub, SSH)."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(f'Infrastructure error: {message}' + (f' ({details})' if details else ''))


class ServiceLimitExceeded(ApplicationDomainError):
    """User has reached the maximum number of services allowed by their quota."""

    def __init__(self, current: int, limit: int):
        self.current = current
        self.limit = limit
        super().__init__(
            f'Service limit exceeded: {current} services created, limit is {limit}'
        )


class ServiceNotFound(ApplicationDomainError):
    """Service does not exist or app does not have access."""

    def __init__(self, service_id: int | str):
        self.service_id = service_id
        super().__init__(f'Service not found: {service_id}')


class InvalidEnvVar(ApplicationDomainError):
    """Environment variable does not meet domain constraints."""

    def __init__(self, key: str, reason: str):
        self.key = key
        self.reason = reason
        super().__init__(f'Invalid environment variable {key}: {reason}')


class GitError(ApplicationDomainError):
    """Error with Git operations (clone, pull, sync)."""

    def __init__(self, message: str, git_url: str | None = None):
        self.message = message
        self.git_url = git_url
        super().__init__(f'Git error: {message}' + (f' for {git_url}' if git_url else ''))
