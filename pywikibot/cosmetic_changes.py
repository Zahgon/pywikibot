#
# (C) Pywikibot team, 2006-2026
#
# Distributed under the terms of the MIT license.
#
"""This module can do slight modifications to tidy a wiki page's source code.

The changes are not supposed to change the look of the rendered wiki page.

If you wish to run this as a stand-alone script, use::

    scripts/cosmetic_changes.py

For regular use, it is recommended to put this line into your user config::

    cosmetic_changes = True

You may enable cosmetic changes for additional site codes by adding the
dictionary ``cosmetic_changes_enable`` to your user-config.py. It should
contain a tuple of codes for each site where you wish to enable in addition to
your own site code if ``cosmetic_changes_mylang_only`` is True (see below).
Please set your dictionary by adding such lines to your user config::

    cosmetic_changes_enable['wikipedia'] = ('de', 'en', 'fr')

There is another config variable: You can set::

    cosmetic_changes_mylang_only = False

if you're running a bot on multiple sites and want to do cosmetic changes on
all of them, but be careful if you do.

You may disable cosmetic changes by adding all unwanted languages to
the dictionary ``cosmetic_changes_disable`` in your user config file
(`user-config.py`). It should contain a tuple of languages for each site
where you wish to disable cosmetic changes. You may use it with
`cosmetic_changes_mylang_only` is False, but you can also disable your
own language. This also overrides the settings in the dictionary
`cosmetic_changes_enable`. Please set this dictionary by adding such
lines to your user config file::

    cosmetic_changes_disable['wikipedia'] = ('de', 'en', 'fr')

You may disable cosmetic changes for a given script by appending all
unwanted scripts to the list ``cosmetic_changes_deny_script`` in your
user-config.py. By default it contains cosmetic_changes.py itself and touch.py.
This overrides all other enabling settings for cosmetic changes. Please modify
the given list by adding such lines to your user-config.py::

    cosmetic_changes_deny_script.append('your_script_name_1')

or by adding a list to the given one::

    cosmetic_changes_deny_script += ['your_script_name_1',
                                     'your_script_name_2']
"""
from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import suppress
from enum import IntEnum
from typing import Any, cast
from urllib.parse import urlparse, urlunparse

import pywikibot
from pywikibot import exceptions, i18n, textlib
from pywikibot.site import Namespace
from pywikibot.tools import first_lower, first_upper
from pywikibot.tools.chars import url2string
from pywikibot.userinterfaces.transliteration import NON_ASCII_DIGITS


try:
    import stdnum.isbn as stdnum_isbn
except ImportError:
    stdnum_isbn = None


# Subpage templates. Must be in lower case,
# whereas subpage itself must be case sensitive
# This is also used by interwiki.py
# TODO: Maybe move it to family file and implement global instances
moved_links = {
    'ar': (['documentation', 'template documentation', 'شرح', 'توثيق'],
           '/doc'),
    'bn': ('documentation', '/doc'),
    'ca': ('ús de la plantilla', '/ús'),
    'cs': ('dokumentace', '/doc'),
    'da': ('dokumentation', '/doc'),
    'de': ('dokumentation', '/Meta'),
    'dsb': (['dokumentacija', 'doc'], '/Dokumentacija'),
    'en': (['documentation', 'template documentation', 'template doc',
            'doc', 'documentation, template'], '/doc'),
    'es': (['documentación', 'documentación de plantilla'], '/doc'),
    'eu': ('txantiloi dokumentazioa', '/dok'),
    'fa': (['documentation', 'template documentation', 'template doc',
            'doc', 'توضیحات', 'زیرصفحه توضیحات'], '/doc'),
    # fi: no idea how to handle this type of subpage at :Metasivu:
    'fi': ('mallineohje', None),
    'fr': (['/documentation', 'documentation', 'doc_modèle',
            'documentation modèle', 'documentation modèle compliqué',
            'documentation modèle en sous-page',
            'documentation modèle compliqué en sous-page',
            'documentation modèle utilisant les parserfunctions en sous-page',
            ],
           '/Documentation'),
    'hsb': (['dokumentacija', 'doc'], '/Dokumentacija'),
    'hu': ('sablondokumentáció', '/doc'),
    'id': ('template doc', '/doc'),
    'ilo': ('documentation', '/doc'),
    'ja': ('documentation', '/doc'),
    'ka': ('თარგის ინფო', '/ინფო'),
    'ko': ('documentation', '/설명문서'),
    'ms': ('documentation', '/doc'),
    'no': ('dokumentasjon', '/dok'),
    'nn': ('dokumentasjon', '/dok'),
    'pl': ('dokumentacja', '/opis'),
    'pt': (['documentação', '/doc'], '/doc'),
    'ro': ('documentaţie', '/doc'),
    'ru': ('doc', '/doc'),
    'simple': (['documentation',
                'template documentation',
                'template doc',
                'doc',
                'documentation, template'], '/doc'),
    'sk': ('dokumentácia', '/Dokumentácia'),
    'sv': ('dokumentation', '/dok'),
    'uk': (['документація', 'doc', 'documentation'], '/Документація'),
    'ur': (['دستاویز', 'توثيق', 'شرح', 'توضیحات',
            'documentation', 'template doc', 'doc',
            'documentation, template'], '/doc'),
    'vi': ('documentation', '/doc'),
    'zh': (['documentation', 'doc'], '/doc'),
}

