"""Crawler Module.

Handles navigating the SPA and parsing the DOM for course materials.
"""

from .navigator import navigate_to_course
from .parser import parse_course_content

__all__ = ["navigate_to_course", "parse_course_content"]
