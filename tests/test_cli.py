"""Smoke tests for the Typer command-line interface."""

from typer.testing import CliRunner

from qobuz_cli.cli.app import app

runner = CliRunner()


def test_help_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "download" in result.output


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0


def test_download_help_exits_zero():
    result = runner.invoke(app, ["download", "--help"])
    assert result.exit_code == 0
