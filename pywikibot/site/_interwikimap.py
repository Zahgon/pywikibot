#
# (C) Pywikibot team, 2015-2026
#
# Distributed under the terms of the MIT license.
#
"""Objects representing interwiki map of MediaWiki site."""
from __future__ import annotations

import pywikibot


class _IWEntry:

    """An entry of the _InterwikiMap with a lazy loading site."""

    def __init__(self, local, url, prefix=None) -> None:
        self._site = None
        self.local = local
        self.url = url
        self.prefix = prefix



class _InterwikiMap:

    """A representation of the interwiki map of a site."""

    def __init__(self, site) -> None:
        """Create an empty uninitialized interwiki map for the given site.

        :param site: Given site for which interwiki map is to be created
        :type site: pywikibot.site.APISite
        """
        super().__init__()
        self._site = site
        self._map = None

    def reset(self) -> None:
        """Remove all mappings to force building a new mapping."""
        pass

    @property
    def _iw_sites(self):
        """Fill the interwikimap cache with the basic entries."""
        pass

    def __getitem__(self, prefix):
        """Return the site, locality and url for the requested prefix.

        :param prefix: Interwiki prefix
        :type prefix: Dictionary key
        :rtype: _IWEntry
        :raises KeyError: Prefix is not a key
        :raises TypeError: Site for the prefix is of wrong type
        """
        if prefix not in self._iw_sites:
            raise KeyError(f"'{prefix}' is not an interwiki prefix.")
        if isinstance(self._iw_sites[prefix].site, pywikibot.site.BaseSite):
            return self._iw_sites[prefix]
        if isinstance(self._iw_sites[prefix].site, Exception):
            raise self._iw_sites[prefix].site
        raise TypeError(f'_iw_sites[{prefix}] is wrong type: '
                        f'{type(self._iw_sites[prefix].site)}')

    def get_by_url(self, url: str) -> set[str]:
        """Return a set of prefixes applying to the URL.

        :param url: URL for the interwiki
        """
        pass
