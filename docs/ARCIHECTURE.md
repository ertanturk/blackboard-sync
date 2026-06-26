# SYSTEM ARCHITECTURE: BLACKBOARD-SYNC

## 1. SYSTEM OVERVIEW

Blackboard-Sync is a robust, modular CLI tool built with Python, Playwright, and Requests. It is designed to navigate the Blackboard Ultra Single Page Application (SPA), handle Hybrid Multi-Factor Authentication (MFA), crawl nested course directories across both Classic and Modern layouts, and idempotently download course materials at high speeds using multithreading.

---

## 2. DIRECTORY STRUCTURE & MODULAR RESPONSIBILITIES

The system enforces strict Separation of Concerns (SoC). Discovery logic (DOM/API parsing) is entirely isolated from execution logic (Downloading).

```bash
blackboard-sync/
├── pyproject.toml # Build system configuration and CLI entry point definitions
├── .env # Environment credentials and configurations
├── downloads/ # Default local mirroring destination for downloaded files
├── .state/ # Directory holding Playwright's serialized storage_state.json
├── docs/ # Project documentation (USAGE.md, ARCHITECTURE.md)
└── src/
├── **init**.py
├── main.py # CLI Orchestrator (Typer/Rich). Chains Phase 1 -> 2 -> 3.
├── config.py # Loads .env, defines global timeouts, exclusions, and paths.
├── logger/
│ └── logger.py # Unified Rich-based logging system.
├── models/
│ └── file_node.py # DataClass representing a target file and its metadata.
├── auth/
│ └── authenticator.py # Phase 1: Hybrid MFA logic and API-based session validation.
├── crawler/
│ ├── navigator.py # Navigates the SPA, handles fuzzy matching, and enters courses.
│ └── parser.py # Phase 2: Hybrid discovery (Classic DOM parsing & Modern JSON API).
└── downloader/
└── sync_manager.py # Phase 3: High-concurrency, idempotent ThreadPool synchronizer.
```

---

## 3. EXECUTION FLOW

### Phase 1: Authentication & Session Validation (`authenticator.py`)

1. **Validation Check:** Reads `.state/storage_state.json` and issues a sub-second headless API ping to `/learn/api/v1/users/me` using the `requests` library.
2. **State Branching:**
   -> **Valid:** Session is alive. Proceeds immediately to Phase 2.
   -> **Invalid/Missing:** Deletes stale state and launches a headful Playwright browser.
3. **MFA Capture:** Awaits user manual login and MFA approval. Once the Blackboard stream/course URL is detected, it serializes the active cookies to `.state/storage_state.json` and terminates the browser.

### Phase 2: Discovery & Parsing (`crawler/`)

1. **Navigation:** `navigator.py` forces "List View", fuzzy-matches the target course code against the `TARGET_TERM`, and awaits the `/outline` route.
2. **Layout Detection:** `parser.py` detects if the course uses the Classic layout (`/cl/outline`) or the Modern Ultra layout (`/outline`).
3. **Classic DOM Parsing:** -> Extracts the "Course Content" root URL.
   -> Navigates via direct URLs (`listContent.jsp`) to bypass UI wrappers.
   -> Parses standard `ul.contentList` directories and `ul#tocTree` Learning Units (Modules).
4. **Modern API Parsing:**
   -> Bypasses the DOM completely. Queries `/learn/api/v1/courses/{id}/contents/{node_id}/children`.
   -> Recursively traverses `resource/x-bb-folder` and `resource/x-bb-lesson`.
5. **Node Generation:** Filters out excluded folders (e.g., quizzes, assignments) and constructs a queue of `FileNode` objects populated with direct `BLACKBOARD_DOWNLOAD_URL` links.

### Phase 3: Idempotent Synchronization (`sync_manager.py`)

This phase abandons Playwright to avoid the severe memory overhead of the SPA, utilizing **Session Handoff** instead.

1. **Pre-Check (Idempotency):** Deduplicates the incoming queue and checks if `FileNode.LOCAL_TARGET_PATH` exists on the local disk. Skips if present (unless `--force` is applied).
2. **Session Handoff:** Injects Playwright's `storage_state.json` cookies into thread-local `requests.Session()` pools.
3. **Concurrent Processing:** Dispatches downloads via a `ThreadPoolExecutor` (capped at 10 workers to prevent WAF rate-limiting bans).
4. **API Resolution:** If the target URL returns a JSON pointer (common in Blackboard Ultra), the worker safely resolves the attachment ID up to 3 redirects.
5. **Atomic Writing (Safety Guard):** -> Acquires a path-based `threading.Lock`.
   -> Streams data into a unique, UUID-stamped `.part` file.
   -> Verifies written bytes against the `Content-Length` header to prevent truncated files.
   -> Atomically renames the `.part` file to the final target filename using `Path.replace()`.

---

## 4. CRITICAL ARCHITECTURAL RULES

- **Separation of Concerns:** The Crawler (Phase 2) must NEVER download files. The Downloader (Phase 3) must NEVER parse HTML/DOM elements. They communicate strictly via the `FileNode` data structure.
- **Mass Downloading Strategy:** Do NOT use Playwright's native `page.expect_download()` for bulk synchronization. The memory overhead of rendering Blackboard's file previewers causes crashes. ALWAYS use the Cookie Handoff strategy to Python `requests`.
- **Atomic I/O:** Never stream network bytes directly into the final target file. Network interruptions result in permanently corrupted partial files that trick the idempotency checker. ALWAYS stream to `.part` and atomically rename upon completion.
- **Thread Safety:** `requests.Session` is NOT natively thread-safe when dealing with connection pools. Always use `threading.local()` to grant each worker its own isolated session context.
- **Filesystem Safety:** Rely exclusively on `pathlib.Path` for all path manipulations to guarantee cross-platform compatibility (Windows, macOS, Linux). Use strict regex sanitization to prevent path-traversal vulnerabilities from malicious remote filenames.
