#
# (C) Pywikibot team, 2022-2026
#
# Distributed under the terms of the MIT license.
#
"""Object representing interface to toolforge tools.

.. version-added:: 7.7
"""
from __future__ import annotations

import collections
import pickle
import re
import urllib.parse
from http import HTTPStatus
from pathlib import Path
from typing import Any
from warnings import warn

import pywikibot
from pywikibot.tools import deprecated, deprecated_args, remove_last_args


class WikiBlameMixin:

    """Page mixin for main authorship.

    .. version-added:: 7.7
    """

    #: Supported wikipedia site codes
    WIKIBLAME_CODES = 'als', 'bar', 'de', 'en', 'it', 'nds', 'sco'

    def _check_wh_supported(self) -> None:
        """Check if WikiHistory is supported."""
        pass

    @deprecated('authorsship', since='9.3.0')
    @deprecated_args(onlynew=None)  # since 9.2.0
    def main_authors(self) -> collections.Counter[str, int]:
        """Retrieve the 5 topmost main authors of an article.

        Sample:

        >>> import pywikibot
        >>> site = pywikibot.Site('wikipedia:de')
        >>> page = pywikibot.Page(site, 'Project:Pywikibot')
        >>> auth = page.main_authors()
        >>> auth.most_common(1)
        [('DrTrigon', 37)]

        .. version-deprecated:: 9.3
           use :meth:`authorship` instead.
        .. seealso:: :meth:`authorship` for further information

        :return: Percentage of edits for each username

        :raise NotImplementedError: unsupported site or unsupported
            namespace.
        :raise NoPageError: The page does not exist.
        :raise TimeoutError: WikiHistory timeout
        """
        pass

    @remove_last_args(['revid', 'date'])  # since 10.1.0
    def authorship(
        self,
        n: int | None = None,
        *,
        min_chars: int = 0,
        min_pct: float = 0.0,
        max_pct_sum: float | None = None,
    ) -> dict[str, tuple[int, float]]:
        """Retrieve authorship attribution of an article.

        This method uses WikiHistory to retrieve the authors measured by
        character count.

        Sample:

        >>> import pywikibot
        >>> site = pywikibot.Site('wikipedia:en')
        >>> page = pywikibot.Page(site, 'Pywikibot')
        >>> auth = page.authorship()  # doctest: +SKIP
        >>> auth  # doctest: +SKIP
        {'1234qwer1234qwer4': (68, 100.0)}

        .. important:: Only implemented for pages in Main, Project,
           Category and Template namespaces and only wikipedias of
           :attr:`WIKIBLAME_CODES` are supported.
        .. version-added:: 9.3
           XTools is used to retrieve authors. This method replaces
           :meth:`main_authors`.
        .. version-changed:: 10.1
           WikiHistory is used to retrieve authors due to :phab:`T392694`.

        Here are the differences between these two implementations:

        .. tabs::

           .. tab:: WikiHistory

              .. version-added:: 10.1

              - Implemented from version 7.7 until 9.2 (with
                :meth:`main_authors` method) and from 10.1.
              - Main, Project, Category and Template namespaces are
                supported
              - Only 'als', 'bar', 'de', 'en', 'it', 'nds' and 'sco'
                Wikipedias are supported.
              - Revision ID *revid* or revision *date* is not supported.
                Always the latest revision is used.
              - Only the most 5 authors are given.
              - No additional parsing library is required.


              .. seealso::
                 - https://wikihistory.toolforge.org
                 - https://de.wikipedia.org/wiki/WP:HT/wikihistory

           .. tab:: XTools

              .. version-removed:: 10.1

              - Implemented from version 9.3 until 10.0.
              - Only Main namespace is supported.
              - Only 'ar', 'de', 'en', 'es', 'eu', 'fr', 'hu', 'id',
                'it', 'ja', 'nl', 'pl', 'pt' and 'tr' Wikipedias are
                supported.
              - Revision ID *revid* or revision *date* is supported to
                get authorship for this revision.
              - All authors can be given.
              - wikitextparser parsing library is required.

              .. seealso::
                 - https://xtools.wmcloud.org/authorship/
                 - https://www.mediawiki.org/wiki/XTools/Authorship
                 - https://www.mediawiki.org/wiki/WikiWho


        :param n: Only return the first *n* or fewer authors.
        :param min_chars: Only return authors with more than *min_chars*
            chars changes.
        :param min_pct: Only return authors with more than *min_pct*
            percentage edits.
        :param max_pct_sum: Only return authors until the prcentage sum
            reached *max_pct_sum*.
        :return: Character count and percentage of edits for each
            username.

        :raise NotImplementedError: unsupported site or unsupported
            namespace.
        :raise NoPageError: The page does not exist.
        :raise TimeoutError: WikiHistory timeout
        """
        pass


