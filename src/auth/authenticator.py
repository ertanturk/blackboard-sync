"""Authentication module for Blackboard-Sync.

Handles Hybrid MFA auto-login and session state persistence via Playwright.
"""

import json
import logging
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.config import Config

logger = logging.getLogger(__name__)

# Core Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = BASE_DIR / ".state"
STATE_FILE = STATE_DIR / "storage_state.json"


def ensure_state_security() -> None:
    """Ensures the state directory and file exist with secure permissions.

    Creates the directory with 0o700 permissions to avoid TOCTOU races.
    If the state file exists, enforces 0o600 permissions to protect
    sensitive session cookies from unauthorized read access.
    """
    try:
        STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        STATE_DIR.chmod(0o700)

        if STATE_FILE.exists():
            STATE_FILE.chmod(0o600)
    except OSError as e:
        logger.warning("Could not enforce strict permissions on state directory/file: %s", e)


def get_browser_state_path() -> Path | None:
    """Checks for the existence and validity of a saved browser session.

    Validates that the file exists, is readable, and contains at least one
    cookie rather than just checking for a non-empty list.

    Returns:
        The Path to the state file if valid, otherwise None.
    """
    if not STATE_FILE.is_file() or STATE_FILE.stat().st_size == 0:
        return None

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        cookies = data.get("cookies") if isinstance(data, dict) else None

        if isinstance(cookies, list) and len(cookies) > 0:
            return STATE_FILE

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
    password = os.getenv("BLACKBOARD_PASSWORD")
    base_url = os.getenv("BLACKBOARD_BASE_URL", "https://mef.blackboard.com/")

    if not username or not password:
        logger.error("Missing credentials. Please check your .env file.")
        return None

    # Force headful on first login so the user can complete MFA interactively.
    is_first_login = get_browser_state_path() is None
    show_browser = headful or is_first_login

    ensure_state_security()
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
            context.storage_state(path=STATE_FILE)
            ensure_state_security()
            logger.info("[green] Session successfully saved to %s[/green]", STATE_FILE.name)

            return STATE_FILE

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
    state_path = get_browser_state_path()

    if state_path:
        logger.info("[green] Valid session found. Skipping login step.[/green]")
        return state_path

    logger.info("No valid session found. Initiating fresh login sequence.")
    return login(headful=headful)
