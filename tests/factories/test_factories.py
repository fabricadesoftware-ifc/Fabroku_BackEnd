"""Smoke tests verifying that test factories build valid, persistable model instances."""
import pytest

from tests.factories.models import (
    AppFactory,
    AppProcessScaleFactory,
    CLITokenFactory,
    ProjectFactory,
    ServiceFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def test_user_factory_creates_user():
    user = UserFactory()
    assert user.pk is not None
    assert user.email


def test_project_factory_creates_project_with_user():
    project = ProjectFactory()
    assert project.pk is not None
    assert project.users.count() == 1


def test_app_factory_creates_app():
    app = AppFactory()
    assert app.pk is not None
    assert app.project_id is not None


def test_service_factory_creates_service_linked_to_app_project():
    service = ServiceFactory()
    assert service.pk is not None
    assert service.project_id == service.app.project_id


def test_app_process_scale_factory_creates_scale():
    scale = AppProcessScaleFactory()
    assert scale.pk is not None
    assert scale.app_id is not None


def test_cli_token_factory_generates_token():
    token = CLITokenFactory()
    assert token.pk is not None
    assert token.token
