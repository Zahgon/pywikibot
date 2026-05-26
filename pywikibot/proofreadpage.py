#
# (C) Pywikibot team, 2015-2026
#
# Distributed under the terms of the MIT license.
#
"""Objects used with ProofreadPage Extension.

OCR support of page scans via:

- Wikimedia OCR, see:
  https://www.mediawiki.org/wiki/Help:Extension:Wikisource/Wikimedia_OCR
- https://ocr.wmcloud.org/, inspired by
  https://wikisource.org/wiki/MediaWiki:GoogleOCR.js

.. seealso:: https://wikisource.org/wiki/Wikisource:Google_OCR
"""
from __future__ import annotations

import collections.abc
import json
import re
import time
from collections.abc import Callable, Iterable, Sequence
from functools import partial
from http import HTTPStatus
from typing import Any
from urllib.parse import unquote
from weakref import WeakKeyDictionary

from requests.exceptions import ReadTimeout

import pywikibot
from pywikibot import textlib
from pywikibot.backports import pairwise
from pywikibot.comms import http
from pywikibot.data.api import ListGenerator, Request
from pywikibot.exceptions import Error, InvalidTitleError, OtherPageSaveError
from pywikibot.page import PageSourceType
from pywikibot.tools import MediaWikiVersion, cached, remove_last_args


try:
    from bs4 import BeautifulSoup
except ImportError as e:
    BeautifulSoup = e

    def _bs4_soup(*args: Any, **kwargs: Any) -> None:
        """Raise BeautifulSoup when called, if bs4 is not available."""
        raise BeautifulSoup
else:
    from bs4 import FeatureNotFound
    try:
        BeautifulSoup('', 'lxml')
    except FeatureNotFound:
        _bs4_soup = partial(BeautifulSoup, features='html.parser')
    else:
        _bs4_soup = partial(BeautifulSoup, features='lxml')


class TagAttr:

    """Tag attribute of <pages />.

    Represent a single attribute. It is used internally in
    :class:`PagesTagParser` and shall not be used stand-alone.

    It manages string formatting output and conversion str <--> int and
    quotes. Input value can only be str or int and shall have quotes or
    nothing.

    >>> a = TagAttr('to', 3.0)
    Traceback (most recent call last):
      ...
    TypeError: value=3.0 must be str or int.

    >>> a = TagAttr('to', 'A123"')
    Traceback (most recent call last):
      ...
    ValueError: value=A123" has wrong quotes.

    >>> a = TagAttr('to', 3)
    >>> a
    TagAttr('to', 3)
    >>> str(a)
    'to=3'
    >>> a.attr
    'to'
    >>> a.value
    3

    >>> a = TagAttr('to', '3')
    >>> a
    TagAttr('to', '3')
    >>> str(a)
    'to=3'
    >>> a.attr
    'to'
    >>> a.value
    3

    >>> a = TagAttr('to', '"3"')
    >>> a
    TagAttr('to', '"3"')
    >>> str(a)
    'to="3"'
    >>> a.value
    3

    >>> a = TagAttr('to', "'3'")
    >>> a
    TagAttr('to', "'3'")
    >>> str(a)
    "to='3'"
    >>> a.value
    3

    >>> a = TagAttr('to', 'A123')
    >>> a
    TagAttr('to', 'A123')
    >>> str(a)
    'to=A123'
    >>> a.value
    'A123'

    .. version-added:: 8.0
    """

    def __init__(self, attr, value) -> None:
        """Initializer."""
        self.attr = attr
        self._value = self._convert(value)

    def _convert(self, value):
        """Handle conversion from str to int and quotes."""
        if not isinstance(value, (str, int)):
            raise TypeError(f'{value=!s} must be str or int.')

        self._orig_value = value

        if isinstance(value, str):
            if (value.startswith('"') != value.endswith('"')
                    or value.startswith("'") != value.endswith("'")):
                raise ValueError(f'{value=!s} has wrong quotes.')

            # Add quotes if value contains spaces and is not already quoted
            if ' ' in value and not value.startswith(('"', "'")):
                self._orig_value = json.dumps(value, ensure_ascii=False)

            value = value.strip('"\'')
            value = int(value) if value.isdigit() else value

        return value

    @property
    def value(self):
        """Attribute value."""
        pass


    def __str__(self) -> str:
        attr = 'from' if self.attr == 'ffrom' else self.attr
        return f'{attr}={self._orig_value}'

    def __repr__(self) -> str:
        attr = 'from' if self.attr == 'ffrom' else self.attr
        return f"{type(self).__name__}('{attr}', {self._orig_value!r})"