# Template which should be replaced or removed.
# Use a list with two entries. The first entry will be replaced by the second.
# Examples:
# For removing {{Foo}}, the list must be:
#           ('Foo', None),
#
# The following also works:
#           ('Foo', ''),
#
# For replacing {{Foo}} with {{Bar}} the list must be:
#           ('Foo', 'Bar'),
#
# This also removes all template parameters of {{Foo}}
# For replacing {{Foo}} with {{Bar}} but keep the template
# parameters in its original order, please use:
#           ('Foo', 'Bar\\g<parameters>'),

deprecatedTemplates = {
    'wikipedia': {
        'de': [
            ('Belege', 'Belege fehlen\\g<parameters>'),
            ('Quelle', 'Belege fehlen\\g<parameters>'),
            ('Quellen', 'Belege fehlen\\g<parameters>'),
            ('Quellen fehlen', 'Belege fehlen\\g<parameters>'),
        ],
        'ur': [
            ('Infobox former country',
             'خانہ معلومات سابقہ ملک\\g<parameters>'),
            ('Infobox Former Country',
             'خانہ معلومات سابقہ ملک\\g<parameters>'),
        ],
    }
}

main_sortkey = {
    '_default': ' ',
    'ar': '*',
}
"""Sort key to specify the main article within a category.

The sort key must be one of ``' '``, ``'!'``, ``'*'``, ``'#'`` and is
used like a pipe link but sorts the page in front of the alphabetical
order. This dict is used in
:meth:`CosmeticChangesToolkit.standardizePageFooter`.

.. version-added:: 9.3
"""


class CANCEL(IntEnum):

    """Cancel level to ignore exceptions.

    If an error occurred and either skips the page or the method
    or a single match. ALL raises the exception.

    .. version-added:: 6.3
    """

    ALL = 0
    PAGE = 1
    METHOD = 2
    MATCH = 3


def _format_isbn_match(match: re.Match[str], *, strict: bool = True) -> str:
    """Helper function to validate and format a single matched ISBN."""
    pass


def _reformat_ISBNs(text: str, *, strict: bool = True) -> str:
    """Helper function to normalise ISBNs in text.

    :raises Exception: Invalid ISBN encountered when strict enabled
    """
    pass


