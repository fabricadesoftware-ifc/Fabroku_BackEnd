"""Unit tests for the interactive-session SSH loops routed through IDokkuPort (Fase E).

Uses `FakeDokkuPort.open_interactive_channel` instead of raw paramiko, proving
`_run_interactive_command_loop`/`_run_postgres_connect_loop` only ever touch the
`InteractiveChannel` port surface (write/read_output/exit_status_ready/exit_status/close),
never paramiko directly.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from core.apps.mixins.apps.interactive_run import (
    _run_interactive_command_loop,
    _run_postgres_connect_loop,
    _set_session_prompt,
    get_interactive_driver,
    submit_interactive_session_answer,
)
from interactive_sessions.models import (
    InteractiveRunAuditDirection,
    InteractiveRunCommandKind,
    InteractiveRunSession,
    InteractiveRunSessionStatus,
)
from observability.models import AppLogManager
from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory, UserFactory
from tests.fakes import FakeDokkuPort, FakeInteractiveChannel

pytestmark = pytest.mark.django_db


def _make_session(app, command_kind, **kwargs) -> InteractiveRunSession:
    return InteractiveRunSession.objects.create(
        app=app,
        created_by=UserFactory(),
        command_kind=command_kind,
        status=InteractiveRunSessionStatus.PENDING,
        manage_path='manage.py',
        expires_at=timezone.now() + timedelta(minutes=5),
        last_activity_at=timezone.now(),
        **kwargs,
    )


def test_run_interactive_command_loop_completes_createsuperuser_flow():
    app = AppFactory(project=ProjectFactory(), name_dokku='my-app')
    session = _make_session(app, InteractiveRunCommandKind.DJANGO_CREATESUPERUSER)
    driver = get_interactive_driver(InteractiveRunCommandKind.DJANGO_CREATESUPERUSER)
    logger = AppLogManager(app, task_id='test-task')

    channel = FakeInteractiveChannel([
        'Email address: ',
        'Name: ',
        'Password: ',
        'Password (again): ',
        'Superuser created successfully.\n',
    ])
    dokku = FakeDokkuPort()
    dokku.interactive_channel_factory = lambda command: channel

    answers = iter(['admin@example.com', 'Admin', '123123Admin', '123123Admin'])

    def auto_answer(session_id, prompt_match):
        prompt_id = _set_session_prompt(session_id, prompt_match)
        submit_interactive_session_answer(session_id, prompt_id, next(answers))
        return prompt_id

    with (
        patch('core.apps.mixins.apps.interactive_run._set_session_prompt', side_effect=auto_answer),
        patch('core.apps.mixins.apps.interactive_run.time.sleep', return_value=None),
    ):
        exit_status, output_state = _run_interactive_command_loop(session, driver, dokku, logger)

    assert exit_status == 0
    assert channel.written_inputs == ['admin@example.com', 'Admin', '123123Admin', '123123Admin']
    assert channel.closed is True
    assert output_state['saw_success_output'] is True
    called_methods = [call['method'] for call in dokku.get_calls()]
    assert called_methods.count('open_interactive_channel') == 1
    assert dokku.get_calls()[0]['args']['command'] == f'run {app.name_dokku} {driver.build_command("manage.py")}'


def test_run_interactive_command_loop_reports_nonzero_exit_status():
    app = AppFactory(project=ProjectFactory(), name_dokku='my-app')
    session = _make_session(app, InteractiveRunCommandKind.DJANGO_CREATESUPERUSER)
    driver = get_interactive_driver(InteractiveRunCommandKind.DJANGO_CREATESUPERUSER)
    logger = AppLogManager(app, task_id='test-task')

    channel = FakeInteractiveChannel(['boom\n'], exit_status=1)
    dokku = FakeDokkuPort()
    dokku.interactive_channel_factory = lambda command: channel

    with patch('core.apps.mixins.apps.interactive_run.time.sleep', return_value=None):
        exit_status, _output_state = _run_interactive_command_loop(session, driver, dokku, logger)

    assert exit_status == 1
    assert channel.closed is True


def test_run_postgres_connect_loop_streams_output_and_input():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    service = ServiceFactory(app=app, project=project, container_name='my-app-postgres')
    session = _make_session(app, InteractiveRunCommandKind.POSTGRES_CONNECT, service=service)
    driver = get_interactive_driver(InteractiveRunCommandKind.POSTGRES_CONNECT)

    channel = FakeInteractiveChannel(['postgres=# '])
    dokku = FakeDokkuPort()
    dokku.interactive_channel_factory = lambda command: channel

    with patch('core.apps.mixins.apps.interactive_run.time.sleep', return_value=None):
        exit_status = _run_postgres_connect_loop(session, driver, dokku)

    assert exit_status == 0
    assert channel.closed is True
    called_methods = [call['method'] for call in dokku.get_calls()]
    assert called_methods.count('open_interactive_channel') == 1
    assert dokku.get_calls()[0]['args']['command'] == 'postgres:connect my-app-postgres'
    chunk = session.audit_chunks.get(direction=InteractiveRunAuditDirection.OUTPUT)
    assert chunk is not None
