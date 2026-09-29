"""
babel.messages.split
~~~~~~~~~~~~~~~~~~~

Split a message catalog into several catalogs grouped by the source path
prefixes of message locations (for handing out parts of a translation to
different owners), and merge the resulting catalogs back together.

A message is assigned to every group whose prefix matches at least one of
its locations; if it matches no group (or has no locations at all), it goes
into the separate *remainder* catalog.  Prefix matching is performed
component by component, so the prefix ``src/app`` matches
``src/app/x.py`` but not ``src/apple.py``.

>>> from babel.messages import Catalog
>>> from babel.messages.split import split_catalog, merge_catalogs
>>> catalog = Catalog()
>>> _ = catalog.add('hello', locations=[('src/app/views.py', 1)])
>>> parts = split_catalog(catalog, {'app': 'src/app'})
>>> 'hello' in parts['app']
True
>>> merged = merge_catalogs(parts)
>>> merged['hello'].is_identical(catalog['hello'])
True

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy

from babel.messages.catalog import Catalog, Message

__all__ = [
    'CatalogSplitError',
    'MergeConflictError',
    'merge_catalogs',
    'path_matches_prefix',
    'split_catalog',
    'split_path',
]

_REMAINDER_DEFAULT = 'remainder'
_PREFIX_SEP = re.compile(r'[\\/]+')
_DRIVE_RE = re.compile(r'^[A-Za-z]:(?=/|$)')

PathLike = str | os.PathLike[str]


class CatalogSplitError(ValueError):
    """Raised when a catalog cannot be split due to invalid arguments."""


class MergeConflictError(Exception):
    """Raised when catalogs to merge contain different translations.

    The conflicting entries are available as a list of dictionaries on the
    :attr:`conflicts` attribute.
    """

    def __init__(self, conflicts: list) -> None:
        self.conflicts = conflicts
        messages = ', '.join(str(conflict['key']) for conflict in conflicts)
        super().__init__(f'Conflicting translations for messages: {messages}')


def split_path(path: PathLike) -> tuple:
    """Split a filesystem path into normalized path components.

    Both ``/`` and backslashes are accepted as separators; leading
    separators, ``./`` prefixes and Windows drive letters are removed, and
    empty components are discarded.

    >>> split_path('src/app/views.py')
    ('src', 'app', 'views.py')
    >>> split_path('./src/app/')
    ('src', 'app')
    """
    normalized = str(path).replace(chr(92), '/')
    normalized = _DRIVE_RE.sub('', normalized)
    while normalized.startswith('./'):
        normalized = normalized[2:]
    components = [part for part in _PREFIX_SEP.split(normalized) if part not in ('', '.')]
    return tuple(components)


def path_matches_prefix(path: PathLike, prefix: PathLike) -> bool:
    """Return whether ``path`` is inside ``prefix`` using component matching.

    Matching is component-wise rather than a plain string prefix check, so
    ``src/app`` matches ``src/app/views.py`` but not ``src/apple.py``.

    >>> path_matches_prefix('src/app/views.py', 'src/app')
    True
    >>> path_matches_prefix('src/apple.py', 'src/app')
    False
    >>> path_matches_prefix('src/app', 'src/app')
    True
    """
    path_components = split_path(path)
    prefix_components = split_path(prefix)
    if not prefix_components:
        raise CatalogSplitError('path prefix must not be empty')
    return path_components[: len(prefix_components)] == prefix_components


def _normalize_groups(
    groups: Mapping[str, str | Iterable[str]],
    remainder_name: str,
) -> dict:
    if not isinstance(groups, Mapping):
        raise CatalogSplitError('groups must be a mapping of name to path prefix(es)')
    if not remainder_name:
        raise CatalogSplitError('remainder group name must not be empty')
    normalized: dict = {}
    for name, prefixes in groups.items():
        if not isinstance(name, str) or not name:
            raise CatalogSplitError('group names must be non-empty strings')
        if name == remainder_name:
            raise CatalogSplitError(
                f'group name {name!r} clashes with the remainder group name',
            )
        if isinstance(prefixes, (str, bytes)):
            prefix_iterable = [prefixes]
        else:
            prefix_iterable = list(prefixes)
        components = []
        for prefix in prefix_iterable:
            if not isinstance(prefix, str) or not prefix:
                raise CatalogSplitError(f'group {name!r} contains an empty path prefix')
            prefix_components = split_path(prefix)
            if not prefix_components:
                raise CatalogSplitError(f'group {name!r} contains an empty path prefix')
            components.append(prefix_components)
        if not components:
            raise CatalogSplitError(f'group {name!r} must contain at least one path prefix')
        normalized[name] = tuple(components)
    return normalized


def _matching_groups(message: Message, groups: Mapping[str, tuple]) -> list:
    matched = []
    for name, prefixes in groups.items():
        for location, _lineno in message.locations:
            location_components = split_path(location)
            if any(location_components[: len(prefix)] == prefix for prefix in prefixes):
                matched.append(name)
                break
    return matched


def _copy_catalog_metadata(catalog: Catalog) -> Catalog:
    copy = Catalog(
        locale=catalog.locale_identifier,
        domain=catalog.domain,
        header_comment=catalog._header_comment,
        project=catalog.project,
        version=catalog.version,
        copyright_holder=catalog.copyright_holder,
        msgid_bugs_address=catalog.msgid_bugs_address,
        creation_date=catalog.creation_date,
        revision_date=catalog.revision_date,
        last_translator=catalog.last_translator,
        language_team=catalog.language_team,
        charset=catalog.charset,
        fuzzy=catalog.fuzzy,
    )
    copy.mime_headers = deepcopy(catalog.mime_headers)
    return copy


def split_catalog(
    catalog: Catalog,
    groups: Mapping[str, str | Iterable[str]],
    *,
    remainder_name: str = _REMAINDER_DEFAULT,
    include_remainder: bool = True,
) -> dict:
    """Split ``catalog`` into one catalog per group plus a remainder.

    Each group maps a name to a path prefix or an iterable of path
    prefixes.  A message is copied into every group whose prefix matches
    one of its message locations; matching is component-wise, see
    :func:`path_matches_prefix`.  Messages matching no group are copied
    into the remainder catalog.  Message copies are left completely
    untouched, so catalogs merged with :func:`merge_catalogs` round-trip
    back to the original messages.

    :param catalog: the catalog to split
    :param groups: mapping of group name to path prefix(es)
    :param remainder_name: name of the key holding unmatched messages
    :param include_remainder: always include the (possibly empty) remainder
                              catalog in the result
    :return: an ordered mapping of group name to the corresponding catalog
    """
    if not isinstance(catalog, Catalog):
        raise CatalogSplitError('catalog must be a Catalog instance')
    normalized_groups = _normalize_groups(groups, remainder_name)

    parts = {name: _copy_catalog_metadata(catalog) for name in normalized_groups}
    remainder = _copy_catalog_metadata(catalog)

    for message in catalog:
        if not message.id:
            continue
        matched = _matching_groups(message, normalized_groups)
        for name in matched:
            parts[name][message.id] = message.clone()
        if not matched:
            remainder[message.id] = message.clone()

    result = dict(parts)
    if include_remainder or len(remainder):
        result[remainder_name] = remainder
    return result


def _message_key(message: Message):
    singular = message.id[0] if isinstance(message.id, (list, tuple)) else message.id
    if message.context is not None:
        return singular, message.context
    return singular


def _translation_value(message: Message):
    if isinstance(message.string, (list, tuple)):
        return tuple(message.string)
    return message.string


def _iter_named_catalogs(catalogs) -> list:
    if isinstance(catalogs, Mapping):
        items = list(catalogs.items())
    else:
        items = list(catalogs)
    normalized = []
    for index, item in enumerate(items):
        try:
            name, catalog = item
        except (TypeError, ValueError) as exc:
            raise CatalogSplitError(
                'catalogs must be a mapping or an iterable of (name, catalog) pairs',
            ) from exc
        if not isinstance(name, str) or not name:
            raise CatalogSplitError(
                f'catalog name at position {index} must be a non-empty string',
            )
        if not isinstance(catalog, Catalog):
            raise CatalogSplitError(f'catalog {name!r} must be a Catalog instance')
        normalized.append((name, catalog))
    if not normalized:
        raise CatalogSplitError('at least one catalog is required to merge')
    names = [name for name, _catalog in normalized]
    if len(set(names)) != len(names):
        raise CatalogSplitError('catalog names must be unique')
    return normalized


def merge_catalogs(
    catalogs: Mapping[str, Catalog] | Iterable[tuple[str, Catalog]],
    template: Catalog | None = None,
    *,
    no_fuzzy_matching: bool = False,
) -> Catalog:
    """Merge catalogs produced by :func:`split_catalog` back into one catalog.

    Messages shared between several catalogs must carry the same
    translation; untranslated (empty) copies are ignored.  If different
    non-empty translations are found, :class:`MergeConflictError` is raised
    *before* any result catalog is built or an input catalog is mutated,
    so a conflict never yields a half-merged catalog.

    When ``template`` is given, the merged catalog is refreshed against it
    using :meth:`Catalog.update`: messages removed from the template become
    obsolete, new messages are added untranslated, and renamed messages are
    recovered by fuzzy matching and marked fuzzy.

    :param catalogs: a mapping of name to catalog, or an iterable of
                     ``(name, catalog)`` pairs
    :param template: optional up-to-date reference catalog (usually a POT)
    :param no_fuzzy_matching: disable fuzzy matching when updating against
                              ``template``
    :return: the merged catalog
    """
    named_catalogs = _iter_named_catalogs(catalogs)

    # Validate everything and collect the messages to use before building
    # the output catalog, so a conflict never leaves a half-merged result.
    chosen = {}
    occurrence_order = []
    conflicts = []
    for name, catalog in named_catalogs:
        for message in catalog:
            if not message.id:
                continue
            key = _message_key(message)
            value = _translation_value(message)
            if key not in chosen:
                occurrence_order.append(key)
                chosen[key] = (message, value, name)
                continue
            _previous_message, previous_value, previous_name = chosen[key]
            translated = {candidate for candidate in (previous_value, value) if candidate}
            if len(translated) > 1:
                conflicts.append(
                    {
                        'key': key,
                        'translations': sorted(translated, key=repr),
                        'sources': sorted({previous_name, name}),
                    },
                )
                continue
            if not previous_value and value:
                chosen[key] = (message, value, name)
    if conflicts:
        raise MergeConflictError(conflicts)

    merged = _copy_catalog_metadata(named_catalogs[0][1])
    for key in occurrence_order:
        message, _value, _name = chosen[key]
        merged[message.id] = message.clone()

    if template is not None:
        if not isinstance(template, Catalog):
            raise CatalogSplitError('template must be a Catalog instance')
        merged.update(template, no_fuzzy_matching=no_fuzzy_matching)

    return merged
