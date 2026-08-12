"""Factory fixtures for tests."""
import pytest

from tests.factories.models import (
    AppFactory,
    AppProcessScaleFactory,
    CLITokenFactory,
    ProjectFactory,
    ServiceFactory,
    UserFactory,
)


@pytest.fixture
def user_factory():
    return UserFactory


@pytest.fixture
def project_factory():
    return ProjectFactory


@pytest.fixture
def app_factory():
    return AppFactory


@pytest.fixture
def service_factory():
    return ServiceFactory


@pytest.fixture
def app_process_scale_factory():
    return AppProcessScaleFactory


@pytest.fixture
def cli_token_factory():
    return CLITokenFactory
