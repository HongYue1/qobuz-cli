"""
Main entry point for the qobuz-cli application.
This module handles top-level setup, exception handling, and CLI invocation.
"""

import asyncio
import logging
import os
import sys
import time

import typer
from rich.console import Console

from qobuz_cli.cli.app import app
from qobuz_cli.cli.formatters import format_error_with_suggestions
from qobuz_cli.exceptions import QobuzCliError


def main() -> None:
    """Main entry point function."""
    if os.name == "nt":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except (TypeError, AttributeError):
            pass

    log = logging.getLogger("qobuz_cli")
    console = Console()

    try:
        app()
    except (typer.Exit, typer.Abort):
        pass
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print("\n[yellow]⚠️  Operation cancelled by user.[/yellow]")
        sys.exit(0)
    except QobuzCliError as e:
        console.print(f"\n{format_error_with_suggestions(e)}")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n{format_error_with_suggestions(e, {'type': 'Unexpected'})}")
        log.debug("Full traceback:", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
