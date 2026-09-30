"""
babel.messages.splitmerge
~~~~~~~~~~~~~~~~~~~~~~~~~

Split a message catalog into per-area catalogs grouped by the source file
prefixes referenced in message locations, and merge the translated per-area
catalogs back into a single catalog.

A message whose locations match several groups is duplicated into every
matching group, so each translator only sees the messages relevant to their
area.  Messages that match no group are collected in a separate "remainder"
group.  When the translated catalogs are merged back, catalogs split from the
same original catalog can be recombined losslessly.

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

import posixpath
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from copy import copy
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from babel.messages.catalog import Catalog, Message

__all__ = [
    'MergeConflict',
    'MergeConflictError',
    'SplitMergeError',
    'merge_catalogs',
    'split_catalog',
]


class SplitMergeError(Exception):
    """Base class for errors raised while splitting or merging catalogs."""


class MergeConflict(NamedTuple):
    """A message translated differently in two or more split catalogs.

    :ivar key: the catalog key of the message (the message id, or a
               (msgid, context) tuple for contextual messages)
    :ivar translations: the distinct translations found for the message
    :ivar sources: the names of the split catalogs providing each
                   translation, in the same order as translations
    """

    key: object
    translations: list[object]
    sources: list[str]


class MergeConflictError(SplitMergeError):
    """Raised when split catalogs contain conflicting translations.

    The whole merge is aborted without producing a partial catalog; inspect
    the conflicts attribute to see every message that needs resolution.
    """

    def __init__(self, conflicts: list[MergeConflict]) -> None:
        if not conflicts:
            raise ValueError('at least one conflict is required')
        self.conflicts = conflicts
        keys = ', '.join(repr(_key_label(conflict.key)) for conflict in conflicts)
        super().__init__(f'conflicting translations for messages: {keys}')


def _key_label(key: object) -> object:
    if isinstance(key, tuple):
        return key[0]
    return key


def _normalize_prefix(prefix: str) -> tuple[str, ...]:
    """Split a path prefix into normalized path components."""
    prefix = prefix.strip().replace('\\', '/')
    components: list[str] = []
    for component in prefix.split('/'):
        if component in ('', '.'):
            continue
        if component == '..':
            raise SplitMergeError(
                f'invalid path prefix (parent component not allowed): {prefix!r}',
            )
        components.append(component)
    if not components:
        raise SplitMergeError(f'invalid empty path prefix: {prefix!r}')
    return tuple(components)


def _normalize_location(filename: str) -> tuple[str, ...]:
    """Split a location filename into normalized path components."""
    normalized = posixpath.normpath(filename.replace('\\', '/'))
    return tuple(
        component for component in normalized.split('/') if component not in ('', '.')
    )


def _matches_prefix(
    location_components: tuple[str, ...],
    prefix_components: tuple[str, ...],
) -> bool:
    """Match a prefix on complete path component boundaries."""
    return location_components[: len(prefix_components)] == prefix_components


def _new_catalog_like(template: Catalog) -> Catalog:
    from babel.messages.catalog import Catalog

    catalog = Catalog(
        locale=template.locale_identifier,
        domain=template.domain,
        header_comment=template._header_comment,
        project=template.project,
        version=template.version,
        copyright_holder=template.copyright_holder,
        msgid_bugs_address=template.msgid_bugs_address,
        creation_date=copy(template.creation_date),
        revision_date=copy(template.revision_date),
        last_translator=template.last_translator,
        language_team=template.language_team,
        charset=template.charset,
        fuzzy=template.fuzzy,
    )
    catalog.mime_headers = list(template.mime_headers)
    catalog._num_plurals = template._num_plurals
    catalog._plural_expr = template._plural_expr
    return catalog


def split_catalog(
    catalog: Catalog,
    groups: Mapping[str, str | Iterable[str]],
    remainder_name: str = 'remainder',
) -> OrderedDict[str, Catalog]:
    """Split catalog into one catalog per group.

    Messages are assigned to groups based on their locations: a message is
    put into a group when at least one of its locations has a path that has
    the group's prefix as an initial sequence of path components.  A message
    may therefore appear in several groups.  Messages that match no group
    are placed in a separate remainder catalog.

    The matching operates on path components, so the prefix src/app matches
    src/app/views.py but not src/apple/views.py.  Both / and backslash are
    accepted as path separators.

    >>> from babel.messages import Catalog
    >>> catalog = Catalog()
    >>> _ = catalog.add('Hello', locations=[('src/app/ui.py', 1)])
    >>> parts = split_catalog(catalog, {'app': 'src/app', 'other': 'src/apple'})
    >>> 'Hello' in parts['app']
    True
    >>> 'Hello' in parts['other']
    False
    >>> 'Hello' in parts['remainder']
    False

    :param catalog: the catalog to split
    :param groups: an ordered mapping of group name to path prefix or
                   iterable of path prefixes
    :param remainder_name: name of the group that receives unmatched
                           messages
    :return: an ordered mapping of group name to the split catalog; the
             remainder catalog is always the last entry
    """
    if remainder_name in groups:
        raise SplitMergeError(
            f'the remainder name {remainder_name!r} clashes with a group name',
        )

    normalized_groups: OrderedDict[str, list[tuple[str, ...]]] = OrderedDict()
    for name, prefixes in groups.items():
        if isinstance(prefixes, str):
            prefixes = (prefixes,)
        normalized_groups[name] = [_normalize_prefix(prefix) for prefix in prefixes]

    parts: OrderedDict[str, Catalog] = OrderedDict()
    for name in (*normalized_groups, remainder_name):
        parts[name] = _new_catalog_like(catalog)

    for message in catalog:
        if not message.id:
            continue
        location_components = [
            _normalize_location(filename) for filename, _lineno in message.locations
        ]
        matched = False
        for name, prefixes in normalized_groups.items():
            if any(
                _matches_prefix(components, prefix)
                for components in location_components
                for prefix in prefixes
            ):
                parts[name][message.id] = message.clone()
                matched = True
        if not matched:
            parts[remainder_name][message.id] = message.clone()

    return parts


def _normalize_named_catalogs(
    catalogs: Mapping[str, Catalog] | Iterable[Catalog | tuple[str, Catalog]],
) -> list[tuple[str, Catalog]]:
    if isinstance(catalogs, Mapping):
        return list(catalogs.items())

    named: list[tuple[str, Catalog]] = []
    for index, item in enumerate(catalogs):
        if isinstance(item, tuple):
            name, catalog = item
        else:
            name, catalog = str(index), item
        named.append((str(name), catalog))
    return named


def _translation_value(message: Message) -> object:
    string = message.string
    if isinstance(string, (list, tuple)):
        return tuple(string)
    return string


def _is_translated(string: object) -> bool:
    if isinstance(string, tuple):
        return any(part for part in string)
    return bool(string)


def merge_catalogs(
    catalogs: Mapping[str, Catalog] | Iterable[Catalog | tuple[str, Catalog]],
    baseline: Catalog | None = None,
) -> Catalog:
    """Merge catalogs produced by split_catalog back together.

    Every input catalog is inspected before any output is built.  If the same
    message has different (non-empty) translations in two or more catalogs,
    a MergeConflictError is raised listing all such messages and no partial
    result catalog is returned.  Empty translations never override existing
    translations, so a message only translated in one area is accepted.

    When baseline is given (typically the catalog that was originally
    split), the merged result is refreshed against it: messages renamed in
    the source follow the baseline's fuzzy matching, locations and flags
    are taken from the current baseline, and messages absent from the
    baseline become obsolete instead of being silently dropped.

    :param catalogs: a mapping of group name to catalog, or an iterable of
                     catalogs or (name, catalog) pairs
    :param baseline: optional current reference catalog to refresh against
    :return: the merged catalog
    :raises MergeConflictError: if conflicting translations are found
    """
    named_catalogs = _normalize_named_catalogs(catalogs)
    if not named_catalogs:
        raise SplitMergeError('at least one catalog is required to merge')

    seen: dict[object, tuple[object, str]] = {}
    conflicts: list[MergeConflict] = []
    for name, catalog in named_catalogs:
        for message in catalog:
            if not message.id:
                continue
            key = catalog._key_for(message.id, message.context)
            value = _translation_value(message)
            if not _is_translated(value):
                continue
            previous = seen.get(key)
            if previous is None:
                seen[key] = (value, name)
            elif previous[0] != value:
                conflict = next((item for item in conflicts if item.key == key), None)
                if conflict is None:
                    conflict = MergeConflict(key, [previous[0]], [previous[1]])
                    conflicts.append(conflict)
                if value not in conflict.translations:
                    conflict.translations.append(value)
                    conflict.sources.append(name)
    if conflicts:
        raise MergeConflictError(conflicts)

    template = named_catalogs[0][1]
    merged = _new_catalog_like(template)
    first_messages: dict[object, Message] = {}
    translated_strings: dict[object, object] = {}
    for _name, catalog in named_catalogs:
        for message in catalog:
            if not message.id:
                continue
            key = catalog._key_for(message.id, message.context)
            clone = message.clone()
            merged[clone.id] = clone
            if key not in first_messages:
                first_messages[key] = merged._messages[key]
            value = _translation_value(message)
            if _is_translated(value) and key not in translated_strings:
                translated_strings[key] = copy(value)

    # Catalog.__setitem__ never replaces the translation of an existing
    # message, so make sure a translation provided in a later split catalog
    # wins over the empty string of an earlier one.
    for key, string in translated_strings.items():
        first_messages[key].string = string

    merged.fuzzy = any(message.fuzzy for message in merged)

    if baseline is not None:
        merged.update(baseline)
        merged.fuzzy = any(message.fuzzy for message in merged)

    return merged
