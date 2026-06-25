"""Logger module for the Blackboard Sync CLI."""

import logging
from typing import TYPE_CHECKING, Any

from rich.logging import RichHandler
from rich.panel import Panel

if TYPE_CHECKING:
    from rich.console import Console


class Logger:
    """A unified logging wrapper utilizing Rich for console output.

    Provides standard logging capabilities alongside formatted console banners,
    enforcing consistent styling across different log levels.
    """

    def __init__(self, console: Console) -> None:
        """Initializes the Logger instance.

        Args:
            console: The rich Console instance for printing UI elements.
        """
        self.console = console
        self._logger = logging.getLogger("bb_sync")

    def setup_logger(self, log_level: int = logging.INFO) -> None:
        """Configures the underlying logging module with a RichHandler.

        Args:
            log_level: The logging level to enforce. Defaults to logging.INFO.
        """
        logging.basicConfig(
            level=log_level,
            format="%(message)s",
            datefmt="[%Y-%m-%d %H:%M:%S]",
            handlers=[
                RichHandler(
                    console=self.console,
                    rich_tracebacks=True,
                    markup=True,
                    show_path=False,
                )
            ],
        )

    def print_banner(self, course_code: str, target_term: str) -> None:
        """Prints a formatted startup banner to the console.

        Args:
            course_code: The identifier for the course.
            target_term: The target academic term (e.g., '2024-2025').
        """
        banner_text = (
            f"[bold cyan]Course:[/bold cyan] {course_code}\n[bold cyan]Term:[/bold cyan] {target_term}\n"
        )
        panel = Panel(
            banner_text,
            title="[bold green]Blackboard-Sync started[/bold green]",
            expand=False,
            border_style="green",
        )
        self.console.print(panel)
        self.console.print()

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Logs an informational message.

        Args:
            msg: The message to log.
            *args: Variable length argument list for the logger.
            **kwargs: Arbitrary keyword arguments for the logger.
        """
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Logs a warning message with yellow markup.

        Args:
            msg: The message to log.
            *args: Variable length argument list for the logger.
            **kwargs: Arbitrary keyword arguments for the logger.
        """
        self._logger.warning(f"[yellow]{msg}[/yellow]", *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Logs an error message with red markup.

        Args:
            msg: The message to log.
            *args: Variable length argument list for the logger.
            **kwargs: Arbitrary keyword arguments for the logger.
        """
        self._logger.error(f"[red]{msg}[/red]", *args, **kwargs)

    def success(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Logs a success message with green markup.

        Args:
            msg: The message to log.
            *args: Variable length argument list for the logger.
            **kwargs: Arbitrary keyword arguments for the logger.
        """
        self._logger.info(f"[green]{msg}[/green]", *args, **kwargs)
