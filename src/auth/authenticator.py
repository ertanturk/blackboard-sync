"""Authentication module for Blackboard-Sync.

Handles Hybrid MFA auto-login and session state persistence via Playwright.
"""

import getpass
import hashlib
import json
import logging
import os
from pathlib import Path

import keyring
import requests
from keyring.errors import PasswordDeleteError
from playwright.sync_api import Browser, BrowserContext, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.config import Config

logger = logging.getLogger(__name__)


# Core Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = BASE_DIR / ".state"

# Keyring Service
KEYRING_SERVICE = "blackboard-sync"


def _clear_keyring_password(username: str) -> None:
    """Removes invalid password from the OS keyring to prevent infinite failure loops."""
    try:
        keyring.delete_password(KEYRING_SERVICE, username)
        logger.info("Invalid password removed from system keyring.")
    except PasswordDeleteError:
        pass


def get_state_file_path(username: str) -> Path:
    """Gets the path to the state file for the given username."""
    safe_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()[:16]
    return STATE_DIR / f"state_{safe_hash}.json"


def _is_state_valid(state_file: Path) -> bool:
    """Performs a sub-second headless validation of the saved cookies.

    Pings the Blackboard API to ensure the session is still active on the server.
    """
    try:
        with Path(state_file).open("r", encoding="utf-8") as f:
            state = json.load(f)

        session = requests.Session()
        for cookie in state.get("cookies", []):
            session.cookies.set(cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"])

        base_url = os.getenv("BLACKBOARD_BASE_URL", "https://mef.blackboard.com").rstrip("/")
        test_url = f"{base_url}/learn/api/v1/users/me"

        # Fast timeout so it doesn't slow down the boot process
        response = session.get(test_url, timeout=5)

        # 200 OK means the cookies are alive and authorized
        return response.status_code == 200
    except Exception as e:
        logger.debug("Session validation check failed: %s", e)
        return False


def ensure_state_security(state_file: Path) -> None:
    """Ensures the state directory and file exist with secure permissions.

    Creates the directory with 0o700 permissions to avoid TOCTOU races.
    If the state file exists, enforces 0o600 permissions to protect
    sensitive session cookies from unauthorized read access.
    """
    try:
        STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        STATE_DIR.chmod(0o700)

        if state_file.exists():
            state_file.chmod(0o600)
    except OSError as e:
        logger.warning("Could not enforce strict permissions on state directory/file: %s", e)


def get_browser_state_path(username: str) -> Path | None:
    """Checks for the existence and validity of a saved browser session.

    Validates that the file exists, is readable, and contains at least one
    cookie rather than just checking for a non-empty list.

    Returns:
        The Path to the state file if valid, otherwise None.
    """

    state_file = get_state_file_path(username)
    if not state_file.is_file() or state_file.stat().st_size == 0:
        return None

    if not _is_state_valid(state_file=state_file):
        logger.warning("Saved session expired on the server. Deleting stale state...")
        state_file.unlink(missing_ok=True)
        return None

    logger.debug("Active session validated via API.")

    try:
        with state_file.open("r", encoding="utf-8") as f:
            data = json.load(f)

        cookies = data.get("cookies") if isinstance(data, dict) else None

        if isinstance(cookies, list) and len(cookies) > 0:
            return state_file

        logger.warning(
            "State file exists but contains no valid cookies. Ignoring.",
        )
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("State file is corrupted or unreadable: %s", e)

    return None


def _close_browser(browser: Browser | None, context: BrowserContext | None) -> None:
    """Closes the Playwright browser context and browser instance safely.

    Args:
        browser: The Playwright Browser instance, or None.
        context: The Playwright BrowserContext instance, or None.
    """
    try:
        if context is not None:
            context.close()
    except PlaywrightError as e:
        logger.warning("Failed to close browser context: %s", e)

    try:
        if browser is not None:
            browser.close()
    except PlaywrightError as e:
        logger.warning("Failed to close browser: %s", e)


def login(headful: bool = False) -> Path | None:
    """Launches Playwright, authenticates, and saves session state.

    Forces headful mode on first login to allow manual MFA completion.

    Args:
        headful: If True, launches the browser visibly.

    Returns:
        The Path to the saved storage_state.json, or None on failure.
    """
    import os

    username = os.getenv("BLACKBOARD_USERNAME")
    password = keyring.get_password(KEYRING_SERVICE, username) if username else None
    base_url = os.getenv("BLACKBOARD_BASE_URL", "https://mef.blackboard.com/")

    if not username or not password:
        logger.error("Missing credentials. Please check your .env file and keyring.")
        return None

    state_file = get_state_file_path(username)

    # Force headful on first login so the user can complete MFA interactively.
    is_first_login = get_browser_state_path(username=username) is None
    show_browser = headful or is_first_login

    ensure_state_security(state_file)
    logger.info("Initializing Playwright browser...")

    cfg = Config()
    browser: Browser | None = None
    context: BrowserContext | None = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not show_browser)
            context = browser.new_context()
            page = context.new_page()

            try:
                logger.info("Navigating to login page: %s", base_url)
                page.goto(base_url, wait_until="domcontentloaded", timeout=cfg.NETWORK_WAIT_MS)

                try:
                    cookie_btn = page.locator(
                        "button:has-text('Agree'), button:has-text('Accept'), "
                        "button:has-text('Kabul'), #agree_button"
                    ).first
                    cookie_btn.click(timeout=cfg.SHORT_WAIT_MS)
                    logger.info("Dismissed cookie consent banner.")
                except PlaywrightTimeoutError:
                    pass  # Expected when no cookie banner is present.

                user_input = page.locator("input[name*='user'], input[type='email'], #user_id").first
                user_input.wait_for(state="visible", timeout=cfg.USER_WAIT_MS)
                user_input.fill(username)

                pass_input = page.locator("input[type='password'], #password").first
                pass_input.wait_for(state="visible", timeout=cfg.USER_WAIT_MS)
                pass_input.fill(password)

                submit_btn = page.locator("button[type='submit'], input[type='submit'], #entry-login").first
                submit_btn.wait_for(state="visible", timeout=cfg.USER_WAIT_MS)
                submit_btn.click()

                try:
                    error_locator = page.locator("#loginErrorMessage")
                    if error_locator.is_visible(timeout=cfg.SHORT_WAIT_MS):
                        error_text = error_locator.inner_text().strip()
                        logger.error("Authentication failed: %s", error_text)
                        _clear_keyring_password(username)
                        return None
                except PlaywrightTimeoutError:
                    pass

                logger.info("Credentials submitted. Awaiting redirect...")

            except PlaywrightTimeoutError as e:
                logger.error(
                    "Network timeout or missing UI elements. Is Blackboard down? Details: %s",
                    e,
                )
                return None

            try:
                # Scenario 1: Fast login — no MFA triggered.
                page.wait_for_url("**/ultra/**", timeout=cfg.FAST_LOGIN_WAIT_MS)
                logger.info("[green] Direct login successful (No MFA).[/green]")

            except PlaywrightTimeoutError:
                # Scenario 2: Redirect was intercepted by a validation error or MFA screen.

                # Check for invalid credentials BEFORE assuming MFA.
                error_locator = page.locator(
                    "#loginErrorMessage, .form-error, .bad-credentials, "
                    "text=/[Ii]nvalid|[Ii]ncorrect|[Gg]eçersiz|[Hh]atal[ıi]/"
                ).first

                if error_locator.is_visible(timeout=cfg.SHORT_WAIT_MS):
                    error_text = error_locator.inner_text().strip().replace("\n", " ")
                    logger.error(
                        "Authentication failed: Invalid credentials provided. (%s)",
                        error_text,
                    )
                    _clear_keyring_password(username)
                    return None

                # No error visible — treat as a legitimate MFA prompt.
                logger.warning("Fast login failed. Waiting for manual MFA approval...")
                logger.info("Please complete the 2FA prompt on your device. (Timeout: 2 Minutes)")

                try:
                    page.wait_for_url("**/ultra/**", timeout=cfg.MFA_USER_WAIT_MS)
                    logger.info("[green] MFA approved and system accessed.[/green]")
                except PlaywrightTimeoutError as e:
                    logger.error(
                        "Authentication failed: MFA timeout or unhandled UI state. Details: %s",
                        e,
                    )
                    return None

            logger.info("Saving session cookies and local storage...")
            context.storage_state(path=state_file)
            ensure_state_security(state_file)
            logger.info("[green] Session successfully saved to %s[/green]", state_file.name)

            return state_file

    except PlaywrightError as e:
        logger.error("Playwright encountered a critical error: %s", e)
        return None

    finally:
        _close_browser(browser, context)


def login_or_load_state(headful: bool = False) -> Path | None:
    """Orchestrator function called by main.py (Phase 1).

    Checks for a valid session state and bypasses login if found.
    Otherwise, triggers the interactive login and MFA flow.

    Args:
        headful: Request visible browser execution.

    Returns:
        Path to the valid state file, or None if authentication failed.
    """

    username = os.getenv("BLACKBOARD_USERNAME")
    if not username:
        logger.error("Missing credentials. Please check your .env file.")
        return None

    state_file = get_browser_state_path(username=username)

    if state_file:
        logger.info("[green] Valid session found. Skipping login step.[/green]")
        return state_file

    logger.info("No valid session found. Initiating fresh login sequence.")
    return login(headful=headful)
