"""Logger module for the Blackboard Sync CLI."""

import atexit
import hashlib
import json
import logging
import os
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING, Any

from rich.logging import RichHandler
from rich.panel import Panel

if TYPE_CHECKING:
    from rich.console import Console


class JSONFormatter(logging.Formatter):
    """Formatter that outputs logs as JSON strings (JSONL format)."""

    def format(self, record: logging.LogRecord) -> str:
        """Formats the log record into a structured JSON string.

        Args:
            record: The LogRecord instance to format.

        Returns:
            str: A JSON string representation of the log entry.
        """
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class Logger:
    """A unified logging wrapper utilizing Rich for console output and Queue for background JSON logging.

    Provides standard logging capabilities alongside formatted console banners,
    enforcing consistent styling across different log levels while writing
    structured JSON logs in a background thread.
    """

    def __init__(self, console: Console) -> None:
        """Initializes the Logger instance.

        Args:
            console: The rich Console instance for printing UI elements.
        """
        self.console = console
        self._logger = logging.getLogger("bb_sync")
        self._listener: QueueListener | None = None

    def setup_logger(self, log_level: int = logging.INFO) -> None:
        """Configures the underlying logging module with console and background JSON handlers.

        Initializes the RichHandler for the CLI UI and a QueueHandler connected
        to a background QueueListener for writing non-blocking structured JSON logs.

        Args:
            log_level: The logging level to enforce. Defaults to logging.INFO.
        """

        handlers: list[logging.Handler] = [
            RichHandler(
                console=self.console,
                rich_tracebacks=True,
                markup=True,
                show_path=False,
            )
        ]

        # Background JSON Structured Logger (Isolated per session)
        username = os.getenv("BLACKBOARD_USERNAME")
        if username:
            try:
                base_dir = Path(__file__).resolve().parent.parent.parent
                log_dir = base_dir / ".state" / "logs"
                log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

                safe_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()[:16]
                log_file = log_dir / f"session_{safe_hash}.jsonl"

                file_handler = logging.FileHandler(log_file, encoding="utf-8")
                file_handler.setFormatter(JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%SZ"))

                log_queue: Queue[logging.LogRecord] = Queue(-1)
                queue_handler = QueueHandler(log_queue)

                self._listener = QueueListener(log_queue, file_handler, respect_handler_level=True)
                self._listener.start()

                # Ensure the background thread drains the queue and closes the file safely on exit
                atexit.register(self._listener.stop)

                handlers.append(queue_handler)
            except OSError as e:
                self.console.print(
                    f"[yellow]Warning: Could not initialize background structured logging: {e}[/yellow]"
                )

        logging.basicConfig(
            level=log_level,
            format="%(message)s",
            datefmt="[%Y-%m-%d %H:%M:%S]",
            handlers=handlers,
        )

    def print_banner(self, course_code: str, target_term: str, install_dir: str | None = None) -> None:
        """Prints a formatted startup banner to the console.

        Args:
            course_code: The identifier for the course.
            target_term: The target academic term (e.g., '2024-2025').
            install_dir: The directory where the application is installed.
        """
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
        """Logs an informational message.

        Args:
            msg: The message to log.
            *args: Variable length argument list for the logger.
            **kwargs: Arbitrary keyword arguments for the logger.
        """
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Logs a warning message with yellow markup on console, pure text in JSON.

        Args:
            msg: The message to log.
            *args: Variable length argument list for the logger.
            **kwargs: Arbitrary keyword arguments for the logger.
        """
        # Rich markup only formats for console; JSON will capture raw string if used via normal logger.e.
        self._logger.warning(f"[yellow]{msg}[/yellow]", *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Logs an error message with red markup on console, pure text in JSON.

        Args:
            msg: The message to log.
            *args: Variable length argument list for the logger.
            **kwargs: Arbitrary keyword arguments for the logger.
        """
        self._logger.error(f"[red]{msg}[/red]", *args, **kwargs)

    def success(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Logs a success message with green markup on console, pure text in JSON.

        Args:
            msg: The message to log.
            *args: Variable length argument list for the logger.
            **kwargs: Arbitrary keyword arguments for the logger.
        """
        self._logger.info(f"[green]{msg}[/green]", *args, **kwargs)
