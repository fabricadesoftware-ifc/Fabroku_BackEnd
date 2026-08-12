"""End-to-end test of CreateAppUseCase against real adapters (DokkuAdapter, GitHubAdapter)
and a real database — no fakes. Skipped unless real Dokku/GitHub credentials are configured;
CI and default `pytest` runs never touch real infrastructure.

Run explicitly with:

    pytest tests/integration/test_create_app_e2e.py -m integration
"""
import uuid

import pytest
from django.conf import settings

from applications.models import App, AppStatus
from applications.use_cases.create_app import CreateAppCommand, CreateAppUseCase
from infrastructure.adapters.dokku import DokkuAdapter
from infrastructure.adapters.github import GitHubAdapter
from observability.models import AppLogManager
from tests.factories.models import AppFactory, ProjectFactory, UserFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

requires_real_infra = pytest.mark.skipif(
    not settings.DOKKU_SSH_KEY or not settings.GITHUB_CLIENT_SECRET,
    reason='DOKKU_SSH_KEY/GITHUB_CLIENT_SECRET not configured — no real infra to test against',
)


@requires_real_infra
def test_create_app_end_to_end_provisions_real_dokku_app():
    """Requires GIT_TOKEN_FOR_E2E_TESTS env-configured user with access to a real public repo."""
    user = UserFactory()
    project = ProjectFactory(users=[user])
    app = AppFactory(
        project=project,
        name=f'e2e-{uuid.uuid4().hex[:8]}',
        git='https://github.com/octocat/Hello-World.git',
        branch='master',
    )

    use_case = CreateAppUseCase(
        dokku_port=DokkuAdapter(),
        github_port=GitHubAdapter(),
        log_manager=AppLogManager(app, task_id='e2e-test'),
    )

    try:
        result = use_case.execute(CreateAppCommand(app_id=app.id, user_id=user.id))
        assert result.status == 'created'

        app.refresh_from_db()
        assert app.status == AppStatus.RUNNING
        assert app.name_dokku
    finally:
        dokku = DokkuAdapter()
        if app.name_dokku and dokku.exists_app(app.name_dokku):
            dokku.delete_app(app.name_dokku)
        App.objects.filter(id=app.id).delete()
