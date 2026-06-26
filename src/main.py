"""Main entry point and CLI orchestrator for Blackboard-Sync."""

import os
import sys
import time
from enum import IntEnum
from pathlib import Path
from typing import Annotated

import typer
from playwright.sync_api import sync_playwright
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.auth.authenticator import login_or_load_state
from src.config import Config, ConfigError
from src.crawler.navigator import navigate_to_course
from src.crawler.parser import parse_course_content
from src.downloader.sync_manager import process_queue
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

console = Console()


@app.command()
def sync(
    course: Annotated[
        str,
        typer.Option(
            "--course",
            "-c",
            help="[bold cyan]Target course code[/bold cyan] (e.g., CS301, BIL301)",
            show_default=False,
            rich_help_panel="Targeting Options",
        ),
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Ignore local files and [red]force redownload[/red] everything.",
            rich_help_panel="Behavior Options",
        ),
    ] = False,
    headful: Annotated[
        bool,
        typer.Option(
            "--headful",
            "-h",
            help="Run browser in visible mode (useful for debugging).",
            rich_help_panel="Behavior Options",
        ),
    ] = False,
    download_path: Annotated[
        Path | None,
        typer.Option(
            "--download-path",
            "-d",
            help="Path to save downloaded files.",
            rich_help_panel="Targeting Options",
        ),
    ] = None,
) -> None:
    """Synchronizes course materials from Blackboard to your local machine."""
    start_time = time.time()

    cli_logger = Logger(console)
    cli_logger.setup_logger()

    # Empty line for clean terminal startup
    console.print()

    try:
        if download_path is not None:
            path = Path(download_path)
            config = Config(install_dir=path)
        else:
            config = Config()
        config.load_config()

        # Display the custom startup banner defined in logger.py
        cli_logger.print_banner(course_code=course, target_term=os.getenv("TARGET_TERM", "Unknown Term"))

        with console.status(
            "[bold green]Phase 1: Authenticating with Blackboard...[/bold green]", spinner="dots"
        ):
            state_path = login_or_load_state(headful=headful)

        if not state_path:
            cli_logger.error("Authentication failed. Aborting synchronization.")
            sys.exit(ExitCode.AUTH_FAILURE)

        cli_logger.info("[bold green]SUCCESS:[/bold green] Authentication verified.")

        with console.status(
            f"[bold cyan]Phase 2: Discovering materials for {course}...[/bold cyan]", spinner="dots"
        ):
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=not headful)
                context = browser.new_context(storage_state=state_path)
                page = context.new_page()

                # Navigate to the target course
                course_found = navigate_to_course(page, course)
                if not course_found:
                    cli_logger.error(f"Could not find or enter accessible course '{course}'.")
                    sys.exit(ExitCode.COURSE_NOT_FOUND)

                # Parse and build the download queue
                download_queue = parse_course_content(page, course, config.INSTALL_DIR)
                browser.close()

        cli_logger.info(
            f"[bold cyan]SUCCESS:[/bold cyan] Discovery phase complete. Found {len(download_queue)} files."
        )

        if download_queue:
            table = Table(title="Discovered Materials", border_style="cyan", box=box.SIMPLE)
            table.add_column("File Name", style="white", no_wrap=False)
            table.add_column("Type", style="magenta", justify="center")
            table.add_column("Target Folder", style="dim")

            for file_node in download_queue:
                table.add_row(
                    file_node.TITLE, file_node.FILE_TYPE.upper(), file_node.LOCAL_TARGET_PATH.parent.name
                )

            console.print()
            console.print(table)
            console.print()

        with console.status("[bold blue]Phase 3: Synchronization in progress...[/bold blue]", spinner="dots"):
            stats = process_queue(
                queue=download_queue,
                state_path=state_path,
                force_override=force,
                max_threads=8,
                install_dir=config.INSTALL_DIR,
            )

        cli_logger.info("[bold blue]SUCCESS:[/bold blue] Synchronization phase complete.")

        duration = time.time() - start_time
        summary_text = (
            f"[bold]Total Found:[/bold] {stats['total']}\n"
            f"[bold green]Downloaded:[/bold green] {stats['downloaded']}\n"
            f"[bold yellow]Skipped:[/bold yellow] {stats['skipped']}\n"
            f"[bold red]Errors:[/bold red] {stats['errors']}\n\n"
            f"[bold purple]Download files to:[/bold purple] {stats['install_dir']}\n"
            f"[dim]Duration: {duration:.2f}s[/dim]\n\n"
            "[italic]Thanks for using Blackboard Sync.[/italic]"
        )

        console.print()
        console.print(
            Panel(
                summary_text,
                title="[bold blue]Sync Summary[/bold blue]",
                border_style="blue",
                box=box.ROUNDED,
                expand=False,
                padding=(1, 2),
            )
        )

        sys.exit(ExitCode.SUCCESS)

    except ConfigError as ce:
        console.print(f"[bold red]Configuration Error:[/bold red] {ce.message}")
        sys.exit(ExitCode.CONFIG_ERROR)
    except Exception as e:
        console.print(f"[bold red]An unexpected system error occurred:[/bold red] {e}")
        sys.exit(ExitCode.NETWORK_ERROR)


if __name__ == "__main__":
    app()
