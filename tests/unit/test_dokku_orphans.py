"""Unit tests for the dokku_orphans management command (Dokku mocked)."""
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from applications.management.commands.dokku_orphans import parse_dokku_list
from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_parse_dokku_list_skips_headers():
    assert parse_dokku_list('=====> My Apps\nalpha\nbeta\n') == ['alpha', 'beta']
    assert parse_dokku_list('NAME  VERSION  STATUS\nalpha-db  postgres:16  running\n') == ['alpha-db']
    assert parse_dokku_list('=====> Postgres services\nalpha-db\n') == ['alpha-db']


def run_command(apps='', databases='', redis='', exclude=()):
    out = StringIO()
    with patch('applications.management.commands.dokku_orphans.DokkuAdapter') as adapter:
        adapter.return_value.get_apps.return_value = apps
        adapter.return_value.get_databases.return_value = databases
        adapter.return_value.list_redis.return_value = redis
        call_command('dokku_orphans', '--exclude', *exclude, stdout=out)
    return out.getvalue()


def test_lists_only_dokku_apps_without_active_record():
    user = UserFactory(email='quem-apagou@example.com')
    project = ProjectFactory()
    AppFactory(project=project, name_dokku='ativo')
    AppFactory(project=project, name_dokku='apagado', deleted_at=timezone.now(), deleted_by=user)
    ServiceFactory(project=project, container_name='ativo-db', service_type='postgres')

    output = run_command(
        apps='=====> My Apps\nativo\napagado\nsumido\nfabroku-api\n',
        databases='=====> Postgres services\nativo-db\nsolto-db\n',
        exclude=['fabroku-api'],
    )

    assert 'ativo ' not in output
    assert 'fabroku-api' not in output
    assert 'apagado' in output
    assert 'quem-apagou@example.com' in output
    assert 'sumido' in output
    assert 'sem registro no banco' in output
    assert 'solto-db' in output
    assert 'Total de orfaos: 3' in output
