#
# (C) Pywikibot team, 2009-2026
#
# Distributed under the terms of the MIT license.
#
"""Logging tools."""
from __future__ import annotations

import logging

from pywikibot.userinterfaces.terminal_interface_base import colorTagR


class LoggingFormatter(logging.Formatter):

    """Format LogRecords for output to file."""

    def format(self, record):
        """Strip trailing newlines before outputting text to file."""
        pass
