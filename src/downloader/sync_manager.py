"""
Sync Manager for Blackboard-Sync.

Handles highly concurrent, multithreaded file downloads bypassing the UI entirely.
Utilizes Session Handoff (Playwright Cookies -> Python Requests) for maximum speed.
"""

import json
import logging
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from tqdm import tqdm

from src.models.file_node import FileNode

logger = logging.getLogger(__name__)

# Thread-local storage to prevent requests.Session race conditions
_thread_local = threading.local()

# Global locks to prevent race conditions on identical file paths
_download_locks: dict[Path, threading.Lock] = {}
_download_locks_guard = threading.Lock()


def _is_transient_error(exception: Exception) -> bool:
    """Determines if the exception is a transient error that should be retried."""
    if isinstance(exception, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exception, requests.HTTPError) and exception.response is not None:
        status_code = exception.response.status_code
        # 429 Too Many Requests or 5xx Internal Server Errors
        return status_code == 429 or 500 <= status_code < 600
    return False


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=10, exp_base=2),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _make_authenticated_request(session: requests.Session, url: str) -> requests.Response:
    """Authenticated request with retry logic using tenacity."""
    try:
        response = session.get(url, stream=True, timeout=(5, 30))
        response.raise_for_status()
        return response
    except Exception as exc:
        if not _is_transient_error(exc):
            raise exc

        logger.warning(f"Transient error occurred: {exc}. Retrying...")
        raise exc


def _get_download_lock(path: Path) -> threading.Lock:
    """Retrieves or creates a thread-safe lock for a specific file path."""
    with _download_locks_guard:
        return _download_locks.setdefault(path.resolve(), threading.Lock())


def _get_authenticated_session(state_path: Path) -> requests.Session | None:
    """Creates and caches a thread-local authenticated requests.Session.

    Reads Playwright's storage_state.json, validates it, and injects cookies.
    Monitors file modification time to prevent stale sessions.
    """
    try:
        state_mtime = state_path.stat().st_mtime
    except FileNotFoundError:
        return None

    if (
        not hasattr(_thread_local, "session")
        or not hasattr(_thread_local, "state_mtime")
        or _thread_local.state_mtime != state_mtime
    ):
        if hasattr(_thread_local, "session"):
            _thread_local.session.close()

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
        )

        try:
            with Path(state_path).open("r", encoding="utf-8") as f:
                state = json.load(f)

            required = {"name", "value", "domain", "path"}

            for cookie in state.get("cookies", []):
                if not required.issubset(cookie):
                    logger.warning("Skipping malformed cookie: %s", cookie)
                    continue

                session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie["domain"],
                    path=cookie["path"],
                )

            _thread_local.session = session
            _thread_local.state_mtime = state_mtime
            logger.debug("Successfully injected Playwright cookies into thread-local Requests session.")

        except OSError as e:
            logger.error("Failed to read state file for cookies: %s", e)
            return None
        except json.JSONDecodeError as e:
            logger.error("State file contains invalid JSON: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected error loading cookies: %s", e)
            return None
        finally:
            session.close()

    return _thread_local.session


