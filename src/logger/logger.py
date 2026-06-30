"""Logger module for the Blackboard Sync CLI."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.logging import RichHandler
from rich.panel import Panel

if TYPE_CHECKING:
    from rich.console import Console


class Logger:
    """A unified logging wrapper utilizing Rich for console output.

    Provides standard logging capabilities alongside formatted console banners,
    enforcing consistent styling across different log levels. Utilizes Log Rotation
    to prevent disk space exhaustion.
    """

    def __init__(self, console: Console) -> None:
        """Initializes the Logger instance.

        Args:
            console: The rich Console instance for printing UI elements.
        """
        self.console = console
        self._logger = logging.getLogger("bb_sync")

        base_dir = Path(__file__).resolve().parent.parent.parent
        self.log_dir = base_dir / "logs"
        self.log_file = self.log_dir / "sync.log"

    def setup_logger(self, log_level: int = logging.INFO, quiet: bool = False, verbose: bool = False) -> None:
        """Configures the underlying logging module with Console and Rotating File handlers.

        Args:
            log_level: Default logging level.
            quiet: If True, suppresses console output completely.
            verbose: If True, upgrades logging level to DEBUG.
        """

        effective_level = logging.DEBUG if verbose else log_level

        self.log_dir.mkdir(parents=True, exist_ok=True)

        handlers = []

        if not quiet:
            handlers.append(
                RichHandler(
                    console=self.console,
                    rich_tracebacks=True,
                    markup=True,
                    show_path=False,
                )
            )

        file_handler = RotatingFileHandler(
            self.log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )

        file_formatter = logging.Formatter(
            fmt="[{asctime}] [{levelname:<8}] [{threadName}] [{module}:{lineno}] {message}",
            datefmt="%Y-%m-%d %H:%M:%S",
            style="{",
        )
        file_handler.setFormatter(file_formatter)
        handlers.append(file_handler)

        logging.basicConfig(
            level=effective_level,
            format="%(message)s",
            datefmt="[%Y-%m-%d %H:%M:%S]",
            handlers=handlers,
            force=True,
        )

    def print_banner(self, course_code: str, target_term: str, install_dir: str | None = None) -> None:
        """Prints a formatted startup banner to the console."""
        banner_text = f"[bold cyan]Target Course:[/bold cyan] {course_code}\n[bold cyan]Term:[/bold cyan] {target_term}\n"
        if install_dir is not None:
            banner_text += f"[bold cyan]Install Dir:[/bold cyan] {install_dir}\n"
        panel = Panel(
            banner_text,
            title="[bold green]Blackboard-Sync[/bold green]",
            expand=False,
            border_style="green",
        )
        self.console.print(panel)
        self.console.print()

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.warning(f"[yellow]{msg}[/yellow]", *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.error(f"[red]{msg}[/red]", *args, **kwargs)

    def success(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.info(f"[green]{msg}[/green]", *args, **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Logs a debug message (visible only when --verbose is used)."""
        self._logger.debug(f"[dim]{msg}[/dim]", *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Logs an error WITH the full stack trace (Traceback) attached."""
        self._logger.error(f"[bold red]{msg}[/bold red]", *args, exc_info=True, **kwargs)
