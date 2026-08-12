"""Integration tests for DokkuAdapter against a real Dokku host over SSH.

Skipped unless DOKKU_SSH_KEY is configured (see config/settings.py) — CI and
default `pytest` runs never touch real infrastructure. Run explicitly with:

    pytest tests/integration/adapters/test_dokku_adapter.py -m integration
"""
import uuid

import pytest
from django.conf import settings

from infrastructure.adapters.dokku import DokkuAdapter

pytestmark = pytest.mark.integration

requires_real_dokku = pytest.mark.skipif(
    not settings.DOKKU_SSH_KEY, reason='DOKKU_SSH_KEY not configured — no real Dokku host to test against'
)


@pytest.fixture
def dokku() -> DokkuAdapter:
    return DokkuAdapter()


@requires_real_dokku
def test_create_and_delete_app_round_trip(dokku: DokkuAdapter):
    app_name = f'itest-{uuid.uuid4().hex[:8]}'
    try:
        dokku.create_app(app_name)
        assert dokku.exists_app(app_name) is True
    finally:
        dokku.delete_app(app_name)
        assert dokku.exists_app(app_name) is False


@requires_real_dokku
def test_exists_app_false_for_unknown_app(dokku: DokkuAdapter):
    assert dokku.exists_app(f'does-not-exist-{uuid.uuid4().hex[:8]}') is False
