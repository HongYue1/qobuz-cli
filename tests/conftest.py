"""Shared pytest fixtures for the qobuz-cli test suite."""

import pytest


def make_config_kwargs(**overrides):
    """Return a minimal set of valid kwargs for ``DownloadConfig``."""
    kwargs = {
        "token": "a-valid-token",
        "app_id": "123456789",
        "secrets": ["deadbeef"],
        "output_template": "{albumartist}/{album}/{tracknumber} {tracktitle}",
        "config_path": "/tmp/qobuz-cli-test.ini",
    }
    kwargs.update(overrides)
    return kwargs


@pytest.fixture
def config_factory():
    """Expose ``make_config_kwargs`` as a fixture."""
    return make_config_kwargs
