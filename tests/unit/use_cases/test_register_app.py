"""Unit tests for RegisterAppUseCase — pure DB, no adapters/fakes needed."""
import pytest
from django.utils import timezone

from applications.domain.exceptions import AppLimitExceeded, AppNameConflict
from applications.models import App, AppStatus
from applications.use_cases.register_app import RegisterAppCommand, RegisterAppUseCase
from tests.factories.models import AppFactory, ProjectFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_register_app_success():
    user = UserFactory()
    project = ProjectFactory(users=[user])
    use_case = RegisterAppUseCase()

    app = use_case.execute(
        RegisterAppCommand(
            user_id=user.id,
            project_id=str(project.id),
            app_name='my-new-app',
            git_url='https://github.com/owner/repo.git',
        )
    )

    assert app.pk is not None
    assert app.name == 'my-new-app'
    assert app.status == AppStatus.STARTING
    assert App.objects.filter(id=app.id).exists()


def test_register_app_exceeds_limit():
    user = UserFactory()
    project = ProjectFactory(users=[user])
    AppFactory.create_batch(user.DEFAULT_MAX_APPS, project=project)
    use_case = RegisterAppUseCase()

    with pytest.raises(AppLimitExceeded) as exc_info:
        use_case.execute(
            RegisterAppCommand(
                user_id=user.id,
                project_id=str(project.id),
                app_name='one-too-many',
                git_url='https://github.com/owner/repo.git',
            )
        )

    assert exc_info.value.current == user.DEFAULT_MAX_APPS
    assert exc_info.value.limit == user.DEFAULT_MAX_APPS
    assert not App.objects.filter(name='one-too-many').exists()


def test_register_app_name_conflict():
    user = UserFactory()
    project = ProjectFactory(users=[user])
    AppFactory(project=project, name='taken-name')
    use_case = RegisterAppUseCase()

    with pytest.raises(AppNameConflict):
        use_case.execute(
            RegisterAppCommand(
                user_id=user.id,
                project_id=str(project.id),
                app_name='taken-name',
                git_url='https://github.com/owner/repo.git',
            )
        )


def test_register_app_name_conflict_is_case_insensitive():
    user = UserFactory()
    project = ProjectFactory(users=[user])
    AppFactory(project=project, name='Taken-Name')
    use_case = RegisterAppUseCase()

    with pytest.raises(AppNameConflict):
        use_case.execute(
            RegisterAppCommand(
                user_id=user.id,
                project_id=str(project.id),
                app_name='taken-name',
                git_url='https://github.com/owner/repo.git',
            )
        )


def test_register_app_ignores_soft_deleted_name_conflicts():
    user = UserFactory()
    project = ProjectFactory(users=[user])
    AppFactory(project=project, name='reusable-name', deleted_at=timezone.now())
    use_case = RegisterAppUseCase()

    app = use_case.execute(
        RegisterAppCommand(
            user_id=user.id,
            project_id=str(project.id),
            app_name='reusable-name',
            git_url='https://github.com/owner/repo.git',
        )
    )

    assert app.pk is not None
