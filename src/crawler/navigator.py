"""Navigator module for Blackboard-Sync.

Handles searching, filtering, and validating course cards on Blackboard Ultra.
"""

import logging
import os
import re

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.config import Config

logger = logging.getLogger(__name__)


def _sanitize_string(text: str) -> str:
    """Removes spaces, hyphens, and underscores for fuzzy string matching.

    Args:
        text: The raw string to sanitize.

    Returns:
        str: An uppercase, alphanumeric-only representation of the string.
    """
    return re.sub(r"[\s\-_]", "", text).upper()


def ensure_list_view(page: Page) -> None:
    """Forces the Blackboard UI into 'List View' to standardize DOM structure.

    Checks the current layout toggle and clicks the List view button if the
    user currently has the Grid view active.

    Args:
        page: The active Playwright Page instance.
    """
    logger.info("Verifying UI layout mode...")
    try:
        list_view_btn = page.locator("button[aria-label*='List'], button[title*='List']").first
        list_view_btn.wait_for(state="visible", timeout=Config.CLICK_WAIT_TIMEOUT)

        is_pressed = list_view_btn.get_attribute("aria-pressed")
        if is_pressed != "true":
            list_view_btn.click()
            page.wait_for_load_state("networkidle")
            logger.info("Switched to List view layout.")
        else:
            logger.debug("Already in List view layout.")
    except PlaywrightTimeoutError:
        logger.warning("View toggle button not found. Continuing with current layout.")
    except PlaywrightError as e:
        logger.warning("Failed to interact with view toggle: %s", e)


def navigate_to_course(page: Page, course_code: str) -> bool:
    """Navigates to the Courses panel, searches, and enters the target course.

    Performs fuzzy matching on the search results to handle variations in
    course naming (e.g., CS301 vs CS 301) and validates against the target term.

    Args:
        page: The active Playwright Page instance.
        course_code: The identifier for the course (e.g., 'MATH116').

    Returns:
        bool: True if the course was successfully entered, False otherwise.
    """
    if not course_code or not course_code.strip():
        logger.error("Course code cannot be empty.")
        return False

    base_url = os.getenv("BLACKBOARD_BASE_URL", "https://mef.blackboard.com").rstrip("/")
    target_term = os.getenv("TARGET_TERM")

    if not target_term:
        logger.error("TARGET_TERM is missing from the environment. Cannot validate courses.")
        return False

    sanitized_target_code = _sanitize_string(course_code)
    sanitized_target_term = _sanitize_string(target_term)

    if len(sanitized_target_code) < 3:
        logger.error(
            "Course code '%s' is too short for reliable matching (minimum 3 characters required).",
            course_code,
        )
        return False

    if not sanitized_target_code:
        logger.error("Course code '%s' contains no matchable characters after sanitization.", course_code)
        return False

    global_timeout = Config.TIMEOUT_SECONDS * 100

    try:
        courses_url = f"{base_url}/ultra/course"
        logger.info("Navigating to courses panel: %s", courses_url)

        page.goto(courses_url, wait_until="domcontentloaded", timeout=global_timeout)

        ensure_list_view(page)

        logger.info("Searching for course '%s'...", course_code)
        search_input = page.locator("#courses-overview-filter-search")
        search_input.wait_for(state="visible", timeout=Config.UI_WAIT_TIMEOUT)

        search_input.click()
        search_input.clear()
        search_input.press_sequentially(course_code, delay=50)

        page.wait_for_timeout(300)
        search_input.press("Enter")

        max_retries = int(global_timeout / 500)
        logger.info("Starting intelligent validation and awaiting SPA search results...")

        zero_results_regex = re.compile(
            r"(^0\s*(results|sonuç|öğe)|no results found|sonuç bulunamadı)", re.IGNORECASE
        )

        seen_cards = set()

        for attempt in range(max_retries):
            if (
                page.locator("div.empty.not-found").is_visible()
                or page.get_by_text(zero_results_regex).is_visible()
            ):
                logger.error("Blackboard returned 0 results for '%s'.", course_code)
                return False

            course_cards = page.locator("article.course-element-card").all()
            valid_candidates = []

            for card in course_cards:
                try:
                    card_text = card.inner_text().strip()
                    if not card_text:
                        continue
                except PlaywrightError:
                    continue

                if card_text not in seen_cards:
                    flat_text = card_text.replace("\n", " | ")
                    logger.info("Found card candidate: %s", flat_text)
                    seen_cards.add(card_text)

                is_new_card = card_text not in seen_cards

                if is_new_card:
                    seen_cards.add(card_text)
                    flat_text = card_text.replace("\n", " | ")
                    logger.info("Found card candidate: %s", flat_text)

                sanitized_card_text = _sanitize_string(card_text)

                if sanitized_target_term not in sanitized_card_text:
                    if is_new_card:
                        logger.warning("Rejected: Target term '%s' not found in text.", target_term)
                    continue

                if sanitized_target_code not in sanitized_card_text:
                    if is_new_card:
                        logger.warning("Rejected: Course code '%s' not found in text.", course_code)
                    continue

                if sanitized_target_code not in sanitized_card_text:
                    if is_new_card:
                        logger.warning("Rejected: Course code '%s' not found in text.", course_code)
                    continue

                if re.search(r"\(Private\)|\(Closed\)|\(Hidden\)", card_text, re.IGNORECASE):
                    if is_new_card:
                        logger.warning(
                            "Rejected: Found matching course but it is inaccessible (Private/Closed)."
                        )
                    continue

                valid_candidates.append((card, card_text))

            if len(valid_candidates) > 1:
                logger.error(
                    "Ambiguous search: Found %d accessible courses matching '%s' for term '%s'. "
                    "Please provide a more specific course code.",
                    len(valid_candidates),
                    course_code,
                    target_term,
                )
                return False

            if len(valid_candidates) == 1:
                card, card_text = valid_candidates[0]
                logger.info("[green] Valid course matched: %s (%s)[/green]", course_code, target_term)

                try:
                    link = card.locator("a.course-title").first
                    link.wait_for(state="visible", timeout=Config.CLICK_WAIT_TIMEOUT)
                    link.click()
                except PlaywrightTimeoutError:
                    logger.error("The matched course link exists but is not clickable.")
                    continue
                except PlaywrightError as e:
                    logger.warning("Failed to click matched course card link, trying next candidate: %s", e)
                    continue

                # Both layouts: classic -> /cl/outline, modern -> /outline
                page.wait_for_url(re.compile(r".*/outline.*"), timeout=global_timeout)
                page.wait_for_load_state("networkidle")
                logger.info("[green] Successfully entered course content view.[/green]")

                return True

            page.wait_for_timeout(500)

        logger.error(
            "Could not find an open, accessible course for '%s' in term '%s'.", course_code, target_term
        )
        return False

    except PlaywrightTimeoutError as e:
        logger.error("Navigation timed out. The Blackboard UI did not load as expected. Details: %s", e)
        return False
    except PlaywrightError as e:
        logger.error("Playwright encountered an interaction error during navigation: %s", e)
        return False
