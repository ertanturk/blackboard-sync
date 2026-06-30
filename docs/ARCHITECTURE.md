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

## EXECUTION FLOW

### Initial Setup (Wizard)

On the very first run, config.py intercepts the flow to run an Interactive Setup Wizard, generating a strict .env file without requesting any passwords.
Phase 1: Authentication & Session Validation (`main.py` & `authenticator.py`)

- State & Keyring Check: `main.py` checks for an active session. If missing, it checks the OS Keyring for a saved password. If no password exists, it securely prompts the user via CLI and saves it to the vault.

- Validation: `authenticator.py` reads `.state/storage_state.json` and issues a sub-second headless API ping to `/learn/api/v1/users/me` using the requests library.

- State Branching:
    - Valid: Session is alive. Proceeds immediately to Phase 2.
    - Invalid/Missing: Launches a Playwright browser, pulling the secure password from the OS Keyring to attempt auto-login.

- MFA Capture: If direct login fails due to MFA requirements, it awaits user manual MFA approval. Once the dashboard loads, it serializes the active cookies to `.state/storage_state.json` and terminates the browser.

- Auto-Recovery: If the saved keyring password is wrong (e.g., password changed), `authenticator.py` detects the invalid credentials, evicts the bad password from the Keyring, and safely halts to prompt a fresh login on the next run.

### Phase 2: Discovery & Parsing (crawler/)

- Navigation: `navigator.py` forces "List View", fuzzy-matches the target course code.

- Layout Detection: `parser.py` detects Classic (`/cl/outline`) or Modern (`/outline`) layouts.

- Classic DOM Parsing: Extracts URLs, navigates via direct links, and parses elements.

- Modern API Parsing: Bypasses DOM, queries `/learn/api/v1/courses/{id}/contents/....`

- Node Generation: Filters exclusions and populates FileNode objects.

### Phase 3: Idempotent Synchronization (`sync_manager.py`)

- Pre-Check: Deduplicates and checks idempotency against local disk.

- Session Handoff: Injects Playwright cookies into requests.Session() pools.

- Concurrent Processing: Dispatches downloads via a ThreadPoolExecutor.

- API Resolution: Resolves Blackboard Ultra JSON pointer attachments.

- Atomic Writing: Streams data to .part files with path-based locks, verifies bytes, and atomically renames.

---

## CRITICAL ARCHITECTURAL RULES

- Separation of Concerns: The Crawler must NEVER download. The Downloader must NEVER parse. The UI Prompting must reside strictly in `main.py` or `config.py`, while `authenticator.py` executes headless backend operations.

- Zero-Trust Storage: Never store plaintext passwords in .env or disk logs. Always route credential storage through keyring.

- Mass Downloading Strategy: ALWAYS use the Cookie Handoff strategy to Python requests to avoid Playwright memory overhead.

- Atomic I/O: ALWAYS stream to .part and atomically rename upon completion to prevent corrupted partial files
