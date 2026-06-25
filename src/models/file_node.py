"""Data structure for Blackboard-Sync."""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class FileNode:
    """Represents a downloadable item or directory discovered on Blackboard Ultra.

    Attributes:
        TITLE: The sanitized name of the file or folder.
        FILE_TYPE: The string representation of the item's type (e.g., 'pdf', 'folder').
        LOCAL_TARGET_PATH: The absolute or relative local filesystem path for this node.
        BLACKBOARD_ID: The unique identifier assigned by Blackboard, if any.
        IS_FOLDER: Boolean indicating if this node represents a directory instead of a file.
        BLACKBOARD_URL: The direct URL to the item on Blackboard Ultra, if available.
    """

    TITLE: str
    FILE_TYPE: str
    LOCAL_TARGET_PATH: Path
    BLACKBOARD_ID: str | None = None
    IS_FOLDER: bool = False
    BLACKBOARD_URL: str | None = None

    def __post_init__(self) -> None:
        """Sanitizes the title to ensure it's a valid filename on all operating systems.

        Removes illegal characters (e.g., < > : " / \\ | ? *) and strips trailing
        whitespace and periods (which are invalid on Windows).
        """
        illegal_chars = r'[<>:"/\\|?*]'
        sanitized = re.sub(illegal_chars, "_", self.TITLE)

        self.TITLE = sanitized.strip().rstrip(".")

    def exists_locally(self) -> bool:
        """Idempotency check: Does this node already exist on the local filesystem?

        Returns:
            bool: True if the file or folder exists locally, False otherwise.
        """
        if not self.LOCAL_TARGET_PATH.exists():
            return False

        if self.IS_FOLDER:
            return self.LOCAL_TARGET_PATH.is_dir()

        return self.LOCAL_TARGET_PATH.is_file()

    def __str__(self) -> str:
        """Returns a string representation of the FileNode.

        Returns:
            str: Formatted string (e.g., '[PDF] Lecture_1').
        """
        return f"[{self.FILE_TYPE.upper()}] {self.TITLE}"
