# SYSTEM ARCHITECTURE: BLACKBOARD-SYNC

## 1. SYSTEM OVERVIEW

Blackboard-Sync is a robust, modular web-automation tool built with Python and Playwright. It is designed to navigate the Blackboard Ultra Single Page Application (SPA), handle Hybrid Multi-Factor Authentication (MFA), crawl nested course directories, and idempotently download valid course materials (PDFs, Docs, Slides) while mirroring the remote directory structure locally.

## 2. DIRECTORY STRUCTURE & MODULAR RESPONSIBILITIES

The system enforces strict Separation of Concerns (SoC). Do NOT mix DOM parsing with download logic.

blackboard-sync/
├── tests/ # Local test destination
├── logs/ # Local logging destination
├── .env # Credentials (USERNAME, PASSWORD)
├── downloads/ # Local mirroring destination for downloaded files
├── .state/ # Directory holding Playwright's storage_state.json
└── src/
├── main.py # Orchestrator. Initializes Playwright, chains Phase 1 -> 2 -> 3.
├── config.py # Loads .env, defines global timeouts, retry limits, and constants.
├── logger/
│ └── logger.py # Unified logging system (stdout and file).
├── models/
│ └── file_node.py # DataClass representing a target.
│ # Fields: name (str), type (str), bb_url (str), local_path (Path).
├── auth/
│ └── authenticator.py # Phase 1: Session state loading and Hybrid MFA logic.
├── crawler/
│ ├── navigator.py # Navigates to Courses, interacts with Search, performs Fuzzy Matching.
│ └── parser.py # Handles SPA Infinite Scroll, parses DOM elements, filters non-files (e.g., Zoom links).
└── downloader/
├── sync_manager.py # Checks local filesystem via pathlib for idempotency (skip if exists).
└── fetcher.py # Uses Playwright `expect_download()`, manages Peek Panel UI state.

## 3. PHASE ALGORITHMS & STATE MACHINES

### Phase 1: Authentication (Hybrid MFA Flow)

1. CHECK: Does `storage_state.json` exist and is it valid?
   -> IF YES: Load state, skip to Phase 2.
   -> IF NO: Proceed to Step 2.
2. LOAD: Read USERNAME and PASSWORD from `.env`.
3. ACTION: Navigate to Login UI, auto-fill credentials, click Submit.
4. WAIT (Race Condition): Listen for either:
   -> Condition A (Success): Dashboard DOM element appears.
   -> Condition B (MFA): MFA iframe/UI appears.
5. HANDLE MFA (If Condition B): Pause script execution. Log "Awaiting manual MFA approval on device". Wait for Condition A to satisfy.
6. SAVE: Serialize current browser context to `storage_state.json`.

### Phase 2: Navigation & Discovery (Crawler)

1. ACTION: Click "Courses" navigation menu. Wait for network idle.
2. ACTION: Input `COURSE_CODE` into the search bar. Wait for API response.
3. VALIDATE (Fuzzy Match): Parse result cards. Do NOT use strict string matching (handle missing hyphens/spaces). Validate against the current academic term to avoid legacy courses. Click the matched course.
4. CRAWL (Depth-First Search):
   -> Trigger infinite scroll (synthetic scroll to bottom) to bypass Lazy Loading.
   -> Evaluate each DOM node.
   -> IF Node == Folder: Click to expand, recursively crawl children.
   -> IF Node == External Link / Zoom / Assignment: SKIP.
   -> IF Node == Valid Document: Extract metadata, instantiate `FileNode`, append to Download Queue.

### Phase 3: Idempotent Synchronization (Downloader)

For each `FileNode` in Queue:

1. CHECK (Idempotency): Does `FileNode.local_path / FileNode.name` exist locally?
   -> IF YES: Log "Skipping (Exists)", continue to next item.
   -> IF NO: Proceed to Step 2.
2. ACTION: Click the DOM element to trigger the Blackboard "Peek Panel" (side panel).
3. DOWNLOAD:
   -> Await `page.expect_download()`
   -> Click the "Download Original File" button inside the Peek Panel.
   -> Save stream to `FileNode.local_path`.
4. CLEANUP (CRITICAL): Click the "Close (X)" button on the Peek Panel. Wait for panel to disappear (`state="hidden"`).
   -> WARNING: Failing to close the panel will cause `ElementInterceptedException` on the next iteration.
5. REPORT: Update progress bar.

## 4. CRITICAL RULES

- NEVER use standard `requests` for downloading materials; ALWAYS use Playwright's `expect_download()` mechanism to inherit session tokens naturally.
- AVOID hardcoded `time.sleep()`. Rely strictly on `page.wait_for_selector()` and `page.wait_for_load_state('networkidle')`.
- ALWAYS handle UI blocking elements (modals, overlays, side panels) by explicitly closing them after use.
- The `pathlib` module MUST be used for all file and directory path operations to ensure cross-platform compatibility (Windows/macOS/Linux).
