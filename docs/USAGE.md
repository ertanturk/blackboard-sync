# Blackboard-Sync Usage Guide

This document outlines the configuration and operational instructions for the Blackboard-Sync CLI.

---

## Environment Configuration

Before operating the tool, you must configure the environment variables. The application no longer requires or stores plaintext credentials (username/password) due to the implementation of interactive Hybrid Multi-Factor Authentication (MFA).

Create a `.env` file in the root directory of the project with the following required variables:

```bash
# .env
BLACKBOARD_USERNAME=<blackboard_username>
BLACKBOARD_PASSWORD=<blackboard_password>
BLACKBOARD_BASE_URL=https://mef.blackboard.com/
TARGET_TERM=<term-lookup> # eg 2024-2025
```

# TARGET_TERM Constraints:

- Must strictly follow the YYYY-YYYY format.
- The starting year cannot be earlier than 2024.
- The span between the start and end year must be exactly one year.

---

## Authentication Workflow

Because Blackboard enforces MFA, the system uses a session handoff strategy.

On your first execution, the CLI will launch a visible browser window. You must manually log in and complete your device's MFA challenge. Once the dashboard loads successfully, the system will automatically intercept the authentication cookies, serialize them to .state/storage_state.json, and close the browser. All subsequent executions will run completely headlessly using these saved tokens.

## Command Line Interface

The application exposes the global bb command. The primary operation is sync.

### Syntax

```bash
bb [OPTIONS]

Options:
-c, --course TEXT (Required)
The target course code to synchronize. The parser uses fuzzy matching, so CS301 or CS 301 are both acceptable.

-f, --force (Optional)
Bypasses the local filesystem idempotency checks. Forces the downloader to redownload and overwrite all discovered materials, regardless of whether they already exist in the target directory.

-h, --headful (Optional)
Overrides the default headless execution for Phase 2 (Discovery). Opens a visible browser window. This is strictly intended for debugging UI hangs, timeout errors, or unexpected DOM changes on Blackboard.

-d TEXT, --download-path TEXT (Optional)
Specifies the directory where downloaded materials should be saved. Defaults to the current directory.

--help (Optional)
Shows the help message and exits.
```

---

## Examples

Basic Synchronization:

Bash

```
bb -c COMP206
```

Forced Overwrite:

Bash

```
bb -c COMP206 -f
```

Debug Mode (Visible Browser & Forced Download):

Bash

```
bb -c COMP206 --headful --force
```

Download Path Override:

Bash

```
bb -c COMP206 -d /path/to/downloads
```

---

## Output Location

By default, all synchronized course materials are saved to the downloads/ directory located in the project root. Files are organized automatically into subdirectories corresponding to their course codes and remote Blackboard folder structures.
