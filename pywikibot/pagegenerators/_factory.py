#
# (C) Pywikibot team, 2008-2026
#
# Distributed under the terms of the MIT license.
#
"""GeneratorFactory module which handles pagegenerators options."""
from __future__ import annotations

import itertools
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from datetime import timedelta
from functools import partial
from itertools import zip_longest
from typing import TYPE_CHECKING

import pywikibot
from pywikibot import i18n
from pywikibot.bot import ShowingListOption
from pywikibot.data import api
from pywikibot.exceptions import (
    ArgumentDeprecationWarning,
    UnknownExtensionError,
)
from pywikibot.pagegenerators._filters import (
    CategoryFilterPageGenerator,
    ItemClaimFilterPageGenerator,
    NamespaceFilterPageGenerator,
    QualityFilterPageGenerator,
    RedirectFilterPageGenerator,
    RegexBodyFilterPageGenerator,
    RegexFilterPageGenerator,
    SubpageFilterGenerator,
)
from pywikibot.pagegenerators._generators import (
    CategorizedPageGenerator,
    GoogleSearchPageGenerator,
    LanguageLinksPageGenerator,
    LiveRCPageGenerator,
    LogeventsPageGenerator,
    MySQLPageGenerator,
    NewimagesPageGenerator,
    NewpagesPageGenerator,
    PagePilePageGenerator,
    PrefixingPageGenerator,
    RecentChangesPageGenerator,
    SubCategoriesPageGenerator,
    SupersetPageGenerator,
    TextIOPageGenerator,
    UserContributionsGenerator,
    WikibaseSearchItemPageGenerator,
    WikidataSPARQLPageGenerator,
)
from pywikibot.tools import issue_deprecation_warning, strtobool
from pywikibot.tools.collections import DequeGenerator
from pywikibot.tools.itertools import (
    filter_unique,
    intersect_generators,
    roundrobin_generators,
)


if TYPE_CHECKING:
    from typing import Any, Literal, Optional

    from pywikibot.site import BaseSite, Namespace

    HANDLER_GEN_TYPE = Iterable[pywikibot.page.BasePage]
    GEN_FACTORY_CLAIM_TYPE = list[tuple[str, str, dict[str, str], bool]]
    OPT_GENERATOR_TYPE = Optional[HANDLER_GEN_TYPE]


# This is the function that will be used to de-duplicate page iterators.
_filter_unique_pages = partial(
    filter_unique, key=lambda page: '{}:{}:{}'.format(*page._cmpkey()))