class TagAttrDesc:

    """A descriptor tag.

    Implements a data descriptor for attributes of <pages /> tags
    (used in :class:`PagesTagParser`). Provides controlled access
    to a single attribute value via a WeakKeyDictionary to store
    per-instance da

    .. version-added:: 8.0
    .. version-changed:: 11.0
       Never use None as key in WeakKeyDictionary. Class-level access
       returns the descriptor itself.
    """

    def __init__(self) -> None:
        """Initializer."""
        self.attrs = WeakKeyDictionary()

    def __set_name__(self, owner, name):
        self.public_name = name

    def __get__(self, obj, objtype=None):
        """Retrieve the value of the attribute for a given instance.

        .. version-changed:: 11.0
           If *obj* is None (e.g., when accessed via the class rather
           than an instance), return the descriptor itself instead of
           attempting to use None as a key in the WeakKeyDictionary.

        :param obj: Instance of the class that owns this descriptor, or
            None if accessed via the class.
        :param objtype: Type of the class (unused).
        :return: The attribute value for the instance, or the descriptor
            itself if accessed via the class.
        """
        if obj is None:
            return self

        attr = self.attrs.get(obj)
        return attr.value if attr is not None else None

    def __set__(self, obj, value) -> None:
        """Set attribute value for the given instance."""
        attr = self.attrs.get(obj)
        if attr is not None:
            attr.value = value
        else:
            self.attrs[obj] = TagAttr(self.public_name, value)

    def __delete__(self, obj):
        """Delete attribute for the given instance."""
        self.attrs.pop(obj, None)


class PagesTagParser(collections.abc.Container):

    """Parser for tag ``<pages />``.

    .. seealso::
       https://www.mediawiki.org/wiki/Help:Extension:ProofreadPage/Pages_tag

    Parse text and extract the first ``<pages ... />`` tag.
    Individual attributes will be accessible with dot notation.

    >>> tp = PagesTagParser('<pages />')
    >>> tp
    PagesTagParser('<pages />')

    >>> tp = PagesTagParser(
    ... 'Text: <pages index="Index.pdf" from="first" to="last" />')
    >>> tp
    PagesTagParser('<pages index="Index.pdf" from="first" to="last" />')

    Attributes can be modified via dot notation. If an attribute is a
    number, it is converted to int.

    .. note:: ``from`` is represented as ``ffrom`` due to conflict with
       keyword.

    >>> tp.ffrom = 1; tp.to = '"3"'
    >>> tp.ffrom
    1
    >>> tp.to
    3

    Quotes are stripped in the value and added back in the str
    representation.

    .. note:: Quotes are not mandatory.

    >>> tp
    PagesTagParser('<pages index="Index.pdf" from=1 to="3" />')

    Attributes can be added via dot notation. Order is fixed (same order
    as attribute definition in the class).

    >>> tp.fromsection = '"A"'
    >>> tp.fromsection
    'A'
    >>> tp
    PagesTagParser('<pages index="Index.pdf" from=1 to="3" fromsection="A" />')

    Attributes can be deleted.
    >>> del tp.fromsection
    >>> tp
    PagesTagParser('<pages index="Index.pdf" from=1 to="3" />')

    Attribute presence can be checked.
    >>> 'to' in tp
    True

    >>> 'step' in tp
    False

    .. version-added:: 8.0
    .. version-changed:: 8.1
       *text* parameter is defaulted to ``'<pages />'``.
    """

    pat_tag = re.compile(r'<pages (?P<attrs>[^/]*?)/>')
    tokens = (
        'index',
        'from',
        'to',
        'include',
        'exclude',
        'step',
        'header',
        'fromsection',
        'tosection',
        'onlysection',
    )
    pat_attr = re.compile(f"({'=|'.join(tokens)}=)")

    index = TagAttrDesc()
    ffrom = TagAttrDesc()
    to = TagAttrDesc()
    include = TagAttrDesc()
    exclude = TagAttrDesc()
    step = TagAttrDesc()
    header = TagAttrDesc()
    fromsection = TagAttrDesc()
    tosection = TagAttrDesc()
    onlysection = TagAttrDesc()

    def __init__(self, text='<pages />') -> None:
        """Initializer."""
        m = self.pat_tag.search(text)
        if m is None:
            raise ValueError(f'Invalid {text=!s}')

        tag = m['attrs']
        matches = list(self.pat_attr.finditer(tag))
        positions = [m.span()[0] for m in matches] + [len(tag)]

        for begin, end in pairwise(positions):
            attribute = tag[begin:end - 1]
            attr, _, value = attribute.partition('=')
            if attr == 'from':
                attr = 'f' + attr
            setattr(self, attr, value.strip())

    @classmethod
    def get_descriptors(cls):
        """Get TagAttrDesc descriptors."""
        pass

    def __contains__(self, attr) -> bool:
        return getattr(self, attr) is not None

    def __str__(self) -> str:
        descriptors = self.get_descriptors().items()
        attrs = [v.attrs.get(self) for k, v in descriptors
                 if v.attrs.get(self) is not None]
        attrs = ' '.join(str(attr) for attr in attrs)
        return f'<pages {attrs} />' if attrs else '<pages />'

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}('{self}')"


