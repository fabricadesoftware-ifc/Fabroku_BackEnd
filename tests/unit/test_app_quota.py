"""Regression tests: apps_count/can_create_app must count apps a user created,
never apps a teammate created in a project they merely share."""
import pytest

from tests.factories.models import AppFactory, ProjectFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_apps_count_ignores_teammates_apps_in_shared_project():
    owner = UserFactory()
    teammate = UserFactory()
    project = ProjectFactory(users=[owner, teammate])
    AppFactory.create_batch(3, project=project, created_by=owner)

    assert owner.apps_count == 3  # noqa: PLR2004
    assert teammate.apps_count == 0


def test_can_create_app_not_blocked_by_teammates_apps():
    owner = UserFactory()
    teammate = UserFactory()
    project = ProjectFactory(users=[owner, teammate])
    AppFactory.create_batch(owner.max_apps, project=project, created_by=owner)

    assert owner.can_create_app() is False
    assert teammate.can_create_app() is True


def test_apps_count_ignores_soft_deleted_apps():
    owner = UserFactory()
    AppFactory(project=ProjectFactory(users=[owner]), created_by=owner, deleted_at=None)
    deleted_app = AppFactory(project=ProjectFactory(users=[owner]), created_by=owner)
    deleted_app.soft_delete()

    assert owner.apps_count == 1