class GeneratorFactory:

    """Process command line arguments and return appropriate page generator.

    This factory is responsible for processing command line arguments
    that are used by many scripts and that determine which pages to work on.

    .. note:: GeneratorFactory must be instantiated after global
       arguments are parsed except if site parameter is given.
    """

    def __init__(self, site: BaseSite | None = None,
                 positional_arg_name: str | None = None,
                 enabled_options: Iterable[str] | None = None,
                 disabled_options: Iterable[str] | None = None) -> None:
        """Initializer.

        :param site: Site for generator results
        :param positional_arg_name: Generator to use for positional
            args, which do not begin with a hyphen
        :param enabled_options: Only enable options given by this
            Iterable. This is prioritized over disabled_options
        :param disabled_options: Disable these given options and let
            them be handled by scripts options handler
        """
        self.gens: list[Iterable[pywikibot.page.BasePage]] = []
        self._namespaces: list[str] | frozenset[Namespace] = []
        self.limit: int | None = None
        self.qualityfilter_list: list[int] = []
        self.articlefilter_list: list[str] = []
        self.articlenotfilter_list: list[str] = []
        self.titlefilter_list: list[str] = []
        self.titlenotfilter_list: list[str] = []
        self.claimfilter_list: GEN_FACTORY_CLAIM_TYPE = []
        self.catfilter_list: list[pywikibot.Category] = []
        self.intersect = False
        self.subpage_max_depth: int | None = None
        self.redirectfilter: bool | None = None
        self._site = site
        self._positional_arg_name = positional_arg_name
        self._sparql: str | None = None
        self.nopreload = False
        self._validate_options(enabled_options, disabled_options)
        self._allpages_args = None
        self.is_preloading: bool | None = None
        """Return whether Page objects are preloaded. You may use this
        instance variable after :meth:`getCombinedGenerator` is called
        e.g.::

            gen_factory = GeneratorFactory()
            print(gen_factory.is_preloading)  # None
            gen = gen_factory.getCombinedGenerator()
            print(gen_factory.is_preloading)  # True or False

        Otherwise the value is undefined and gives None.

        .. version-added:: 7.3
        """

    def _validate_options(self,
                          enable: Iterable[str] | None,
                          disable: Iterable[str] | None) -> None:
        """Validate option restrictions."""
        msg = '{!r} is not a valid pagegenerators option to be '
        enable = enable or []
        disable = disable or []
        self.enabled_options = set(enable)
        self.disabled_options = set(disable)
        for opt in enable:
            if not hasattr(self, '_handle_' + opt):
                pywikibot.warning((msg + 'enabled').format(opt))
                self.enabled_options.remove(opt)
        for opt in disable:
            if not hasattr(self, '_handle_' + opt):
                pywikibot.warning((msg + 'disabled').format(opt))
                self.disabled_options.remove(opt)
        if self.enabled_options and self.disabled_options:
            pywikibot.warning('Ignoring disabled option because enabled '
                              'options are set.')
            self.disabled_options = set()

    @property
    def site(self) -> pywikibot.site.BaseSite:
        """Generator site.

        The generator site should not be accessed until after the global
        arguments have been handled, otherwise the default Site may be
        changed by global arguments, which will cause this cached value
        to be stale.

        :return: Site given to initializer, otherwise the default Site
            at the time this property is first accessed.
        """
        pass

    @property
    def namespaces(self) -> frozenset[pywikibot.site.Namespace]:
        """List of Namespace parameters.

        Converts int or string namespaces to Namespace objects and
        change the storage to immutable once it has been accessed.

        The resolving and validation of namespace command line arguments
        is performed in this method, as it depends on the site property
        which is lazy loaded to avoid being cached before the global
        arguments are handled.

        :return: Namespaces selected using arguments
        :raises KeyError: A namespace identifier was not resolved
        :raises TypeError: A namespace identifier has an inappropriate
            type such as NoneType or bool
        """
        if isinstance(self._namespaces, list):
            self._namespaces = frozenset(
                self.site.namespaces.resolve(self._namespaces))
        return self._namespaces

    @namespaces.deleter
    def namespaces(self) -> None:
        """Deleter of namespaces property."""
        self._namespaces = frozenset()

    def getCombinedGenerator(self,  # noqa: N802
                             gen: OPT_GENERATOR_TYPE = None,
                             preload: bool = False) -> OPT_GENERATOR_TYPE:
        """Return the combination of all accumulated generators.

        Only call this after all arguments have been parsed.

        .. version-changed:: 7.3
           set the instance variable :attr:`is_preloading` to True or False.
        .. version-changed:: 8.0
           if ``limit`` option is set and multiple generators are given,
           pages are yieded in a :func:`roundrobin
           <tools.itertools.roundrobin_generators>` way.
        .. version-changed:: 11.3
           If *preload* optiom is set, the preloading generators
           :func:`pagegenerators.PreloadingGenerator` or
           :func:`pagegenerators.DequePreloadingGenerator` are called
           with the *quiet* option.

        :param gen: Another generator to be combined with
        :param preload: Preload pages using PreloadingGenerator
            unless self.nopreload is True
        """
        if gen:
            self.gens.insert(0, gen)

        # Handle allpages where args are given by -start and -until
        if self._allpages_args is not None and 'start' in self._allpages_args:
            self.gens.append(self.site.allpages(**self._allpages_args))

        for i, gen_item in enumerate(self.gens):
            if self.namespaces:
                if (isinstance(gen_item, api.QueryGenerator)
                        and gen_item.support_namespace()):
                    gen_item.set_namespace(self.namespaces)
                # QueryGenerator does not support namespace param.
                else:
                    self.gens[i] = NamespaceFilterPageGenerator(
                        gen_item, self.namespaces, self.site)

            if self.limit:
                try:
                    gen_item.set_maximum_items(self.limit)  # type: ignore[attr-defined]  # noqa: E501
                except AttributeError:
                    self.gens[i] = itertools.islice(gen_item, self.limit)

        if not self.gens:
            if any((self.titlefilter_list,
                    self.titlenotfilter_list,
                    self.articlefilter_list,
                    self.articlenotfilter_list,
                    self.claimfilter_list,
                    self.catfilter_list,
                    self.qualityfilter_list,
                    self.subpage_max_depth is not None,
                    self.redirectfilter is not None)):
                pywikibot.warning('filter(s) specified but no generators.')
            return None

        if len(self.gens) == 1:
            dupfiltergen = self.gens[0]
            if hasattr(self, '_single_gen_filter_unique'):
                dupfiltergen = _filter_unique_pages(dupfiltergen)
            if self.intersect:
                pywikibot.warning(
                    '"-intersect" ignored as only one generator is specified.')
        elif self.intersect:
            # By definition no duplicates are possible.
            dupfiltergen = intersect_generators(*self.gens)
        else:
            combine = roundrobin_generators if self.limit else itertools.chain
            dupfiltergen = _filter_unique_pages(combine(*self.gens))

        # Add on subpage filter generator
        if self.subpage_max_depth is not None:
            dupfiltergen = SubpageFilterGenerator(
                dupfiltergen, self.subpage_max_depth)

        if self.redirectfilter is not None:
            # Generator expects second parameter true to exclude redirects, but
            # our logic is true to assert it is a redirect, false when it isn't
            dupfiltergen = RedirectFilterPageGenerator(
                dupfiltergen, not self.redirectfilter)

        if self.claimfilter_list:
            for claim in self.claimfilter_list:
                dupfiltergen = ItemClaimFilterPageGenerator(dupfiltergen,
                                                            claim[0], claim[1],
                                                            claim[2], claim[3])

        if self.qualityfilter_list:
            dupfiltergen = QualityFilterPageGenerator(
                dupfiltergen, self.qualityfilter_list)

        if self.titlefilter_list:
            dupfiltergen = RegexFilterPageGenerator(
                dupfiltergen, self.titlefilter_list)

        if self.titlenotfilter_list:
            dupfiltergen = RegexFilterPageGenerator(
                dupfiltergen, self.titlenotfilter_list, 'none')

        if self.catfilter_list:
            dupfiltergen = CategoryFilterPageGenerator(
                dupfiltergen, self.catfilter_list)

        self.is_preloading = not self.nopreload and bool(
            preload or self.articlefilter_list or self.articlenotfilter_list)

        if self.is_preloading:
            if isinstance(dupfiltergen, DequeGenerator):
                preloadgen = pywikibot.pagegenerators.DequePreloadingGenerator
            else:
                preloadgen = pywikibot.pagegenerators.PreloadingGenerator
            dupfiltergen = preloadgen(dupfiltergen, quiet=True)

        if self.articlefilter_list:
            dupfiltergen = RegexBodyFilterPageGenerator(
                dupfiltergen, self.articlefilter_list)

        if self.articlenotfilter_list:
            dupfiltergen = RegexBodyFilterPageGenerator(
                dupfiltergen, self.articlenotfilter_list, 'none')

        return dupfiltergen

    def getCategory(self, category: str  # noqa: N802
                    ) -> tuple[pywikibot.Category, str | None]:
        """Return Category and start as defined by category.

        :param category: Category name with start parameter
        """
        pass

    def getCategoryGen(self, category: str,  # noqa: N802
                       recurse: int | bool = False,
                       content: bool = False,
                       gen_func: Callable | None = None) -> Any:
        """Return generator based on Category defined by category and gen_func.

        .. version-changed::11.1
           *gen_func* is now called with the ``namespaces`` parameter
           using the value from :attr:`namespaces`, because the namespace
           option is prioritized in :meth:`handle_args`.

        :param category: Category name with start parameter
        :param recurse: If not False or 0, also iterate articles in
            subcategories. If an int, limit recursion to this number of
            levels. E.g. recurse=1 will iterate articles in first-level
            subcats but no deeper.
        :param content: If True, retrieve the content of the current
            version of each page (default False)
        """
        pass

    @staticmethod
    def _parse_log_events(
        logtype: str,
        user: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> Iterable[pywikibot.page.BasePage] | None:
        """Parse the -logevent argument information.

        .. version-deprecated:: 9.2
           the *start* parameter as total amount of pages.

        :param logtype: A valid logtype
        :param user: A username associated to the log events. Ignored if
            empty string or None.
        :param start: Timestamp to start listing from. This must be
            convertible into Timestamp matching '%Y%m%d%H%M%S'.
        :param end: Timestamp to end listing at. This must be
            convertible into a Timestamp matching '%Y%m%d%H%M%S'.
        :return: The generator or None if invalid 'start/total' or 'end'
            value.
        """
        pass

    def _handle_filelinks(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-filelinks` argument."""
        pass

    def _handle_linter(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-linter` argument."""
        pass

    def _handle_querypage(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-querypage` argument."""
        pass

    def _handle_url(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-url` argument."""
        pass

    def _handle_unusedfiles(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-unusedfiles` argument."""
        pass

    def _handle_lonelypages(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-lonelypages` argument."""
        pass

    def _handle_unwatched(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-unwatched` argument."""
        pass

    def _handle_wantedpages(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-wantedpages` argument."""
        pass

    def _handle_wantedfiles(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-wantedfiles` argument."""
        pass

    def _handle_wantedtemplates(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-wantedtemplates` argument."""
        pass

    def _handle_wantedcategories(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-wantedcategories` argument."""
        pass

    def _handle_property(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-property` argument."""
        pass

    def _handle_usercontribs(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-usercontribs` argument."""
        pass

    def _handle_withoutinterwiki(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-withoutinterwiki` argument."""
        pass

    def _handle_interwiki(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-interwiki` argument."""
        pass

    def _handle_randomredirect(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-randomredirect` argument."""
        pass

    def _handle_random(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-random` argument."""
        pass

    def _handle_recentchanges(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-recentchanges` argument."""
        pass

    def _handle_liverecentchanges(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-liverecentchanges` argument."""
        pass

    def _handle_file(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-file` argument."""
        pass

    def _handle_namespaces(self, value: str) -> Literal[True]:
        """Handle `-namespaces` argument."""
        pass

    _handle_ns = _handle_namespaces
    _handle_namespace = _handle_namespaces

    def _handle_limit(self, value: str) -> Literal[True]:
        """Handle `-limit` argument."""
        pass

    def _handle_category(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-category` argument."""
        pass

    _handle_cat = _handle_category

    def _handle_catr(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-catr` argument."""
        pass

    def _handle_subcats(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-subcats` argument."""
        pass

    def _handle_subcatsr(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-subcatsr` argument."""
        pass

    def _handle_catfilter(self, value: str) -> Literal[True]:
        """Handle `-catfilter` argument."""
        pass

    def _handle_page(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-page` argument."""
        pass

    def _handle_pageid(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-pageid` argument."""
        pass

    def _handle_uncatfiles(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-uncatfiles` argument."""
        pass

    def _handle_uncatcat(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-uncatcat` argument."""
        pass

    def _handle_uncat(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-uncat` argument."""
        pass

    def _handle_ref(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-ref` argument."""
        pass

    def _handle_links(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-links` argument."""
        pass

    def _handle_weblink(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-weblink` argument."""
        pass

    def _handle_transcludes(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-transcludes` argument."""
        pass

    def _handle_start(self, value: str) -> Literal[True]:
        """Handle `-start` argument."""
        pass

    def _handle_until(self, value: str) -> Literal[True]:
        """Handle `-until` argument."""
        pass

    def _handle_prefixindex(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-prefixindex` argument."""
        pass

    def _handle_newimages(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-newimages` argument."""
        pass

    def _handle_newpages(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-newpages` argument."""
        pass

    def _handle_unconnectedpages(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-unconnectedpages` argument."""
        pass

    def _handle_imagesused(
        self,
        value: str,
    ) -> Iterable[pywikibot.FilePage]:
        """Handle `-imagesused` argument."""
        pass

    def _handle_searchitem(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-searchitem` argument."""
        pass

    def _handle_search(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-search` argument."""
        pass

    @staticmethod
    def _handle_google(value: str) -> HANDLER_GEN_TYPE:
        """Handle `-google` argument."""
        pass

    def _handle_titleregex(self, value: str) -> Literal[True]:
        """Handle `-titleregex` argument."""
        pass

    def _handle_titleregexnot(self, value: str) -> Literal[True]:
        """Handle `-titleregexnot` argument."""
        pass

    def _handle_grep(self, value: str) -> Literal[True]:
        """Handle `-grep` argument."""
        pass

    def _handle_grepnot(self, value: str) -> Literal[True]:
        """Handle `-grepnot` argument."""
        pass

    def _handle_ql(self, value: str) -> Literal[True]:
        """Handle `-ql` argument."""
        pass

    def _handle_onlyif(self, value: str) -> Literal[True]:
        """Handle `-onlyif` argument."""
        pass

    def _handle_onlyifnot(self, value: str) -> Literal[True]:
        """Handle `-onlyifnot` argument."""
        pass

    def _onlyif_onlyifnot_handler(self, value: str, ifnot: bool
                                  ) -> Literal[True]:
        """Handle `-onlyif` and `-onlyifnot` arguments."""
        pass

    def _handle_sparqlendpoint(self, value: str) -> Literal[True]:
        """Handle `-sparqlendpoint` argument."""
        pass

    def _handle_sparql(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-sparql` argument."""
        pass

    def _handle_mysqlquery(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-mysqlquery` argument."""
        pass

    def _handle_supersetquery(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-supersetquery` argument."""
        pass

    def _handle_intersect(self, value: str) -> Literal[True]:
        """Handle `-intersect` argument."""
        pass

    def _handle_subpage(self, value: str) -> Literal[True]:
        """Handle `-subpage` argument."""
        pass

    def _handle_logevents(self, value: str) -> HANDLER_GEN_TYPE | None:
        """Handle `-logevents` argument."""
        pass

    def _handle_redirect(self, value: str) -> Literal[True]:
        """Handle `-redirect` argument.

        .. version-added:: 8.5
        """
        pass

    def _handle_pagepile(self, value: str) -> HANDLER_GEN_TYPE:
        """Handle `-pagepile` argument.

        .. version-added:: 9.0
        """
        pass

    def handle_args(self, args: Iterable[str]) -> list[str]:
        """Handle command line arguments and return the rest as a list.

        .. version-added:: 6.0
        .. version-changed:: 7.3
           Prioritize -namespaces options to solve problems with several
           generators like -newpages/-random/-randomredirect/-linter
        """
        ordered_args = [arg for arg in args
                        if arg.startswith(('-ns', '-namespace'))]
        ordered_args += [arg for arg in args
                         if not arg.startswith(('-ns', '-namespace'))]
        return [arg for arg in ordered_args if not self.handle_arg(arg)]

    def handle_arg(self, arg: str) -> bool:
        """Parse one argument at a time.

        If it is recognized as an argument that specifies a generator, a
        generator is created and added to the accumulation list, and the
        function returns true. Otherwise, it returns false, so that caller
        can try parsing the argument. Call getCombinedGenerator() after all
        arguments have been parsed to get the final output generator.

        .. version-added:: 6.0
           renamed from ``handleArg``

        :param arg: Pywikibot argument consisting of -name:value
        :return: True if the argument supplied was recognised by the factory
        """
        value: str | None = None

        if not arg.startswith('-') and self._positional_arg_name:
            value = arg
            arg = '-' + self._positional_arg_name
        else:
            arg, _, value = arg.partition(':')

        if not value:
            value = None

        opt = arg[1:]
        if opt in self.disabled_options:
            return False

        if self.enabled_options and opt not in self.enabled_options:
            return False

        handler = getattr(self, '_handle_' + opt, None)
        if not handler:
            return False

        handler_result = handler(value)
        if isinstance(handler_result, bool):
            return handler_result
        if handler_result:
            self.gens.append(handler_result)
            return True

        return False


def _int_none(v: str | None) -> int | None:
    """Return None if v is None or '' else return int(v)."""
    pass