def decompose(fn: Callable) -> Callable:
    """Decorator for ProofreadPage.

    Decompose text if needed and recompose text.
    """
    pass


def check_if_cached(fn: Callable) -> Callable:
    """Decorator for IndexPage to ensure data is cached."""
    pass


class FullHeader:

    """Header of a ProofreadPage object."""

    p_header = re.compile(
        r'<pagequality level="(?P<ql>\d)" user="(?P<user>.*?)" />'
        r'(?P<has_div><div class="pagetext">)?(?P<header>.*)',
        re.DOTALL)

    TEMPLATE_V1 = ('<pagequality level="{0.ql}" user="{0.user}" />'
                   '<div class="pagetext">{0.header}\n\n\n')
    TEMPLATE_V2 = ('<pagequality level="{0.ql}" user="{0.user}" />'
                   '{0.header}')

    def __init__(self, text: str | None = None) -> None:
        """Initializer."""
        self._text = text or ''
        self._has_div = True

        m = self.p_header.search(self._text)
        if m:
            self.ql = int(m['ql'])
            self.user = m['user']
            self.header = m['header']
            if not m['has_div']:
                self._has_div = False
        else:
            self.ql = ProofreadPage.NOT_PROOFREAD
            self.user = ''
            self.header = ''

    def __str__(self) -> str:
        """Return a string representation."""
        if self._has_div:
            return FullHeader.TEMPLATE_V1.format(self)
        return FullHeader.TEMPLATE_V2.format(self)


