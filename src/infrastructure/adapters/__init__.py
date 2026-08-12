"""Adapter implementations for external systems (Dokku, GitHub, SSH, etc)."""
from .dokku import DokkuAdapter as DokkuAdapter
from .github import GitHubAdapter as GitHubAdapter
from .ssh import SSHAdapter as SSHAdapter
