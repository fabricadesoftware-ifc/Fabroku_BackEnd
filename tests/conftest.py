"""Pytest configuration and fixtures."""
import os

import django

# Configure Django settings for tests
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import pytest
from django.test import Client
from rest_framework.test import APIClient


@pytest.fixture
def db_setup():
    """Ensure Django database is set up for tests."""
    pass


@pytest.fixture
def client():
    """Django test client."""
    return Client()


@pytest.fixture
def api_client():
    """DRF API test client."""
    return APIClient()


@pytest.fixture
def authenticated_api_client(api_client, user_factory):
    """DRF API client with authenticated user."""
    user = user_factory()
    api_client.force_authenticate(user=user)
    return api_client


# Import factories to make them available in tests
pytest_plugins = ['tests.factories']
