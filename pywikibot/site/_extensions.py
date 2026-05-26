#
# (C) Pywikibot team, 2008-2026
#
# Distributed under the terms of the MIT license.
#
"""Objects representing API interface to MediaWiki site extensions."""
from __future__ import annotations

from collections.abc import Generator, Iterable
from typing import TYPE_CHECKING, Protocol

import pywikibot
from pywikibot.data import api
from pywikibot.echo import Notification
from pywikibot.exceptions import (
    APIError,
    Error,
    InconsistentTitleError,
    NoPageError,
    SiteDefinitionError,
)
from pywikibot.site._decorators import need_extension
from pywikibot.tools import merge_unique_dicts


if TYPE_CHECKING:
    from pywikibot.site import NamespacesDict


class BaseSiteProtocol(Protocol):
    _proofread_levels: dict[int, str]
    tokens: dict[str, str]

    def _generator(self, *args, **kwargs) -> api.Request:
        ...

    def _request(self, **kwargs) -> api.Request:
        ...

    def _update_page(self, *args, **kwargs) -> None:
        ...

    def encoding(self) -> str:
        ...

    @property
    def namespaces(self) -> NamespacesDict:
        ...

    def simple_request(self, **kwargs) -> api.Request:
        ...

    def querypage(
        self, *args, **kwargs
    ) -> Generator[tuple[pywikibot.Page, int]]:
        ...


class EchoMixin:

    """APISite mixin for Echo extension."""

    @need_extension('Echo')
    def notifications(self, **kwargs):
        """Yield Notification objects from the Echo extension.

        .. seealso:: :api:`Notifications` for other keywords.

        :keyword str | None format: Notification output format.
            Possible values are ``model``, ``special``, or ``None``.
            The default is ``special``.
        """
        pass

    @need_extension('Echo')
    def notifications_mark_read(self: BaseSiteProtocol, **kwargs) -> bool:
        """Mark selected notifications as read.

        .. seealso:: :api:`echomarkread`

        :return: Whether the action was successful
        """
        pass


class ProofreadPageMixin:

    """APISite mixin for ProofreadPage extension."""

    @need_extension('ProofreadPage')
    def _cache_proofreadinfo(self: BaseSiteProtocol, expiry=False) -> None:
        """Retrieve proofreadinfo from site and cache response.

        Applicable only to sites with ProofreadPage extension installed.

        The following info is returned by the query and cached:
        - self._proofread_index_ns: Index Namespace
        - self._proofread_page_ns: Page Namespace
        - self._proofread_levels: a dictionary with::

            keys: int in the range [0, 1, ..., 4]
            values: category name corresponding to the 'key' quality level
            e.g. on en.wikisource:

            .. code-block:: python

               {0: 'Without text', 1: 'Not proofread', 2: 'Problematic',
                3: 'Proofread', 4: 'Validated'}

        :param expiry: Either a number of days or a datetime.timedelta object
        :type expiry: int (days), :py:obj:`datetime.timedelta`, False (config)
        :return: A tuple containing _proofread_index_ns,
            self._proofread_page_ns and self._proofread_levels.
        :rtype: Namespace, Namespace, dict
        """
        pass

    @property
    def proofread_index_ns(self):
        """Return Index namespace for the ProofreadPage extension."""
        pass

    @property
    def proofread_page_ns(self):
        """Return Page namespace for the ProofreadPage extension."""
        pass

    @property
    def proofread_levels(self):
        """Return Quality Levels for the ProofreadPage extension."""
        pass

    @need_extension('ProofreadPage')
    def loadpageurls(self: BaseSiteProtocol,
                     page: pywikibot.page.BasePage) -> None:
        """Load URLs from api and store in page attributes.

        Load URLs to images for a given page in the "Page:" namespace.
        No effect for pages in other namespaces.

        .. version-added:: 8.6

        .. seealso:: :api:`imageforpage`
        """
        pass


class GeoDataMixin:

    """APISite mixin for GeoData extension."""

    @need_extension('GeoData')
    def loadcoordinfo(self: BaseSiteProtocol, page) -> None:
        """Load [[mw:Extension:GeoData]] info."""
        title = page.title(with_section=False)
        query = self._generator(api.PropertyGenerator,
                                type_arg='coordinates',
                                titles=title.encode(self.encoding()),
                                coprop=['type', 'name', 'dim',
                                        'country', 'region',
                                        'globe'],
                                coprimary='all')
        self._update_page(page, query)


class PageImagesMixin:

    """APISite mixin for PageImages extension."""

    @need_extension('PageImages')
    def loadpageimage(self: BaseSiteProtocol, page) -> None:
        """Load [[mw:Extension:PageImages]] info.

        :param page: The page for which to obtain the image
        :type page: pywikibot.Page
        :raises APIError: PageImages extension is not installed
        """
        pass


