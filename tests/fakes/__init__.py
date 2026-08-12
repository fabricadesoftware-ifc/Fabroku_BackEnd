"""Fake implementations of ports for testing."""
from tests.fakes.fake_dokku_port import FakeDokkuPort, FakeInteractiveChannel
from tests.fakes.fake_github_port import FakeGitHubPort

__all__ = ['FakeDokkuPort', 'FakeGitHubPort', 'FakeInteractiveChannel']

