#
# (C) Pywikibot team, 2008-2026
#
# Distributed under the terms of the MIT license.
#
"""Decorators used by site models."""
from __future__ import annotations

import os
from textwrap import fill

from pywikibot.exceptions import UnknownExtensionError, UserRightsError
from pywikibot.tools import MediaWikiVersion, manage_wrapping


CLOSED_WIKI_MSG = (
    'Site {site} has been closed. Only steward can perform requested action.'
)


def must_be(group: str | None = None):
    """Decorator to require a certain user status when method is called.

    :param group: The group the logged in user should belong to. This
        parameter can be overridden by keyword argument 'as_group'.
    :return: Method decorator
    :raises UserRightsError: User is not part of the required user
        group.
    """
    def decorator(fn):

        manage_wrapping(callee, fn)
        return callee

    return decorator


def need_extension(extension: str):
    """Decorator to require a certain MediaWiki extension.

    :param extension: The MediaWiki extension required
    :return: A decorator to make sure the requirement is satisfied when
        the decorated function is called.
    """
    def decorator(fn):

        manage_wrapping(callee, fn)
        return callee

    return decorator


def need_right(right: str | None = None):
    """Decorator to require a certain user right when method is called.

    :param right: The right the logged in user should have.
    :return: Method decorator
    :raises UserRightsError: User has insufficient rights.
    """
    def decorator(fn):

        manage_wrapping(callee, fn)
        return callee

    return decorator


def need_version(version: str):
    """Decorator to require a certain MediaWiki version number.

    :param version: The mw version number required
    :return: A decorator to make sure the requirement is satisfied when
        the decorated function is called.
    """
    def decorator(fn):

        manage_wrapping(callee, fn)

        return callee
    return decorator
