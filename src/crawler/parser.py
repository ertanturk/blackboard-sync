"""Parser module for Blackboard-Sync.

Implements a hybrid discovery logic:
1. Modern Layout: Uses Blackboard's internal JSON API via Playwright APIRequestContext.
2. Classic Layout: Direct DOM parsing of listContent.jsp with URL-based recursion.
"""

import logging
import os
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.config import Config
from src.models.file_node import FileNode

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def _sanitize_name(name: str) -> str:
    """Removes invalid OS characters and prevents path traversal vulnerabilities.

    Args:
        name: The raw string to sanitize.

    Returns:
        str: A safe, non-empty string for filesystem paths.
    """
    if not name or not name.strip():
        return "_unnamed_"

    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()

    if cleaned in (".", ".."):
        return f"_{cleaned}_"

    return cleaned or "_unnamed_"


def _extract_extension(filename: str) -> str:
    """Safely extracts the file extension from a filename.

    Args:
        filename: The full filename string.

    Returns:
        str: The lowercase extension including the dot (e.g. '.pdf'), or '' if none found.
    """
    match = re.search(r"(\.[a-zA-Z0-9]+)$", filename)
    return match.group(1).lower() if match else ""


def _should_exclude_folder(folder_name: str) -> bool:
    """Checks if a folder name contains any excluded keyword.

    Args:
        folder_name: The raw folder title from the DOM or API.

    Returns:
        bool: True if the folder should be skipped.
    """
    clean_name = folder_name.lower()
    return any(excluded in clean_name for excluded in Config.EXCLUDE_FOLDERS)


def _is_classic_layout(page: Page) -> bool:
    """Determines whether the current course uses Classic or Modern Ultra layout.

    Classic layout URLs contain '/cl/outline'.
    Modern layout URLs contain '/outline' without '/cl/'.

    Args:
        page: The active Playwright Page instance.

    Returns:
        bool: True if Classic layout, False if Modern Ultra layout.
    """
    return "/cl/outline" in page.url


def _get_classic_content_url(page: Page, base_url: str) -> str | None:
    """Finds the initial 'Course Content' URL from the Classic left-hand navigation menu.

    Args:
        page: The active Playwright Page instance.
        base_url: The root URL of the Blackboard instance.

    Returns:
        str | None: The full URL to the content page, or None if not found.
    """
    logger.info("Locating 'Course Content' menu in Classic Layout...")

    # The classic menu is typically housed inside an iframe when viewed via Ultra
    iframe_selector = "iframe[name='classic-learn-iframe'], iframe[id='classic-learn-iframe']"
    iframe_query = page.locator(iframe_selector)

    frame = page.frame_locator(iframe_selector) if iframe_query.count() > 0 else page

    try:
        for kw in Config.KEYWORDS:
            # Matches standard BB Navigation hierarchies based on HTML provided
            loc = frame.locator(
                f"div.locationPane nav#navigationPane li a:has(span[title='{kw}']), "
                f"ul#courseMenuPalette_contents li a:has(span[title='{kw}'])"
            ).first

            if loc.count() > 0:
                href = loc.get_attribute("href")
                if href:
                    return f"{base_url}{href}" if href.startswith("/") else href
    except PlaywrightError as e:
        logger.error("Failed to extract Classic content URL: %s", e)

    return None


def _extract_classic_bb_id(li_element: Any) -> str:
    """Extracts the Blackboard content ID from a classic listContent.jsp <li> element.

    The <li> id attribute has the format 'contentListItem:_2128847_1'.
    The inner <div class="item"> has an ID attribute matching '_2128847_1'.

    Args:
        li_element: A Playwright Locator pointing to the <li.liItem> element.

    Returns:
        str: The extracted BB content ID (e.g. '_2128847_1'), or '' if not found.
    """
    # Primary: inner div.item ID attribute (most reliable)
    try:
        item_div = li_element.locator("div.item").first
        if item_div.count() > 0:
            div_id = item_div.get_attribute("ID") or item_div.get_attribute("id") or ""
            if div_id:
                return div_id
    except PlaywrightError:
        pass

    # Fallback: parse the <li> id attribute
    try:
        raw_id = li_element.get_attribute("id") or ""
        if ":" in raw_id:
            return raw_id.split(":")[1]
        return raw_id
    except PlaywrightError:
        return ""