class CosmeticChangesToolkit:

    """Cosmetic changes toolkit.

    .. version-changed:: 7.0
       `from_page()` method was removed
    """

    def __init__(self, page: pywikibot.page.BasePage, *,
                 show_diff: bool = False,
                 ignore: IntEnum = CANCEL.ALL) -> None:
        """Initializer.

        .. version-changed:: 5.2
           instantiate the CosmeticChangesToolkit from a page object;
           only allow keyword arguments except for page parameter;
           `namespace` and `pageTitle` parameters are deprecated

        .. version-changed:: 7.0
           `namespace` and `pageTitle` parameters were removed

        :param page: The Page object containing the text to be modified
        :param show_diff: Show difference after replacements
        :param ignore: Ignores if an error occurred and either skips the page
            or only that method. It can be set one of the CANCEL constants
        """
        self.site = page.site
        self.title = page.title()
        self.namespace = page.namespace()

        self.show_diff = show_diff
        self.template = self.namespace == Namespace.TEMPLATE
        self.talkpage = self.namespace >= 0 and self.namespace % 2 == 1
        self.ignore = ignore

        self.common_methods = [
            self.commonsfiledesc,
            self.fixSelfInterwiki,
            self.standardizePageFooter,
            self.fixSyntaxSave,
            self.cleanUpLinks,
            self.cleanUpSectionHeaders,
            self.putSpacesInLists,
            self.translateAndCapitalizeNamespaces,
            self.translateMagicWords,
            self.replaceDeprecatedTemplates,
            self.resolveHtmlEntities,
            self.removeEmptySections,
            self.removeUselessSpaces,
            self.removeNonBreakingSpaceBeforePercent,

            self.fixHtml,
            self.fixReferences,
            self.fixStyle,
            self.fixTypo,

            self.fixArabicLetters,
        ]
        if stdnum_isbn:
            self.common_methods.append(self.fix_ISBN)

    def safe_execute(self, method: Callable[[str], str], text: str) -> str:
        """Execute the method and catch exceptions if enabled."""
        result = None
        try:
            result = method(text)
        except Exception as e:
            if self.ignore != CANCEL.METHOD:
                raise

            pywikibot.warning(
                f'Unable to perform "{method.__name__}" on "{self.title}"!')
            pywikibot.error(e)

        return text if result is None else result

    def _change(self, text: str) -> str:
        """Execute all clean up methods."""
        for method in self.common_methods:
            text = self.safe_execute(method, text)
        return text

    def change(self, text: str) -> bool | str:
        """Execute all clean up methods and catch errors if activated."""
        try:
            new_text = self._change(text)
        except Exception as e:
            if self.ignore == CANCEL.PAGE:
                pywikibot.warning(
                    f'Skipped "{self.title}", because an error occurred.'
                )
                pywikibot.error(e)
                return False
            raise

        if self.show_diff:
            pywikibot.showDiff(text, new_text)
        return new_text

    def fixSelfInterwiki(self, text: str) -> str:
        """Interwiki links to the site itself are displayed like local links.

        Remove their language code prefix.
        """
        pass

    def standardizePageFooter(self, text: str) -> str:
        """Standardize page footer.

        Makes sure that interwiki links and categories are put into the
        correct position and into the right order.

        The page footer consists of the following parts in that sequence:

        1. categories
        2. additional information depending on the local site policy
        3. interwiki

        .. version-changed:: 9.3
           uses :attr:`main_sortkey` to determine the sort key for the
           main article within a category. If the main article has a
           sort key already, it will not be changed any longer.

        :param text: Text to be modified
        :return: The modified *text*
        :raises ValueError: Wrong value of sortkey in
            :attr:`main_sortkey` for the given site
        """
        pass

    def translateAndCapitalizeNamespaces(self, text: str) -> str:
        """Use localized namespace names.

        .. version-changed:: 7.4
           No longer expect a specific namespace alias for File:
        """
        pass

    def translateMagicWords(self, text: str) -> str:
        """Use localized magic words."""
        pass

    def cleanUpLinks(self, text: str) -> str:
        """Tidy up wikilinks found in a string.

        This function will:

        * Replace underscores with spaces
        * Move leading and trailing spaces out of the wikilink and into
          the surrounding text
        * Convert URL-encoded characters into Unicode-encoded characters
        * Move trailing characters out of the link and make the link
          without using a pipe, if possible
        * Capitalize the article title of the link, if appropriate

        .. version-changed:: 8.4
           Convert URL-encoded characters if a link is an interwiki link
           or different from main namespace.
        .. version-changed:: 11.3
           UnicodeDecodeError is now ignored when encoding a links, and
           link cleanup is skipped in such case.

        :param text: String to perform the clean-up on
        :return: Text with tidied wikilinks
        """
        pass

    def resolveHtmlEntities(self, text: str) -> str:
        """Replace HTML entities with string."""
        pass

    def removeEmptySections(self, text: str) -> str:
        """Cleanup empty sections."""
        pass

    def removeUselessSpaces(self, text: str) -> str:
        """Cleanup multiple or trailing spaces."""
        pass

    def removeNonBreakingSpaceBeforePercent(self, text: str) -> str:
        """Remove a non-breaking space between number and percent sign.

        Newer MediaWiki versions automatically place a non-breaking
        space in front of a percent sign, so it is no longer required to
        place it manually.
        """
        pass

    def cleanUpSectionHeaders(self, text: str) -> str:
        """Add a space between the equal signs and the section title.

        Example::

            ==Section title==

        becomes::

        == Section title ==

        .. note:: This space is recommended in the syntax help on the
           English and German Wikipedias. It is not wanted on Lojban and
           English Wiktionaries (:phab:`T168399`, :phab:`T169064`) and
           it might be that it is not wanted on other wikis. If there
           are any complaints, please file a bug report.
        """
        pass

    def putSpacesInLists(self, text: str) -> str:
        """Add a space between the * or # and the text.

        .. note:: This space is recommended in the syntax help on the
           English, German and French Wikipedias. It might be that it
           is not wanted on other wikis. If there are any complaints,
           please file a bug report.
        """
        pass

    def replaceDeprecatedTemplates(self, text: str) -> str:
        """Replace deprecated templates."""
        pass

    # from fixes.py
    def fixSyntaxSave(self, text: str) -> str:
        """Convert weblinks to wikilink, fix link syntax."""
        pass

    def fixHtml(self, text: str) -> str:
        """Replace html markups with wikitext markups."""
        pass

    def fixReferences(self, text: str) -> str:
        """Fix references tags."""
        pass

    def fixStyle(self, text: str) -> str:
        """Convert prettytable to wikitable class."""
        pass

    def fixTypo(self, text: str) -> str:
        """Fix units."""
        pass

    def fixArabicLetters(self, text: str) -> str:
        """Fix Arabic and Persian letters."""
        pass

    def commonsfiledesc(self, text: str) -> str:
        """Clean up file descriptions on Wikimedia Commons.

        It works according to [1] and works only on pages in the file
        namespace on Wikimedia Commons.

        [1]:
        https://commons.wikimedia.org/wiki/Commons:Tools/pywiki_file_description_cleanup
        """
        pass

    def fix_ISBN(self, text: str) -> str:
        """Hyphenate ISBN numbers."""
        pass
