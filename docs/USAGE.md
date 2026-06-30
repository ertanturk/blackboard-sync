# Blackboard-Sync Usage Guide

This document outlines the configuration and operational instructions for the Blackboard-Sync CLI.

---

## Environment Configuration & Setup Wizard

The application does **not** require or store plaintext credentials (passwords) anywhere on your disk. Passwords are securely stored in your operating system's native credential vault (macOS Keychain, Windows Credential Locker, or Linux Secret Service).

You do **not** need to manually create configuration files. On your first execution, Blackboard-Sync will automatically launch an **Interactive Setup Wizard**. It will prompt you for:

1. Your Blackboard Username
2. Your Blackboard Base URL (Defaults to `https://mef.blackboard.com/`)
3. The Target Academic Term (e.g., `2024-2025`)

The wizard will then auto-generate the `.env` file securely.

**TARGET_TERM Constraints:**

- Must strictly follow the `YYYY-YYYY` format.
- The starting year cannot be earlier than `2024`.
- The span between the start and end year must be exactly one year.

---

## Authentication Workflow

Because Blackboard enforces MFA, the system uses a secure session handoff strategy combined with system keyring storage.

1. **Secure Password Prompt:** If your password is not found in the system keyring, the CLI will securely prompt you for it (hidden input) and save it to your OS vault.
2. **Session Generation:** On your first execution, the CLI will launch a visible browser window. You must manually log in and complete your device's MFA challenge.
3. **Session Handoff:** Once the dashboard loads successfully, the system will automatically intercept the authentication cookies, serialize them to `.state/storage_state.json`, and close the browser.
4. **Headless Operation:** All subsequent executions will run completely headlessly using these saved tokens. If the session expires, the system will automatically use the keyring password to re-authenticate.

---

## Command Line Interface

The application exposes the global `bb` command.

### Syntax

```bash
bb [OPTIONS]

Options:
  -c, --course TEXT             (Required) The target course code to synchronize. The parser uses fuzzy matching, so CS301 or CS 301 are both acceptable.

  -f, --force                   (Optional) Bypasses the local filesystem idempotency checks. Forces the downloader to redownload and overwrite all discovered materials.

  -h, --headful                 (Optional) Overrides the default headless execution. Opens a visible browser window. Strictly intended for debugging UI hangs or unexpected DOM changes.

  -ra, --reset-auth             (Optional) Resets saved credentials and session state. Deletes your password from the OS keyring and removes the saved session cookie, forcing a fresh login.

  -n, --dry-run                 (Optional) Runs in dry mode. Discovers materials but no files will be downloaded.

  -d, --download-path TEXT      (Optional) Specifies the directory where downloaded materials should be saved. Defaults to the current directory.

  -s, --skip-confirmation        (Optional) Skips confirmation prompts before downloading files.

  -q, --quiet                   (Optional) Suppresses all output except for error messages.

  -v, --verbose                 (Optional) Enables verbose output, including progress bars and detailed logging.

  --help                        Shows the help message and exits.

```

---

## Examples

Basic Synchronization:

```bash
bb -c COMP206
```

Forced Overwrite:

```bash
bb -c COMP206 -f
```

Debug Mode (Visible Browser & Forced Download):

```bash
bb -c COMP206 --headful --force
```

Download Path Override:

```bash
bb -c COMP206 -d /path/to/downloads
```

Reset Authentication (If you changed your Blackboard password):

```bash
bb -c COMP206 --reset-auth
```

---

## Output Location

By default, all synchronized course materials are saved to the `downloads/` directory located in the project root. Files are organized automatically into subdirectories corresponding to their course codes and remote Blackboard folder structures.