def _walk_classic_directory(
    page: Page,
    url: str,
    current_path: Path,
    download_queue: list[FileNode],
    visited_urls: set[str],
    max_depth: int = 8,
) -> None:
    """Recursively walks a Classic layout content directory using direct URL navigation.

    Navigates to listContent.jsp URLs, parses the DOM for files and folders,
    and recurses into subdirectories. Maintains a visited URL set to prevent cycles.

    Args:
        page: The active Playwright Page instance.
        url: The listContent.jsp URL to visit.
        current_path: The local filesystem path for this directory level.
        download_queue: Shared list collecting FileNode objects for download.
        visited_urls: Set of already-visited URLs to prevent infinite recursion.
        max_depth: Maximum recursion depth as a circuit breaker.
    """
    if max_depth <= 0:
        logger.warning("Max recursion depth reached in Classic walk. Aborting branch at: %s", url)
        return

    if url in visited_urls:
        logger.debug("Skipping already-visited Classic URL: %s", url)
        return

    visited_urls.add(url)
    logger.debug("Walking Classic directory: %s", url)

    cfg = Config()

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=cfg.NETWORK_WAIT_MS)
        page.locator("ul#content_listContainer, ul.contentList").wait_for(
            state="visible", timeout=cfg.USER_WAIT_MS
        )
    except PlaywrightTimeoutError:
        logger.debug("Directory at %s appears empty or timed out.", url)
        return
    except PlaywrightError as e:
        logger.warning("Failed to navigate to classic directory '%s': %s", url, e)
        return

    items = page.locator("li.liItem").all()
    folders_to_visit: list[tuple[str, Path]] = []
    base_url = os.getenv("BLACKBOARD_BASE_URL", "https://mef.blackboard.com/").rstrip("/")

    for item in items:
        try:
            icon = item.locator("img.item_icon").first
            if icon.count() == 0:
                continue

            alt = (icon.get_attribute("alt") or "").lower()
            src = (icon.get_attribute("src") or "").lower()

            is_folder = "folder" in alt or "folder_on" in src
            # "Item" alt (document_on.svg) = embedded/linked content (SharePoint, video) — skip
            is_file = alt == "file" or "file_on" in src

            if not is_folder and not is_file:
                logger.debug("Skipping non-file, non-folder item (alt='%s').", alt)
                continue

            title_node = item.locator("h3").first
            if title_node.count() == 0:
                continue

            title_text = title_node.inner_text().strip()
            if not title_text:
                continue

            sanitized_title = _sanitize_name(title_text)

            if is_folder:
                if _should_exclude_folder(title_text):
                    logger.debug("Skipping excluded folder: %s", title_text)
                    continue

                link = item.locator("h3 a").first
                if link.count() > 0:
                    href = link.get_attribute("href") or ""
                    if href:
                        full_url = f"{base_url}{href}" if href.startswith("/") else href
                        folders_to_visit.append((full_url, current_path / sanitized_title))

            elif is_file:
                ext = _extract_extension(title_text)
                if ext and ext not in Config.VALID_EXTENSIONS:
                    logger.debug("Skipping file with unsupported extension '%s': %s", ext, title_text)
                    continue

                bb_id = _extract_classic_bb_id(item)
                if not bb_id:
                    logger.warning("Could not extract BB ID for item '%s'. Skipping.", title_text)
                    continue

                node = FileNode(
                    TITLE=title_text,
                    FILE_TYPE=ext.lstrip(".") if ext else "document",
                    LOCAL_TARGET_PATH=current_path / sanitized_title,
                    BLACKBOARD_ID=bb_id,
                    IS_FOLDER=False,
                )
                download_queue.append(node)
                logger.debug("Queued (classic): %s", node)

        except PlaywrightError as e:
            logger.debug("Error parsing classic DOM item. Skipping: %s", e)

    for next_url, next_path in folders_to_visit:
        _walk_classic_directory(page, next_url, next_path, download_queue, visited_urls, max_depth - 1)


