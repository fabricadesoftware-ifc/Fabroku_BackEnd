"""Domain validators for applications context.

Pure functions that validate domain constraints without side effects.
Raise ApplicationDomainError subclasses when validation fails.
"""
import re

from applications.domain.exceptions import InvalidEnvVar

# Environment variable constraints (from core/apps/views.py)
ENV_VAR_KEY_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
ENV_VAR_MAX_KEY_LENGTH = 128
ENV_VAR_MAX_VALUE_LENGTH = 8192
ENV_VAR_MAX_ITEMS = 100

# App name constraints
APP_NAME_MIN_LENGTH = 2
APP_NAME_MAX_LENGTH = 60
APP_NAME_PATTERN = re.compile(r'^[a-z0-9\-]+$')  # lowercase alphanumeric + hyphen


def validate_app_name(name: str) -> None:
    """Validate app name according to domain rules.
    
    Args:
        name: App name to validate
        
    Raises:
        InvalidEnvVar: If name does not meet constraints
    """
    if not name:
        raise InvalidEnvVar('name', 'cannot be empty')

    if len(name) < APP_NAME_MIN_LENGTH:
        raise InvalidEnvVar('name', f'must be at least {APP_NAME_MIN_LENGTH} characters')

    if len(name) > APP_NAME_MAX_LENGTH:
        raise InvalidEnvVar('name', f'must be at most {APP_NAME_MAX_LENGTH} characters')

    if not APP_NAME_PATTERN.match(name):
        raise InvalidEnvVar('name', 'must contain only lowercase alphanumeric characters and hyphens')


def validate_env_var_key(key: str) -> None:
    """Validate environment variable key according to domain rules.
    
    Args:
        key: Environment variable key to validate
        
    Raises:
        InvalidEnvVar: If key does not meet constraints
    """
    if not key:
        raise InvalidEnvVar(key, 'key cannot be empty')

    if len(key) > ENV_VAR_MAX_KEY_LENGTH:
        raise InvalidEnvVar(key, f'key must be at most {ENV_VAR_MAX_KEY_LENGTH} characters')

    if not ENV_VAR_KEY_PATTERN.match(key):
        raise InvalidEnvVar(
            key,
            'key must start with a letter or underscore, followed by alphanumeric or underscore'
        )


def validate_env_var_value(value: str) -> None:
    """Validate environment variable value according to domain rules.
    
    Args:
        value: Environment variable value to validate
        
    Raises:
        InvalidEnvVar: If value does not meet constraints
    """
    if len(value) > ENV_VAR_MAX_VALUE_LENGTH:
        raise InvalidEnvVar('<value>', f'value must be at most {ENV_VAR_MAX_VALUE_LENGTH} characters')


def validate_env_vars(env_vars: dict[str, str]) -> None:
    """Validate entire environment variables dict according to domain rules.
    
    Args:
        env_vars: Dict of environment variables to validate
        
    Raises:
        InvalidEnvVar: If any variable does not meet constraints
    """
    if len(env_vars) > ENV_VAR_MAX_ITEMS:
        raise InvalidEnvVar('<env_vars>', f'cannot have more than {ENV_VAR_MAX_ITEMS} variables')

    for key, value in env_vars.items():
        validate_env_var_key(key)
        validate_env_var_value(value)


def validate_process_quantities(quantities: dict[str, int]) -> None:
    """Validate process scaling quantities.
    
    Args:
        quantities: Dict of process type -> instance count
        
    Raises:
        InvalidEnvVar: If any quantity is invalid
    """
    for process_type, count in quantities.items():
        if not isinstance(count, int):
            raise InvalidEnvVar(process_type, f'must be an integer, got {type(count).__name__}')

        if count < 0:
            raise InvalidEnvVar(process_type, f'cannot be negative, got {count}')

        if count > 5:
            raise InvalidEnvVar(process_type, f'cannot exceed 5 instances, got {count}')
