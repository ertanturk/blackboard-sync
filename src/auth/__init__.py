"""Authentication Module.

Handles Hybrid MFA auto-login and session state persistence via Playwright.
"""

from .authenticator import login_or_load_state

__all__ = ["login_or_load_state"]