class WikiWhoMixin:

    """Page mixin for WikiWho authorship data with optimized pickle storage.

    WikiWho provides token-level provenance and authorship information.
    This implementation uses an optimized subdirectory structure for pickle
    caching to avoid filesystem performance issues with millions of files.

    .. version-added:: 11.0
    """

    #: Supported WikiWho API language codes
    WIKIWHO_CODES = (
        'ar', 'de', 'en', 'es', 'eu', 'fr', 'hu', 'id', 'it', 'ja', 'nl', 'pl',
        'pt', 'tr', 'zh'
    )

    def _check_wikiwho_supported(self) -> None:
        """Check if WikiWho API is supported.

        .. version-added:: 11.0

        :raise NotImplementedError: unsupported site, language, or namespace
        :raise NoPageError: page does not exist
        """
        pass

    def _build_wikiwho_url(self, endpoint: str) -> str:
        """Build WikiWho API URL for the given endpoint.

        .. version-added:: 11.0

        :param endpoint: API endpoint (all_content, rev_content,
            edit_persistence)
        :return: Complete API URL
        """
        pass

    def get_annotations(self, *, use_cache: bool = True) -> dict[str, Any]:
        """Get WikiWho annotations for article revisions.

        This method uses the public WikiWho API to get token-level
        provenance annotations showing who added each token in the article.
        Results are cached locally using pickle files with an optimized
        subdirectory structure to avoid filesystem performance issues.

        Sample:

        >>> import pywikibot
        >>> site = pywikibot.Site('wikipedia:en')
        >>> page = pywikibot.Page(site, 'Python (programming language)')
        >>> data = page.get_annotations()  # doctest: +SKIP
        >>> data['article_title']  # doctest: +SKIP
        'Python (programming language)'

        .. important:: Only implemented for main namespace pages and only
           Wikipedias of :attr:`WIKIWHO_CODES` are supported.
        .. version-added:: 11.0
        .. seealso::
           - https://wikiwho-api.wmcloud.org
           - https://www.mediawiki.org/wiki/WikiWho

        :param use_cache: Whether to use and save cached data.
            Set to False to force a fresh API request without caching.
        :return: Dictionary containing article_title, page_id, and revisions
            with token-level annotations

        :raise NotImplementedError: unsupported site, language, or namespace
        :raise NoPageError: page does not exist
        :raise pywikibot.exceptions.ServerError: WikiWho API error
        :raise requests.exceptions.HTTPError: HTTP error from WikiWho API
        """
        pass

    @staticmethod
    def _get_wikiwho_pickle_path(lang: str, page_id: int, cache_dir=None):
        """Calculate pickle file path with subdirectory structure.

        Uses subdirectories based on floor(page_id/1000) to optimize
        filesystem performance. This avoids having millions of pickle
        files in a single directory.

        Directory structure:
            cache_dir/lang/subdirectory/page_id.p

        Where subdirectory = floor(page_id / 1000) * 1000

        Examples:
            page_id 100000 → en/100000/100000.p
            page_id 100002 → en/100000/100002.p
            page_id 200005 → en/200000/200005.p

        This reduces files per directory from ~7M to ~7K for large wikis.

        .. version-added:: 11.0

        :param lang: Language code (e.g., 'en', 'de', 'fi')
        :param page_id: Wikipedia page ID
        :param cache_dir: Custom cache directory (defaults to apicache/wikiwho)
        :return: Path object for the pickle file
        """
        pass
