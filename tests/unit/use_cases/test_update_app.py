"""Unit tests for UpdateAppUseCase, using fake ports (no SSH)."""
import pytest

from applications.domain.exceptions import DeploymentFailed
from applications.models import AppStatus
from applications.use_cases.update_app import AppUpdated, UpdateAppCommand, UpdateAppUseCase
from tests.factories.models import AppFactory, ProjectFactory
from tests.fakes import FakeDokkuPort

pytestmark = pytest.mark.django_db


def make_use_case(dokku=None):
    dokku = dokku or FakeDokkuPort()
    return UpdateAppUseCase(dokku_port=dokku), dokku


def test_update_app_rename():
    project = ProjectFactory()
    app = AppFactory(project=project, name='old-name', name_dokku='old-name', git='https://github.com/o/r.git')
    use_case, dokku = make_use_case()
    dokku.create_app('old-name')

    result = use_case.execute(UpdateAppCommand(app_id=app.id, name='new-name'))

    assert isinstance(result, AppUpdated)
    assert result.dokku_app_name == 'new-name'
    app.refresh_from_db()
    assert app.name == 'new-name'
    assert app.name_dokku == 'new-name'
    assert app.status == AppStatus.RUNNING
    assert 'new-name' in dokku.apps
    assert 'old-name' not in dokku.apps


def test_update_app_git_url():
    project = ProjectFactory()
    app = AppFactory(project=project, name='my-app', name_dokku='my-app', git='https://github.com/o/old.git')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')

    use_case.execute(UpdateAppCommand(app_id=app.id, git_url='https://github.com/o/new.git'))

    app.refresh_from_db()
    assert app.git == 'https://github.com/o/new.git'
    assert dokku.apps['my-app']['git_url'] == 'https://github.com/o/new.git'


def test_update_app_env_vars():
    project = ProjectFactory()
    app = AppFactory(project=project, name='my-app', name_dokku='my-app')
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')

    use_case.execute(UpdateAppCommand(app_id=app.id, env_vars={'FOO': 'bar'}))

    app.refresh_from_db()
    assert app.variables == {'FOO': 'bar'}
    assert dokku.apps['my-app']['env_vars'] == {'FOO': 'bar'}


def test_update_app_without_name_dokku_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku=None)
    use_case, _dokku = make_use_case()

    with pytest.raises(DeploymentFailed):
        use_case.execute(UpdateAppCommand(app_id=app.id, name='new-name'))


def test_update_app_no_changes_is_a_noop_besides_status():
    project = ProjectFactory()
    app = AppFactory(project=project, name='my-app', name_dokku='my-app', status=AppStatus.RUNNING)
    use_case, dokku = make_use_case()
    dokku.create_app('my-app')
    dokku.clear_logs()

    use_case.execute(UpdateAppCommand(app_id=app.id))

    assert dokku.get_calls() == []
    app.refresh_from_db()
    assert app.status == AppStatus.RUNNING