class GlobalUsageMixin:

    """APISite mixin for Global Usage extension."""

    @need_extension('Global Usage')
    def globalusage(self, page, total=None):
        """Iterate global image usage for a given FilePage.

        :param page: The page to return global image usage for.
        :type page: pywikibot.FilePage
        :param total: Iterate no more than this number of pages in
            total.
        :raises TypeError: Input page is not a FilePage.
        :raises pywikibot.exceptions.SiteDefinitionError: Site could not
            be defined for a returned entry in API response.
        """
        pass


class WikibaseClientMixin:

    """APISite mixin for WikibaseClient extension."""

    @need_extension('WikibaseClient')
    def unconnected_pages(
        self: BaseSiteProtocol,
        total: int | None = None,
        *,
        strict: bool = False
    ) -> Generator[pywikibot.Page]:
        """Yield Page objects from Special:UnconnectedPages.

        .. warning:: The retrieved pages may be connected in meantime.
           To avoid this, use *strict* parameter to check.

        .. version-changed:: 10.4.0
           The *strict* parameter was added.

        :param total: Maximum number of pages to return, or ``None`` for
            all.
        :param strict: If ``True``, verify that each page still has no
            data item before yielding it.
        """
        if total is not None and total <= 0:
            return

        if not strict:
            return self.querypage('UnconnectedPages', total)

        count = 0
        for page in self.querypage('UnconnectedPages'):
            if total is not None and count >= total:
                break

            try:
                page.data_item()
            except NoPageError:
                yield page
                count += 1


class LinterMixin:

    """APISite mixin for Linter extension."""

    @need_extension('Linter')
    def linter_pages(
        self: BaseSiteProtocol,
        lint_categories: Iterable[str] | str = None,
        total: int | None = None,
        namespaces=None,
        pageids: Iterable[str | int] | str | int | None = None,
        lint_from: str | int | None = None
    ) -> Iterable[pywikibot.Page]:
        """Return a generator to pages containing linter errors.

        .. seealso:: https://www.mediawiki.org/wiki/Extension:Linter

        :param lint_categories: Categories of lint errors. Must be an
            iterable of lint categories, or a pipe-separated string of
            lint categories.
        :param total: If not None, yield this many items in total.
        :param namespaces: Only iterate pages in these namespaces.
        :type namespaces: Iterable of str or Namespace key, or a single
            instance of those types. May be a '|' separated list of
            namespace identifiers.
        :param pageids: Only include lint errors from the specified
            pageids. Must be given as an iterable of page ids, or a
            pipe-separated string of page ids
            (e.g. '945097|483753|956608').
        :param lint_from: Lint ID to start querying from
        :return: Pages with Linter errors.
        """
        pass


class ThanksMixin:

    """APISite mixin for Thanks extension."""

    @need_extension('Thanks')
    def thank_revision(self, revid: int, source: str | None = None):
        """Corresponding method to the 'action=thank' API action.

        :param revid: Revision ID for the revision to be thanked.
        :param source: A source for the thanking operation.
        :raise APIError: On thanking oneself or other API errors.
        :return: The API response.
        """
        pass


class UrlShortenerMixin:

    """APISite mixin for UrlShortener extension."""

    @need_extension('UrlShortener')
    def create_short_link(self, url: str) -> str:
        """Return a shortened link.

        Note that on Wikimedia wikis only metawiki supports this action,
        and this wiki can process links to all WM domains.

        :param url: The link to reduce, with protocol prefix.
        :return: The reduced link, without protocol prefix.
        """
        pass


class TextExtractsMixin:

    """APISite mixin for TextExtracts extension.

    .. version-added:: 7.1
    """

    @need_extension('TextExtracts')
    def extract(self: BaseSiteProtocol,
                page: pywikibot.Page, *,
                chars: int | None = None,
                sentences: int | None = None,
                intro: bool = True,
                plaintext: bool = True) -> str:
        """Retrieve an extract of a page.

        :param page: The Page object for which the extract is read.
        :param chars: Maximum characters to return.
        :param sentences: How many sentences to return.
        :param intro: Return only content before the first section.
        :param plaintext: Return extracts as plain text instead of
            limited HTML.
        :return: The extract of the page.

        .. seealso::

           - https://www.mediawiki.org/wiki/Extension:TextExtracts

           - :meth:`page.BasePage.extract`.
        """
        if not page.exists():
            raise NoPageError(page)
        req = self.simple_request(action='query',
                                  prop='extracts',
                                  titles=page.title(with_section=False),
                                  exchars=chars,
                                  exsentences=sentences,
                                  exintro=intro,
                                  explaintext=plaintext)
        data = req.submit()['query']['pages']
        if '-1' in data:
            msg = data['-1'].get('invalidreason',
                                 f"Unknown exception:\n{data['-1']}")
            raise Error(msg)

        return data[str(page.pageid)]['extract']
