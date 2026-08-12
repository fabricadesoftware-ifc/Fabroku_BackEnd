"""Tests proving AppSerializer.create() still behaves the same after being rewired
onto RegisterAppUseCase — same success/quota-exceeded shape as before, plus two
name-conflict fixes:

1. DRF auto-generated a `UniqueValidator` for `name` from the model's partial
   `UniqueConstraint` but ignored its `condition=Q(deleted_at__isnull=True)` — it
   treated `name` as globally unique across ALL apps, including soft-deleted ones,
   permanently blocking reuse of a deleted app's name. Fixed by declaring `name`
   explicitly on the serializer (no auto-validator) and letting
   `RegisterAppUseCase` enforce the real, condition-respecting rule.
2. A conflict with an *active* app now raises a clean `ValidationError` (400) from
   `RegisterAppUseCase` instead of hitting the DB's unique constraint directly and
   crashing with an unhandled `IntegrityError` (500).

`create_app_task.delay(...)` is mocked: there's no real Celery broker in tests,
and provisioning is CreateAppUseCase's job, already covered elsewhere.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework import serializers

from applications.models import App, AppStatus
from applications.serializers import AppSerializer
from tests.factories.models import AppFactory, ProjectFactory, UserFactory

pytestmark = pytest.mark.django_db


def build_serializer(user, data):
    request = SimpleNamespace(user=user)
    return AppSerializer(data=data, context={'request': request})


@patch('applications.serializers.create_app_task')
def test_create_success_dispatches_task_and_sets_starting(mock_create_app_task):
    mock_create_app_task.delay.return_value = SimpleNamespace(id='fake-task-id')
    user = UserFactory()
    project = ProjectFactory(users=[user])

    serializer = build_serializer(
        user, {'name': 'brand-new-app', 'git': 'https://github.com/owner/repo.git', 'project': str(project.id)}
    )
    assert serializer.is_valid(), serializer.errors
    instance = serializer.save()

    assert instance.pk is not None
    assert instance.status == AppStatus.STARTING
    assert instance.task_id == 'fake-task-id'
    mock_create_app_task.delay.assert_called_once()


@patch('applications.serializers.create_app_task')
def test_create_quota_exceeded_raises_validation_error_with_same_shape_as_before(mock_create_app_task):
    user = UserFactory()
    project = ProjectFactory(users=[user])
    AppFactory.create_batch(user.DEFAULT_MAX_APPS, project=project)

    serializer = build_serializer(
        user, {'name': 'one-too-many', 'git': 'https://github.com/owner/repo.git', 'project': str(project.id)}
    )
    assert serializer.is_valid(), serializer.errors

    with pytest.raises(serializers.ValidationError) as exc_info:
        serializer.save()

    detail = exc_info.value.detail
    assert 'quota' in detail
    assert int(detail['limit']) == user.DEFAULT_MAX_APPS
    assert int(detail['current']) == user.DEFAULT_MAX_APPS
    mock_create_app_task.delay.assert_not_called()


@patch('applications.serializers.create_app_task')
def test_create_name_conflict_with_active_app_raises_validation_error_instead_of_crashing(mock_create_app_task):
    """Previously this hit the DB's unique constraint directly -> unhandled IntegrityError -> 500."""
    user = UserFactory()
    project = ProjectFactory(users=[user])
    AppFactory(project=project, name='taken-name')

    serializer = build_serializer(
        user, {'name': 'taken-name', 'git': 'https://github.com/owner/repo.git', 'project': str(project.id)}
    )
    assert serializer.is_valid(), serializer.errors

    with pytest.raises(serializers.ValidationError) as exc_info:
        serializer.save()

    assert 'name' in exc_info.value.detail
    mock_create_app_task.delay.assert_not_called()
    assert App.objects.filter(name='taken-name').count() == 1


@patch('applications.serializers.create_app_task')
def test_create_reuses_name_of_a_soft_deleted_app(mock_create_app_task):
    """Regression test for the auto-UniqueValidator bug: a deleted app's name must be reusable."""
    mock_create_app_task.delay.return_value = SimpleNamespace(id='fake-task-id')
    user = UserFactory()
    project = ProjectFactory(users=[user])
    AppFactory(project=project, name='reusable-name', deleted_at=timezone.now())

    serializer = build_serializer(
        user, {'name': 'reusable-name', 'git': 'https://github.com/owner/repo.git', 'project': str(project.id)}
    )
    assert serializer.is_valid(), serializer.errors
    instance = serializer.save()

    assert instance.pk is not None
    assert App.objects.filter(name='reusable-name', deleted_at__isnull=True).count() == 1