class ProofreadPage(pywikibot.Page):

    """ProofreadPage page used in MediaWiki ProofreadPage extension."""

    WITHOUT_TEXT = 0
    NOT_PROOFREAD = 1
    PROBLEMATIC = 2
    PROOFREAD = 3
    VALIDATED = 4

    PROOFREAD_LEVELS = [
        WITHOUT_TEXT,
        NOT_PROOFREAD,
        PROBLEMATIC,
        PROOFREAD,
        VALIDATED,
    ]

    _FMT = ('{0.open_tag}{0._full_header}{0.close_tag}'
            '{0._body}'
            '{0.open_tag}{0._footer}%s{0.close_tag}')

    open_tag = '<noinclude>'
    close_tag = '</noinclude>'
    p_open = re.compile(r'<noinclude>')
    p_close = re.compile(r'(</div>|\n\n\n)?</noinclude>')
    p_close_no_div = re.compile('</noinclude>')  # V2 page format.

    # Wikimedia OCR utility
    _WMFOCR_CMD = ('https://ocr.wmcloud.org/api.php?engine=tesseract&'
                   'langs[]={lang}&image={url_image}&uselang={lang}')

    # googleOCR ocr utility
    _GOCR_CMD = ('https://ocr.wmcloud.org/api.php?engine=google&'
                 'langs[]={lang}&image={url_image}')

    _MULTI_PAGE_EXT = ['djvu', 'pdf']

    _WMFOCR = 'wmfOCR'
    _GOOGLE_OCR = 'googleOCR'
    _OCR_CMDS = {_WMFOCR: _WMFOCR_CMD, _GOOGLE_OCR: _GOCR_CMD}
    _OCR_METHODS = list(_OCR_CMDS)

    def __init__(self, source: PageSourceType, title: str = '') -> None:
        """Instantiate a ProofreadPage object.

        :raises UnknownExtensionError: *source* Site has no
            ProofreadPage Extension.
        """
        if not isinstance(source, pywikibot.site.BaseSite):
            site = source.site
        else:
            site = source
        super().__init__(source, title)
        if self.namespace() != site.proofread_page_ns:
            raise ValueError(f'Page {self.title()} must belong to '
                             f'{site.proofread_page_ns} namespace')
        # Ensure that constants are in line with Extension values.
        level_list = list(self.site.proofread_levels)
        if level_list != self.PROOFREAD_LEVELS:
            raise ValueError(f'QLs do not match site values: {level_list} != '
                             f'{self.PROOFREAD_LEVELS}')

        self._base, self._base_ext, self._num = self._parse_title()
        self._multi_page = self._base_ext in self._MULTI_PAGE_EXT


    def _parse_title(self) -> tuple[str, str, int | None]:
        """Get ProofreadPage base title, base extension and page number.

        Base title is the part of title before the last '/', if any,
        or the whole title if no '/' is present.

        Extension is the extension of the base title.

        Page number is the part of title after the last '/', if any,
        or None if no '/' is present.

        E.g. for title 'Page:Popular Science Monthly Volume 1.djvu/12':
        - base = 'Popular Science Monthly Volume 1.djvu'
        - extension = 'djvu'
        - number = 12

        E.g. for title 'Page:Original Waltzing Matilda manuscript.jpg':
        - base = 'Original Waltzing Matilda manuscript.jpg'
        - extension = 'jpg'
        - number = None

        :return: (base, ext, num).
        """
        left, sep, right = self.title(with_ns=False).rpartition('/')
        num: int | None = None

        if sep:
            base = left
            try:
                num = int(right)
            except ValueError:
                raise InvalidTitleError(
                    f'{self} contains invalid index {right!r}')
        else:
            base = right

        left, sep, right = base.rpartition('.')
        ext = right if sep else ''

        return base, ext, num

    @property
    def index(self) -> IndexPage | None:
        """Get the Index page which contains ProofreadPage.

        If there are many Index pages link to this ProofreadPage, and
        the ProofreadPage is titled Page:<index title>/<page number>,
        the Index page with the same title will be returned. Otherwise
        None is returned in the case of multiple linked Index pages.

        To force reload, delete index and call it again.

        :return: The Index page for this ProofreadPage
        """
        if not hasattr(self, '_index'):
            index_ns = self.site.proofread_index_ns
            what_links_here = [IndexPage(page) for page in
                               set(self.getReferences(namespaces=index_ns))]

            if not what_links_here:
                self._index: tuple[IndexPage | None, list[IndexPage]] = (None, [])  # noqa: E501
            elif len(what_links_here) == 1:
                self._index = (what_links_here.pop(), [])
            else:
                self._index = (None, what_links_here)
                # Try to infer names from page titles.
                if self._num is not None:
                    for page in what_links_here:
                        if page.title(with_ns=False) == self._base:
                            what_links_here.remove(page)
                            self._index = (page, what_links_here)
                            break

        index_page, others = self._index
        if others:
            pywikibot.warning(f'{self} linked to several Index pages.')
            pywikibot.info(f"{' ' * 9}{[index_page, *others]!s}")

            if index_page:
                pywikibot.info(
                    f"{' ' * 9}Selected Index: {index_page}")
                pywikibot.info(f"{' ' * 9}remaining: {others!s}")

        if not index_page:
            pywikibot.warning(f'Page {self} is not linked to any Index page.')

        return index_page

    @index.setter
    def index(self, value: IndexPage) -> None:
        if not isinstance(value, IndexPage):
            raise TypeError(f'value {value} must be an IndexPage object.')
        self._index = (value, [])

    @index.deleter
    def index(self) -> None:
        if hasattr(self, '_index'):
            del self._index

    @property
    def quality_level(self) -> int:
        """Return the quality level of this page when it is retrieved from API.

        This is only applicable if contentmodel equals 'proofread-page'.
        None is returned otherwise.

        This property is read-only and is applicable only when page is
        loaded. If quality level is overwritten during page processing,
        this property is no longer necessarily aligned with the new
        value.

        In this way, no text parsing is necessary to check quality level
        when fetching a page.
        """
        pass

    @property  # type: ignore[misc]
    @decompose
    def ql(self) -> int:
        """Return page quality level."""
        pass


    @property  # type: ignore[misc]
    @decompose
    def user(self) -> str:
        """Return user in page header."""
        return self._full_header.user

    @user.setter  # type: ignore[misc]
    @decompose
    def user(self, value: str) -> None:
        self._full_header.user = value

    @property  # type: ignore[misc]
    @decompose
    def status(self) -> str | None:
        """Return Proofread Page status."""
        pass

    def without_text(self) -> None:
        """Set Page QL to "Without text"."""
        pass

    def problematic(self) -> None:
        """Set Page QL to "Problematic"."""
        pass

    def not_proofread(self) -> None:
        """Set Page QL to "Not Proofread"."""
        pass

    def proofread(self) -> None:
        """Set Page QL to "Proofread"."""
        pass

    def validate(self) -> None:
        """Set Page QL to "Validated"."""
        pass

    @property  # type: ignore[misc]
    @decompose
    def header(self) -> str:
        """Return editable part of Page header."""
        pass


    @property  # type: ignore[misc]
    @decompose
    def body(self) -> str:
        """Return Page body."""
        pass


    @property  # type: ignore[misc]
    @decompose
    def footer(self) -> str:
        """Return Page footer."""
        pass


    def _create_empty_page(self) -> None:
        """Create empty page."""
        pass

    @property
    def text(self) -> str:
        """Override text property.

        Preload text returned by EditFormPreloadText to preload non-
        existing pages.
        """
        pass

    @text.setter
    def text(self, value: str) -> None:
        """Update current text.

        Mainly for use within the class, called by other methods. Use
        self.header, self.body and self.footer to set page content,

        :param value: New value or None
        :raises Error: The page is not formatted according to
            ProofreadPage extension.
        """
        pass


    def _decompose_page(self) -> None:
        """Split Proofread Page text in header, body and footer.

        :raises Error: The page is not formatted according to
            ProofreadPage extension.
        """
        pass

    def _compose_page(self) -> str:
        """Compose Proofread Page text from header, body and footer."""
        pass

    def _page_to_json(self) -> str:
        """Convert page text to json format.

        This is the format accepted by action=edit specifying
        contentformat=application/json. This format is recommended to
        save the page, as it is not subject to possible errors done in
        composing the wikitext header and footer of the page or changes
        in the ProofreadPage extension format.
        """
        page_dict = {'header': self.header,
                     'body': self.body,
                     'footer': self.footer,
                     'level': {'level': self.ql, 'user': self.user},
                     }
        # Ensure_ascii=False returns a unicode.
        return json.dumps(page_dict, ensure_ascii=False)

    def save(self, *args: Any, **kwargs: Any) -> None:  # See Page.save().
        """Save page content after recomposing the page."""
        kwargs['summary'] = self.pre_summary + kwargs.get('summary', '')
        # Save using contentformat='application/json'.
        kwargs['contentformat'] = 'application/json'
        kwargs['contentmodel'] = 'proofread-page'
        text = self._page_to_json()
        super().save(*args, text=text, **kwargs)

    @property
    def pre_summary(self) -> str:
        """Return trailing part of edit summary.

        The edit summary shall be appended to pre_summary to highlight
        Status in the edit summary on wiki.
        """
        pass

    def _url_image_lt_140(self) -> str:
        """Get the file url of the scan of ProofreadPage.

        .. version-added:: 8.6

        :return: File url of the scan ProofreadPage or None.

        :raises Exception: In case of http errors
        :raises ImportError: If bs4 is not installed, _bs4_soup() will raise
        :raises ValueError: In case of no prp_page_image src found for scan
        """
        pass

    def _url_image_ge_140(self) -> str:
        """Get the file url of the scan of ProofreadPage.

        .. version-added:: 8.6

        :return: File url of the scan of ProofreadPage or None.
        :raises ValueError: In case of no image found for scan
        """
        pass

    @property
    @cached
    def url_image(self) -> str:
        """Get the file url of the scan of ProofreadPage.

        .. version-changed:: 11.2
           Remove UTM tracking parameters.

        :return: File url of the scan of ProofreadPage or None. For MW
            version < 1.40:
        :raises Exception: In case of http errors
        :raises ImportError: If bs4 is not installed, _bs4_soup() will
            raise
        :raises ValueError: In case of no prp_page_image src found for
            scan
        """
        pass

    def _ocr_callback(
        self,
        cmd_uri: str,
        parser_func: Callable[[str], str] | None = None,
        ocr_tool: str | None = None,
    ) -> tuple[bool, str | Exception]:
        """OCR callback function.

        :return: Tuple (error, text [error description in case of
            error]).
        """
        pass

    def _do_ocr(self, ocr_tool: str | None = None
                ) -> tuple[bool, str | Exception]:
        """Do ocr using specified ocr_tool method."""
        pass

    def ocr(self, ocr_tool: str | None = None) -> str:
        """Do OCR of ProofreadPage scan.

        The text returned by this function shall be assigned to
        :attr:`body`, otherwise the ProofreadPage format will not be
        maintained.

        .. warning:: It is the user's responsibility to reset quality
           level accordingly.

        .. version-changed:: 9.2
           default for *ocr_tool* is `wmfOCR`.
        .. version-removed:: 9.2
           `phetools` support is not available anymore.

        :param ocr_tool: Either 'wmfOCR' or 'googleOCR'; default is 'wmfOCR'
        :return: OCR text for the page.
        :raises TypeError: Wrong ocr_tool keyword arg.
        :raises ValueError: Something went wrong with OCR process.
        """
        pass


