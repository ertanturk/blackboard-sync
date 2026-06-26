"""Configuration management for Blackboard-Sync."""

import logging
import os
import re
import textwrap
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Base class for configuration errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


class Config:
    """Singleton configuration manager for Blackboard-Sync.

    Handles environment variable loading, validation, and directory setup.
    """

    _instance: Config | None = None
    _initialized: bool = False

    BASE_DIR = Path(__file__).resolve().parent.parent
    DEFAULT_ENV_PATH = BASE_DIR / ".env"
    DEFAULT_INSTALL_DIR = BASE_DIR / "downloads"
    TIMEOUT_SECONDS: int = 60
    RETRY_ATTEMPTS: int = 3

    # Playwright timeouts (milliseconds)
    NETWORK_WAIT_MS: int = 30000
    USER_WAIT_MS: int = 10000
    FAST_LOGIN_WAIT_MS: int = 10000
    MFA_USER_WAIT_MS: int = 100000
    SHORT_WAIT_MS: int = 4000
    UI_WAIT_TIMEOUT: int = 6000
    CLICK_WAIT_TIMEOUT: int = 2000

    # Valid file extensions to download
    VALID_EXTENSIONS: set[str] = {
        ".pdf",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".txt",
        ".rtf",
        ".csv",
        ".zip",
        ".png",
        ".jpg",
        ".jpeg",
    }

    # Folders to completely ignore during the recursive crawl
    EXCLUDE_FOLDERS: set[str] = {
        "zoom",
        "assignment",
        "homework",
        "quiz",
        "exam",
        "syllabus",
        "discussion",
        "grade",
        "turnitin",
        "sınav",
        "ödev",
        "proje",
    }

    # Keywords to match in item titles for download filtering
    KEYWORDS = [
        "Course Content",
        "Ders İçeriği",
        "Proje",
        "Project",
        "Lecture",
        "Ders",
        "Lectures",
        "Lecture Notes",
        "Documents",
        "Belgeler",
        "Materials",
        "Materyaller",
        "Resources",
    ]

    def __new__(cls, *args, **kwargs) -> Config:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, install_dir: Path | None = None) -> None:
        if self._initialized:
            return

        self.INSTALL_DIR: Path = install_dir if install_dir is not None else self.DEFAULT_INSTALL_DIR
        self.load_config()
        self.__class__._initialized = True

    def _check_env(self) -> bool:
        """Checks if the environment configuration file exists.

        Returns:
            bool: True if the file exists, False otherwise.
        """
        return self.DEFAULT_ENV_PATH.exists()

    def _create_env(self) -> None:
        """Creates a default .env file with safe permissions.

        Raises:
            ConfigError: If the directory or file cannot be created.
        """
        env_content: str = textwrap.dedent("""\
            BLACKBOARD_USERNAME=
            BLACKBOARD_PASSWORD=
            BLACKBOARD_BASE_URL=https://mef.blackboard.com/
            TARGET_TERM=
        """)
        try:
            self.DEFAULT_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.DEFAULT_ENV_PATH, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(env_content)

            logger.info("Created default .env file at %s", self.DEFAULT_ENV_PATH)
        except FileExistsError:
            logger.debug(".env file already exists, skipping creation.")
        except OSError as e:
            raise ConfigError(f"Failed to create .env file: {e}") from e

    def _validate_env(self) -> None:
        """Validates the presence and format of required environment variables.

        Raises:
            ConfigError: If required variables are missing or malformed, or
                         if the file cannot be read.
        """
        try:
            load_dotenv(self.DEFAULT_ENV_PATH)

            if not os.getenv("BLACKBOARD_USERNAME") or not os.getenv("BLACKBOARD_PASSWORD"):
                raise ConfigError("BLACKBOARD_USERNAME and BLACKBOARD_PASSWORD must be set in .env file")

            base_url = os.getenv("BLACKBOARD_BASE_URL")
            target_term = os.getenv("TARGET_TERM")

            if not base_url or not target_term:
                raise ConfigError("BLACKBOARD_BASE_URL and TARGET_TERM must be set in .env file")

            self._validate_values(base_url, target_term)
        except ConfigError:
            raise
        except OSError as e:
            raise ConfigError(f"Failed to validate .env file: {e}") from e

    def _validate_values(self, base_url: str, target_term: str) -> None:
        """Validates the specific formats of the base URL and target term.

        Args:
            base_url: The Blackboard base URL.
            target_term: The academic term in YYYY-YYYY format.

        Raises:
            ConfigError: If the URL or term format is invalid.
        """
        if base_url != "https://mef.blackboard.com/":
            raise ConfigError("BLACKBOARD_BASE_URL must be set to 'https://mef.blackboard.com/' in .env file")

        if not re.fullmatch(r"\d{4}-\d{4}", target_term):
            raise ConfigError("TARGET_TERM must be in YYYY-YYYY format in .env file")

        start_year_str, end_year_str = target_term.split("-")
        start_year = int(start_year_str)
        end_year = int(end_year_str)

        if start_year < 2024:
            raise ConfigError("TARGET_TERM must start from 2024 in .env file")

        if start_year - end_year != -1:
            raise ConfigError("TARGET_TERM year range must be one year apart in .env file")

    def _validate_install_dir(self) -> None:
        """Ensures the installation directory exists."""
        if not self.INSTALL_DIR.exists():
            self._create_install_dir()

    def _create_install_dir(self) -> None:
        """Creates the installation directory.

        Raises:
            ConfigError: If the directory cannot be created.
        """
        try:
            self.INSTALL_DIR.mkdir(parents=True, exist_ok=True)
            logger.info("Created installation directory at %s", self.INSTALL_DIR)
        except OSError as e:
            raise ConfigError(f"Failed to create installation directory: {e}") from e

    def load_config(self) -> None:
        """Loads and validates all configuration parameters."""
        if not self._check_env():
            self._create_env()
        self._validate_env()
        self._validate_install_dir()
