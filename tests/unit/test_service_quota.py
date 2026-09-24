"""Regression tests: services_count/can_create_service must count services a user
created, never services a teammate created in a project they merely share."""
import pytest

from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_services_count_ignores_teammates_services_in_shared_project():
    owner = UserFactory()
    teammate = UserFactory()
    project = ProjectFactory(users=[owner, teammate])
    app = AppFactory(project=project, created_by=owner)
    ServiceFactory.create_batch(3, project=project, app=app, created_by=owner)

    assert owner.services_count == 3  # noqa: PLR2004
    assert teammate.services_count == 0


def test_can_create_service_not_blocked_by_teammates_services():
    owner = UserFactory()
    teammate = UserFactory()
    project = ProjectFactory(users=[owner, teammate])
    app = AppFactory(project=project, created_by=owner)
    ServiceFactory.create_batch(owner.max_services, project=project, app=app, created_by=owner)

    assert owner.can_create_service() is False
    assert teammate.can_create_service() is True


def test_services_count_ignores_soft_deleted_services():
    owner = UserFactory()
    project = ProjectFactory(users=[owner])
    app = AppFactory(project=project, created_by=owner)
    ServiceFactory(project=project, app=app, created_by=owner)
    deleted_service = ServiceFactory(project=project, app=app, created_by=owner)
    deleted_service.soft_delete()

    assert owner.services_count == 1
