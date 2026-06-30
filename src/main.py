"""Main entry point and CLI orchestrator for Blackboard-Sync."""

import os
import signal
import sys
import time
from enum import IntEnum
from pathlib import Path
from typing import Annotated

import keyring
import typer
from keyring.errors import PasswordDeleteError
from playwright.sync_api import sync_playwright
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.auth.authenticator import get_browser_state_path, get_state_file_path, login
from src.config import Config, ConfigError
from src.crawler.navigator import navigate_to_course
from src.crawler.parser import parse_course_content
from src.downloader.sync_manager import _shutdown_event, process_queue
from src.logger.logger import Logger


class ExitCode(IntEnum):
    """Standard POSIX exit codes for Blackboard-Sync."""

    SUCCESS = 0
    CONFIG_ERROR = 1
    AUTH_FAILURE = 2
    COURSE_NOT_FOUND = 3
    NETWORK_ERROR = 4
    KEYBOARD_INTERRUPT = 5
    ALREADY_RUNNING = 6


_lock_fd = None


def acquire_instance_lock() -> bool:
    """Acquires a cross-platform OS-level file lock to prevent concurrent executions.

    Using kernel-level locks ensures that if the process crashes or is killed,
    the OS automatically releases the lock. No stale locks are left behind.
    """
    global _lock_fd

    base_dir = Path(__file__).resolve().parent.parent
    state_dir = base_dir / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_file = state_dir / "bb_sync.lock"

    try:
        _lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)

        if os.name == "nt":
            # Local import prevents ModuleNotFoundError on Linux/macOS
            import msvcrt

            msvcrt.locking(_lock_fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        os.write(_lock_fd, f"{os.getpid():<10}".encode("utf-8"))  # noqa: UP012
        return True
    except OSError:
        if _lock_fd is not None:
            try:
                os.close(_lock_fd)
            except Exception:
                pass
        return False


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
    reset_auth: Annotated[
        bool,
        typer.Option(
            "--reset-auth",
            "-ra",
            help="Reset saved credentials and session state to force a fresh login.",
            rich_help_panel="Behavior Options",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Run in dry mode, no files will be downloaded.",
            rich_help_panel="Behavior Options",
        ),
    ] = False,
    skip_confirmation: Annotated[
        bool,
        typer.Option(
            "--skip-confirmation",
            "-s",
            help="Skip confirmation prompts before downloading files.",
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
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            "-q",
            help="Suppress all banners, tables, and prompts (Ideal for CI/CD or cron jobs).",
            rich_help_panel="Logging Options",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable debug-level logging.",
            rich_help_panel="Logging Options",
        ),
    ] = False,
) -> None:
    """Synchronizes course materials from Blackboard to your local machine."""

    if quiet and verbose:
        console.print("[bold red]Error:[/bold red] Cannot use --quiet and --verbose together.")
        sys.exit(ExitCode.CONFIG_ERROR)

    if not acquire_instance_lock():
        console.print("\n[bold red][!] Another instance of Blackboard-Sync is already running.[/bold red]")
        console.print(
            "[yellow]Please wait for the current synchronization to finish before starting a new one.[/yellow]\n"
        )
        sys.exit(ExitCode.ALREADY_RUNNING)

    def handle_shutdown_signal(signum, frame):
        _shutdown_event.set()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    if hasattr(signal, "SIGTSTP"):
        signal.signal(signal.SIGTSTP, handle_shutdown_signal)

    start_time = time.time()
    cli_logger = Logger(console)

    # Empty line for clean terminal startup
    console.print()

    try:
        if download_path is not None:
            path = Path(download_path)
            config = Config(install_dir=path)
        else:
            config = Config()
        config.load_config()

        cli_logger.setup_logger()

        # Display the custom startup banner defined in logger.py
        if not quiet:
            cli_logger.print_banner(
                course_code=course,
                target_term=os.getenv("TARGET_TERM", "Unknown Term"),
                install_dir=str(download_path) if download_path is not None else str(config.INSTALL_DIR),
            )

        username = os.getenv("BLACKBOARD_USERNAME")
        if not username:
            cli_logger.error("BLACKBOARD_USERNAME must be set in your .env file.")
            sys.exit(ExitCode.AUTH_FAILURE)

        if reset_auth:
            try:
                keyring.delete_password("blackboard-sync", username)
                cli_logger.info("[dim]Old password removed from system keyring.[/dim]")
            except PasswordDeleteError:
                pass

            state_file = get_state_file_path(username)
            if state_file and state_file.exists():
                state_file.unlink()
                cli_logger.info("[dim]Old browser state file removed.[/dim]")

            cli_logger.info("[bold green]Authentication state reset successfully![/bold green]")

        state_path = get_browser_state_path(username)
        if not state_path:
            password = None
            try:
                password = keyring.get_password("blackboard-sync", username)
            except Exception as e:
                if not quiet:
                    cli_logger.warning(
                        f"System keyring is unavailable ({type(e).__name__}). "
                        "This usually happens on headless Linux servers without 'dbus' or 'secret-service'. "
                        "Falling back to manual prompt."
                    )

            if not password:
                if quiet:
                    cli_logger.error("Password required but running in --quiet mode. Aborting.")
                    sys.exit(ExitCode.AUTH_FAILURE)

                cli_logger.error("No secure password found for username `%s` in keyring.", username)
                password = typer.prompt("Enter Blackboard Password", hide_input=True)

                if not password:
                    cli_logger.error("Password cannot be empty. Aborting.")
                    sys.exit(ExitCode.AUTH_FAILURE)

                keyring.set_password("blackboard-sync", username, password)
                cli_logger.info("[bold green]Password saved securely to system keyring![/bold green]")

            with console.status(
                "[bold green]Phase 1: Authenticating with Blackboard...[/bold green]", spinner="dots"
            ):
                state_path = login(headful=headful)
        else:
            cli_logger.info("[bold green]SUCCESS:[/bold green] Valid session found. Skipping login.")

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

        if download_queue and not quiet:
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

        pending_files = [f for f in download_queue if force or not f.exists_locally()]

        total_bytes = sum(getattr(f, "SIZE_BYTES", 0) for f in pending_files)
        size_str = "Unknown"
        if total_bytes > 0:
            if total_bytes >= 1024**3:
                size_str = f"{total_bytes / (1024**3):.2f} GB"
            else:
                size_str = f"{total_bytes / (1024**2):.2f} MB"

        auto_skip_prompt = skip_confirmation or quiet
        confirm = True

        if not auto_skip_prompt and pending_files:
            confirm = typer.confirm(
                f"Download {len(pending_files)} new/updated files? (Estimated Size: {size_str})", default=True
            )

        if not confirm:
            stats = {
                "total": len(download_queue),
                "downloaded": 0,
                "skipped": 0,
                "errors": 0,
                "install_dir": config.INSTALL_DIR,
            }
            if not quiet:
                cli_logger.warning("[bold yellow]Download cancelled by user.[/bold yellow]")
        else:
            if dry_run:
                if not quiet:
                    console.print("[bold yellow]Dry run: no files will be downloaded.[/bold yellow]")
                stats = {
                    "total": len(download_queue),
                    "downloaded": 0,
                    "skipped": 0,
                    "errors": 0,
                    "install_dir": config.INSTALL_DIR,
                    "quiet": quiet,
                }
            else:
                stats = process_queue(
                    queue=download_queue,
                    state_path=state_path,
                    force_override=force,
                    max_threads=8,
                    install_dir=config.INSTALL_DIR,
                )

            if _shutdown_event.is_set():
                raise KeyboardInterrupt()

        if not quiet:
            cli_logger.info("[bold blue]SUCCESS:[/bold blue] Synchronization phase complete.")
            duration = time.time() - start_time

            failed_text = ""
            if stats.get("failed_files"):
                failed_text = "\n[bold red]Failed Files:[/bold red]\n"
                for failed_file in stats["failed_files"]:  # type: ignore
                    failed_text += f"  - [red]✖[/red] {failed_file}\n"

            summary_text = (
                f"[bold]Total Found:[/bold] {stats['total']}\n"
                f"[bold green]Downloaded:[/bold green] {stats['downloaded']}\n"
                f"[bold yellow]Skipped:[/bold yellow] {stats['skipped']}\n"
                f"[bold red]Errors:[/bold red] {stats['errors']}\n"
                f"{failed_text}\n"
                f"[bold purple]Output Dir:[/bold purple] {stats['install_dir']}\n"
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
        else:
            console.print("[bold green]Installation complete. Thanks for using Blackboard Sync![/bold green]")
        sys.exit(ExitCode.SUCCESS)

    except KeyboardInterrupt:
        console.print("\n[bold red][!] All operations cancelled gracefully.[/bold red]")
        try:
            sys.stdout.flush()
            sys.stderr.flush()
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stderr.fileno())
        except Exception:
            pass
        os._exit(ExitCode.KEYBOARD_INTERRUPT)
    except ConfigError as ce:
        console.print(f"[bold red]Configuration Error:[/bold red] {ce.message}")
        sys.exit(ExitCode.CONFIG_ERROR)
    except Exception as e:
        if _shutdown_event.is_set() or "Target closed" in str(e) or "Browser closed" in str(e):
            console.print("\n[bold red][!] All operations cancelled gracefully.[/bold red]")
            try:
                sys.stdout.flush()
                sys.stderr.flush()
                devnull = os.open(os.devnull, os.O_WRONLY)
                os.dup2(devnull, sys.stderr.fileno())
            except Exception:
                pass
            os._exit(ExitCode.KEYBOARD_INTERRUPT)

        console.print(f"[bold red]An unexpected system error occurred:[/bold red] {e}")
        sys.exit(ExitCode.NETWORK_ERROR)


if __name__ == "__main__":
    app()
