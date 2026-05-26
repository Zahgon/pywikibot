#
# (C) Pywikibot team, 2025-2026
#
# Distributed under the terms of the MIT license.
#
"""Citoid Query interface.

.. version-added:: 10.6
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any

import pywikibot
from pywikibot.comms import http
from pywikibot.exceptions import ApiNotAvailableError, Error
from pywikibot.site import BaseSite


VALID_FORMAT = [
    'mediawiki', 'wikibase', 'zotero', 'bibtex', 'mediawiki-basefields'
]


@dataclass(eq=False)
class CitoidClient:

    """Citoid client class.

    This class allows to call the Citoid API used in production.
    """

    site: BaseSite

    def get_citation(
        self,
        response_format: str,
        ref_url: str
    ) -> dict[str, Any]:
        """Get a citation from the citoid service.

        :param response_format: Return format, e.g. 'bibtex', 'wikibase', etc.
        :param ref_url: The URL to get the citation for.
        :return: A dictionary with the citation data.
        """
        pass
