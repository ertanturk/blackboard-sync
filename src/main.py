"""Main entry point and CLI orchestrator for Blackboard-Sync."""

import os
import sys
import time
from enum import IntEnum
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from src.auth.authenticator import login_or_load_state
from src.config import Config, ConfigError
from src.logger.logger import Logger


class ExitCode(IntEnum):
    """Standard POSIX exit codes for Blackboard-Sync."""

    SUCCESS = 0
    CONFIG_ERROR = 1
    AUTH_FAILURE = 2
    COURSE_NOT_FOUND = 3
    NETWORK_ERROR = 4


app = typer.Typer(
    help="Idempotent Blackboard Ultra Course Downloader",
    add_completion=False,
    rich_markup_mode="rich",
)


@app.command()
def sync(
    course: Annotated[
        str,
        typer.Option(
            "--course",
            "-c",
            help="[bold cyan]Target course code[/bold cyan] (e.g., CS301, BIL301)",
            show_default=False,
        ),
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Ignore local files and [red]force redownload[/red] everything.",
        ),
    ] = False,
    headful: Annotated[
        bool,
        typer.Option(
            "--headful",
            "-h",
            help="Run browser in [yellow]visible mode[/yellow] (useful for debugging or first-time MFA).",
        ),
    ] = False,
) -> None:
    """Synchronizes course materials from Blackboard Ultra to your local machine.

    Args:
        course: The target course code to search for and download.
        force: If True, bypasses local idempotency checks and overwrites existing files.
        headful: If True, launches the Playwright browser with a visible GUI.
    """
    start_time = time.time()

    console = Console()
    cli_logger = Logger(console)
    cli_logger.setup_logger()

    try:
        # Load and validate Configuration
        Config()

        target_term = os.getenv("TARGET_TERM")
        if not target_term:
            cli_logger.error("TARGET_TERM is missing from the environment.")
            sys.exit(ExitCode.CONFIG_ERROR)

        # Print Corporate Banner
        cli_logger.print_banner(course_code=course, target_term=target_term)

        if force:
            cli_logger.warning("Force mode activated. Idempotency checks will be bypassed.")
        if headful:
            cli_logger.warning("Headful mode activated. Browser GUI will be visible.")

        # --- ARCHITECTURE PHASES (Placeholders) ---

        cli_logger.info("\n[bold]Phase 1: Authentication[/bold]")
        state_path = login_or_load_state(headful=headful)

        if not state_path:
            cli_logger.error("Authentication failed. Check your .env credentials or MFA status.")
            sys.exit(ExitCode.AUTH_FAILURE)

        cli_logger.success(f"Authentication phase complete. Session active via: {state_path.name}")

        cli_logger.info("\n[bold]Phase 2: Navigation & Discovery[/bold]")
        # download_queue = crawler.get_download_queue(course_code=course)
        # if not download_queue:
        #     cli_logger.error(f"Could not find course '{course}' or it contains no downloadable files.")
        #     sys.exit(ExitCode.COURSE_NOT_FOUND)
        cli_logger.success("Discovery phase complete. Found X files.")

        cli_logger.info("\n[bold]Phase 3: Synchronization[/bold]")
        # stats = downloader.process_queue(queue=download_queue, force_override=force)

        # Mocking stats for the draft
        stats = {"total": 10, "downloaded": 2, "skipped": 8, "errors": 0}
        cli_logger.success("Synchronization phase complete.")

        # Print Final Summary using Rich Panel
        duration = time.time() - start_time
        summary_text = (
            f"[bold]Total Found:[/bold] {stats['total']}\n"
            f"[bold green]Downloaded:[/bold green] {stats['downloaded']}\n"
            f"[bold yellow]Skipped:[/bold yellow] {stats['skipped']}\n"
            f"[bold red]Errors:[/bold red] {stats['errors']}\n\n"
            f"[dim]Duration: {duration:.2f}s[/dim]"
        )
        console.print()
        console.print(Panel(summary_text, title="[bold blue]Sync Summary[/bold blue]", expand=False))

        sys.exit(ExitCode.SUCCESS)

    except ConfigError as ce:
        cli_logger.error(f"Configuration Error: {ce.message}")
        sys.exit(ExitCode.CONFIG_ERROR)
    except Exception as e:
        # Catch-all for unexpected Playwright or Network crashes
        cli_logger.error(f"An unexpected system error occurred: {e}")
        sys.exit(ExitCode.NETWORK_ERROR)


if __name__ == "__main__":
    app()