def _download_worker(node: FileNode, state_path: Path, force_override: bool) -> str:
    """Worker function to download a single file with idempotency and retry guards."""

    # Global Pre-Check (Fast fail before lock)
    if not force_override and node.exists_locally():
        return "SKIPPED"

    session = _get_authenticated_session(state_path)
    if not session:
        return "ERROR"

    current_url = node.BLACKBOARD_DOWNLOAD_URL
    if not current_url:
        logger.warning("Missing download URL for node: %s", node.TITLE)
        return "ERROR"

    lock = _get_download_lock(node.LOCAL_TARGET_PATH)

    with lock:
        # Strict In-Lock Check (Prevents TOCTOU race conditions across identical nodes)
        if not force_override and node.exists_locally():
            return "SKIPPED"

        MAX_ATTACHMENT_LOOKUPS = 3

        for _ in range(MAX_ATTACHMENT_LOOKUPS):
            try:
                response = _make_authenticated_request(session, current_url)
                content_type = response.headers.get("Content-Type", "")

                # Blackboard sometimes returns a JSON pointer to the actual file attachment
                if "application/json" in content_type:
                    data = response.json()
                    results = data.get("results", [])

                    if not results:
                        logger.warning("Empty JSON results array for node: %s", node.TITLE)
                        return "ERROR"

                    attachment_id = results[0].get("id")
                    if not attachment_id:
                        logger.warning("Missing 'id' in JSON results for node: %s", node.TITLE)
                        return "ERROR"

                    match = re.search(r"/courses/(_\d+_\d+)", current_url)
                    if not match:
                        logger.warning("Failed to extract course ID from URL: %s", current_url)
                        return "ERROR"

                    course_id = match.group(1)
                    base_url = os.getenv("BLACKBOARD_BASE_URL", "https://mef.blackboard.com").rstrip("/")

                    # Loop safely without modifying the shared FileNode object
                    resolved_url = f"{base_url}/learn/api/v1/courses/{course_id}/contents/{attachment_id}/attachments/{attachment_id}/download"
                    current_url = resolved_url
                    continue

                # Direct File Stream
                target_path = node.LOCAL_TARGET_PATH
                target_path.parent.mkdir(parents=True, exist_ok=True)

                # Worker-unique temp file to prevent partial write collisions
                temp_path = target_path.with_name(f"{target_path.name}.{uuid.uuid4().hex}.part")

                success = False
                try:
                    expected_len = response.headers.get("Content-Length")
                    written = 0

                    with Path(temp_path).open("wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                written += len(chunk)

                    # Validate Content-Length to guard against truncated network drops
                    if expected_len is not None:
                        if written != int(expected_len):
                            logger.error(
                                "Truncated download for %s. Expected %s bytes, got %s.",
                                node.TITLE,
                                expected_len,
                                written,
                            )
                            return "ERROR"

                    temp_path.replace(target_path)
                    success = True
                    return "DOWNLOADED"

                finally:
                    # Absolute cleanup guarantee
                    if not success and temp_path.exists():
                        temp_path.unlink(missing_ok=True)
            except Exception as exc:
                logger.error("Unexpected error in download worker for %s: %s", node.TITLE, exc)
                return "ERROR"
        else:
            # Reached if MAX_ATTACHMENT_LOOKUPS is exhausted without a valid file stream
            logger.warning("Max redirects reached for node: %s. Aborting.", node.TITLE)
            return "ERROR"


def process_queue(
    queue: list[FileNode],
    state_path: Path,
    max_threads: int = 5,
    force_override: bool = False,
    install_dir: Path | None = None,
) -> dict[str, int | str]:
    """Processes the download queue using a thread pool.

    Args:
        queue: List of FileNodes to download.
        state_path: Path to the Playwright storage_state.json.
        max_threads: Number of concurrent downloads (capped at 10).
        force_override: If True, bypasses idempotency checks.

    Returns:
        Statistics dictionary containing total, downloaded, skipped, and error counts.
    """
    # Deduplicate incoming queue strictly by physical target path
    unique = {}
    for node in queue:
        unique.setdefault(node.LOCAL_TARGET_PATH.resolve(), node)

    deduplicated_queue = list(unique.values())
    stats: dict[str, int | str] = {
        "total": len(deduplicated_queue),
        "downloaded": 0,
        "skipped": 0,
        "errors": 0,
        "install_dir": str(install_dir),
    }

    if not deduplicated_queue:
        return stats

    # Fail fast if the session state cannot be loaded
    test_session = _get_authenticated_session(state_path)
    if not test_session:
        logger.error("Failed to initialize authenticated session. Aborting synchronization.")
        stats["errors"] = len(deduplicated_queue)
        return stats

    # Prevent rate-limiting bans by capping max threads
    safe_max_threads = min(max_threads, 10)
    if max_threads > 10:
        logger.warning("Requested %d threads. Capping at 10 to prevent server rate-limiting.", max_threads)

    logger.info("Starting synchronization with %d concurrent threads.", safe_max_threads)

    progress_bar = tqdm(
        total=len(deduplicated_queue),
        desc="Synchronizing",
        unit="file",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
    )

    try:
        with ThreadPoolExecutor(max_workers=safe_max_threads) as executor:
            future_to_node = {
                executor.submit(_download_worker, node, state_path, force_override): node
                for node in deduplicated_queue
            }

            for future in as_completed(future_to_node):
                node = future_to_node[future]
                try:
                    result = future.result()
                    if result == "DOWNLOADED":
                        stats["downloaded"] += 1
                    elif result == "SKIPPED":
                        stats["skipped"] += 1
                    else:
                        stats["errors"] += 1
                except Exception as exc:
                    logger.error("Thread crashed abruptly for %s: %s", node.TITLE, exc)
                    stats["errors"] += 1
                finally:
                    progress_bar.update(1)
    finally:
        # Ensures terminal output remains clean even if user aborts (Ctrl+C)
        progress_bar.close()

        # Clean up pooled main-thread connection
        if hasattr(_thread_local, "session"):
            _thread_local.session.close()

    return stats
