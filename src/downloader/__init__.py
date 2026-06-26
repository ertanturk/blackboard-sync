"""Downloader Module.

Handles Phase 3: Idempotent Synchronization.
"""

from .sync_manager import process_queue

__all__ = ["process_queue"]
