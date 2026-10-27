"""Unit tests for the OAuth state helper shared by the CLI/web login views and the
shared GitHub callback. This is the primitive that closes the CLI login hijack:
the callback must never trust a client-supplied port/state at face value."""
import pytest

from infrastructure.adapters.utils.oauth_state import (
    consume_oauth_state,
    generate_oauth_state,
    validate_cli_port,
)


def test_consume_returns_the_data_generate_stored():
    state = generate_oauth_state(cli_port=54321)

    assert consume_oauth_state(state) == {'cli_port': 54321}


def test_consume_is_single_use():
    state = generate_oauth_state(cli_port=54321)
    consume_oauth_state(state)

    assert consume_oauth_state(state) is None


def test_consume_rejects_unknown_state():
    """A state an attacker makes up (never minted by generate_oauth_state) must
    never resolve to a port — this is what makes a forged `state` harmless."""
    assert consume_oauth_state('attacker-made-this-up') is None


def test_consume_rejects_empty_state():
    assert consume_oauth_state('') is None


@pytest.mark.parametrize('raw_port', ['1024', '65535', '9876'])
def test_validate_cli_port_accepts_in_range_values(raw_port):
    assert validate_cli_port(raw_port) == int(raw_port)


@pytest.mark.parametrize(
    'raw_port',
    [
        None,
        '',
        '0',
        '1023',
        '65536',
        '-1',
        '1@evil.com',
        '9876; rm -rf /',
        '9876\nHost: evil.com',
        '  9876',
        '9876 ',
        'abc',
    ],
)
def test_validate_cli_port_rejects_everything_else(raw_port):
    assert validate_cli_port(raw_port) is None