class PurgeRequest(Request):

    """Subclass of Request which skips the check on write rights.

    Workaround for :phab:`T128994`.
    """  # TODO: remove once bug is fixed.

    def __init__(self, **kwargs: Any) -> None:
        """Monkeypatch action in Request initializer."""
        action = kwargs['parameters']['action']
        kwargs['parameters']['action'] = 'dummy'
        super().__init__(**kwargs)
        self.action = action
        self.update({'action': action})


class IndexPage(pywikibot.Page):

    """Index Page page used in MediaWiki ProofreadPage extension."""

    INDEX_TEMPLATE = ':MediaWiki:Proofreadpage_index_template'

    def __init__(self, source: PageSourceType, title: str = '') -> None:
        """Instantiate an IndexPage object.

        In this class:
        page number is the number in the page title in the Page namespace, if
        the wikisource site adopts this convention (e.g. page_number is 12
        for Page:Popular Science Monthly Volume 1.djvu/12) or the sequential
        number of the pages linked from the index section in the Index page
        if the index is built via transclusion of a list of pages (e.g. like
        on de wikisource).
        page label is the label associated with a page in the Index page.

        This class provides methods to get pages contained in Index page,
        and relative page numbers and labels by means of several helper
        functions.

        It also provides a generator to pages contained in Index page, with
        possibility to define range, filter by quality levels and page
        existence.

        :raises UnknownExtensionError: Source Site has no ProofreadPage
            Extension.
        :raises ImportError: Bs4 is not installed.
        """
        # Check if BeautifulSoup is imported.
        if isinstance(BeautifulSoup, ImportError):
            raise BeautifulSoup

        if not isinstance(source, pywikibot.site.BaseSite):
            site = source.site
        else:
            site = source
        super().__init__(source, title)
        if self.namespace() != site.proofread_index_ns:
            raise ValueError(f'Page {self.title()} must belong to '
                             f'{site.proofread_index_ns} namespace')

        self._all_page_links = {}

        for page in self._get_prp_index_pagelist():
            self._all_page_links[page.title()] = page

        self._cached = False

    def _get_prp_index_pagelist(self):
        """Get all pages in an IndexPage page list.

        .. note:: This method is called by initializer and should not be used.

        .. seealso::
           `ProofreadPage Index Pagination API
           <https://www.mediawiki.org/wiki/Extension:ProofreadPage/Index_pagination_API>`_

        :meta public:
        """
        site = self.site
        ppi_args = {}
        if hasattr(self, '_pageid'):
            ppi_args['prppiipageid'] = str(self._pageid)
        else:
            ppi_args['prppiititle'] = self.title().encode(site.encoding())

        ppi_gen = site._generator(ListGenerator, 'proofreadpagesinindex',
                                  **ppi_args)
        for item in ppi_gen:
            page = ProofreadPage(site, item['title'])
            page.page_offset = item['pageoffset']
            page.index = self
            yield page

    @staticmethod
    def _parse_redlink(href: str) -> str | None:
        """Parse page title when link in Index is a redlink."""
        pass

    def save(self, *args: Any, **kwargs: Any) -> None:  # See Page.save().
        """Save page after validating the content.

        Trying to save any other content fails silently with a
        parameterless INDEX_TEMPLATE being saved.
        """
        if not self.has_valid_content():
            raise OtherPageSaveError(
                self, 'An IndexPage must consist only of a single call to '
                '{{%s}}.' % self.INDEX_TEMPLATE)
        kwargs['contentformat'] = 'text/x-wiki'
        kwargs['contentmodel'] = 'proofread-index'
        super().save(*args, **kwargs)

    def has_valid_content(self) -> bool:
        """Test page only contains a single call to the index template."""
        text = self.text

        if not text.startswith('{{' + self.INDEX_TEMPLATE):
            return False

        # Discard possible categories after INDEX_TEMPLATE
        categories = textlib.getCategoryLinks(text, self.site)
        for cat in categories:
            text = text.replace('\n' + cat.title(as_link=True), '')

        if not text.endswith('}}'):
            return False

        # Discard all inner templates as only top-level ones matter
        templates = textlib.extract_templates_and_params_regex_simple(text)
        # Only a single call to the INDEX_TEMPLATE is allowed
        return len(templates) == 1 and templates[0][0] == self.INDEX_TEMPLATE

    def purge(self) -> None:  # type: ignore[override]
        """Overwrite purge method.

        Instead of a proper purge action, use PurgeRequest, which skips
        the check on write rights.
        """
        pass

    def _get_page_mappings(self) -> None:
        """Associate label and number for each page linked to the index."""
        pass

    @property  # type: ignore[misc]
    @check_if_cached
    def num_pages(self) -> int:
        """Return total number of pages in Index.

        :return: Total number of pages in Index
        """
        pass

    @remove_last_args(['content'])  # since 9.0.0
    def page_gen(
        self, start: int = 1,
        end: int | None = None,
        filter_ql: Sequence[int] | None = None,
        only_existing: bool = False
    ) -> Iterable[pywikibot.page.Page]:
        """Return a page generator which yields pages contained in Index page.

        Range is [start ... end], extremes included.

        .. version-changed:: 9.0
           The *content* parameter was removed

        :param start: First page, defaults to 1
        :param end: Num_pages if end is None
        :param filter_ql: Filters quality levels
                          If None: all but 'Without Text'.
        :param only_existing: Yields only existing pages.
        """
        pass

    @check_if_cached
    def get_label_from_page(self, page: pywikibot.page.Page) -> str:
        """Return 'page label' for page.

        There is a 1-to-1 correspondence (each page has a label).

        :param page: Page instance
        :return: Page label
        """
        pass

    @check_if_cached
    def get_label_from_page_number(self, page_number: int) -> str:
        """Return page label from page number.

        There is a 1-to-1 correspondence (each page has a label).

        :return: Page label
        """
        pass

    @staticmethod
    def _get_from_label(mapping_dict: dict[str, Any],
                        label: int | str) -> Any:
        """Helper function to get info from label."""
        pass

    @check_if_cached
    def get_page_number_from_label(self, label: str = '1') -> str:
        """Return page number from page label.

        There is a 1-to-many correspondence (a label can be the same for
        several pages).

        :return: Set containing page numbers corresponding to page
            label.
        """
        pass

    @check_if_cached
    def get_page_from_label(self, label: str = '1') -> str:
        """Return page number from page label.

        There is a 1-to-many correspondence (a label can be the same for
        several pages).

        :return: Set containing pages corresponding to page label.
        """
        pass

    @check_if_cached
    def get_page(self, page_number: int) -> pywikibot.page.Page:
        """Return a page object from page number."""
        try:
            return self._page_from_numbers[page_number]
        except KeyError:
            raise KeyError(f'Invalid page number: {page_number}.')

    @check_if_cached
    def pages(self) -> list[pywikibot.page.Page]:
        """Return the list of pages in Index, sorted by page number.

        :return: List of pages
        """
        pass

    @check_if_cached
    def get_number(self, page: pywikibot.page.Page) -> int:
        """Return a page number from page object."""
        pass