def _parse_modern_api(
    page: Page,
    course_id: str,
    node_id: str,
    current_path: Path,
    download_queue: list[FileNode],
    visited_ids: set[str],
    max_depth: int = 8,
) -> None:
    """Recursively queries the Blackboard internal JSON API to build the download queue.

    Uses isReviewable and contentHandler fields to distinguish files from folders.
    Handles API pagination via the nextPage field in the paging response block.

    Args:
        page: The Playwright Page instance (used for its authenticated APIRequestContext).
        course_id: The internal Blackboard course identifier (e.g. '_330725_1').
        node_id: The content node identifier to query ('ROOT' for top level).
        current_path: The local filesystem path for this directory level.
        download_queue: Shared list collecting FileNode objects for download.
        visited_ids: Set of already-visited node IDs to prevent cycles.
        max_depth: Maximum recursion depth as a circuit breaker.
    """
    if max_depth <= 0:
        logger.warning("Max recursion depth reached in API walk. Aborting branch at node: %s", node_id)
        return

    if node_id in visited_ids:
        logger.debug("Skipping already-visited API node: %s", node_id)
        return

    visited_ids.add(node_id)

    base_url = os.getenv("BLACKBOARD_BASE_URL", "https://mef.blackboard.com/").rstrip("/")
    offset = 0
    limit = 1000

    while True:
        params = urlencode({"limit": limit, "offset": offset})
        api_url = f"{base_url}/learn/api/v1/courses/{course_id}/contents/{node_id}/children?{params}"

        try:
            response = page.context.request.get(api_url)
        except PlaywrightError as e:
            logger.error("Request failed for API node '%s': %s", node_id, e)
            return

        if not response.ok:
            logger.warning(
                "API returned HTTP %s for node '%s'. Directory may be empty or restricted.",
                response.status,
                node_id,
            )
            return

        try:
            data: dict[str, Any] = response.json()
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to parse JSON response for node '%s': %s", node_id, e)
            return

        results: list[dict[str, Any]] = data.get("results", [])

        for item in results:
            title: str = (item.get("title") or "").strip()
            if not title:
                logger.debug("Skipping API item with empty title (id=%s).", item.get("id"))
                continue

            sanitized_title = _sanitize_name(title)
            handler: str = item.get("contentHandler", "")
            item_id: str = item.get("id", "")
            is_reviewable: bool = item.get("isReviewable", False)

            if not item_id:
                logger.debug("Skipping API item with no id (title='%s').", title)
                continue

            if handler == "resource/x-bb-folder":
                # isBbPage=True means a Blackboard-rendered page, not a real folder
                content_detail: dict[str, Any] = item.get("contentDetail", {})
                folder_detail: dict[str, Any] = content_detail.get("resource/x-bb-folder", {})
                if folder_detail.get("isBbPage", False):
                    logger.debug("Skipping isBbPage folder: %s", title)
                    continue

                if is_reviewable:
                    # isReviewable=True on a folder is unusual; treat cautiously as skip
                    logger.debug("Skipping reviewable folder (unexpected state): %s", title)
                    continue

                if _should_exclude_folder(title):
                    logger.debug("Skipping excluded folder: %s", title)
                    continue

                logger.debug("Recursing into folder: %s (id=%s)", title, item_id)
                _parse_modern_api(
                    page,
                    course_id,
                    item_id,
                    current_path / sanitized_title,
                    download_queue,
                    visited_ids,
                    max_depth - 1,
                )

            elif handler == "resource/x-bb-file" and is_reviewable:
                # Only collect files that are marked reviewable (student-accessible)
                ext = _extract_extension(title)
                if ext and ext not in Config.VALID_EXTENSIONS:
                    logger.debug("Skipping file with unsupported extension '%s': %s", ext, title)
                    continue

                node = FileNode(
                    TITLE=title,
                    FILE_TYPE=ext.lstrip(".") if ext else "document",
                    LOCAL_TARGET_PATH=current_path / sanitized_title,
                    BLACKBOARD_ID=item_id,
                    IS_FOLDER=False,
                )
                download_queue.append(node)
                logger.debug("Queued (API): %s", node)

            else:
                logger.debug(
                    "Skipping item handler='%s' isReviewable=%s title='%s'.",
                    handler,
                    is_reviewable,
                    title,
                )

        # Pagination: continue if nextPage is set and non-empty
        paging: dict[str, Any] = data.get("paging", {})
        next_page: str = paging.get("nextPage", "")
        if next_page:
            # nextPage may be a full URL or a relative path; extract offset from it
            try:
                parsed = urlparse(next_page)
                qs = parse_qs(parsed.query)
                next_offset = int(qs.get("offset", [str(offset + limit)])[0])
                if next_offset <= offset:
                    # Guard against non-advancing pagination
                    logger.warning("Pagination offset did not advance. Stopping.")
                    break
                offset = next_offset
                logger.debug("Fetching next page at offset=%d for node '%s'.", offset, node_id)
            except (ValueError, KeyError) as e:
                logger.warning("Could not parse nextPage offset for node '%s': %s", node_id, e)
                break
        else:
            break


def parse_course_content(page: Page, course_code: str, install_dir: Path) -> list[FileNode]:
    """Main orchestrator for the discovery phase (Phase 2).

    Identifies the Blackboard layout type from the current URL and routes
    execution to either the Classic DOM parser or the Modern JSON API crawler.

    Args:
        page: The active Playwright Page instance, positioned on the course outline.
        course_code: The target course code used for local directory naming.
        install_dir: The root downloads directory from Config.

    Returns:
        A list of FileNode objects ready for the Downloader phase.
    """
    download_queue: list[FileNode] = []

    # Validate current URL contains a parseable course_id
    match = re.search(r"/courses/(_\d+_\d+)", page.url)
    if not match:
        logger.error("Could not extract internal course_id from URL '%s'. Aborting discovery.", page.url)
        return download_queue

    course_id = match.group(1)

    base_url = os.getenv("BLACKBOARD_BASE_URL", "https://mef.blackboard.com/").rstrip("/")

    # Create local course directory
    course_dir = install_dir / _sanitize_name(course_code)
    try:
        course_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("Failed to create course directory '%s': %s", course_dir, e)
        return download_queue

    if _is_classic_layout(page):
        logger.info("Classic Layout detected for course '%s'. Initializing DOM crawler...", course_code)
        content_url = _get_classic_content_url(page, base_url)

        if not content_url:
            logger.error("Could not locate Classic 'Course Content' URL for '%s'. Aborting.", course_code)
            return download_queue

        logger.info("Starting recursive Classic DOM scan from: %s", content_url)
        _walk_classic_directory(page, content_url, course_dir, download_queue, visited_urls=set())

    else:
        logger.info(
            "Modern Ultra Layout detected for course '%s'. Initializing JSON API crawler...", course_code
        )
        _parse_modern_api(page, course_id, "ROOT", course_dir, download_queue, visited_ids=set())

    logger.info(
        "Discovery complete for '%s'. %d file(s) queued for synchronization.",
        course_code,
        len(download_queue),
    )
    return download_queue
