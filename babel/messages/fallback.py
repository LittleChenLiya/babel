"""
babel.messages.fallback
~~~~~~~~~~~~~~~~~~~~~~~

Read-only fallback lists for message catalogs.

This module inspects a `Catalog` and produces a list of messages that would
fall back to the source string at runtime, following the exact rules that
``write_mo`` uses to decide which messages are compiled into a MO file:

* A singular message with an empty translation is omitted from the MO file
  and falls back to the source string.
* A message marked as ``fuzzy`` is omitted unless ``use_fuzzy`` is true.
* A plural message is always compiled (its ``msgstr`` tuple is truthy), but
  any empty slot falls back to the singular or plural source form.

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from babel.messages.catalog import Catalog, Message

__all__ = ['FallbackEntry', 'list_fallbacks']


@dataclass
class FallbackEntry:
    """A single entry in a read-only fallback list.

    :param message: the message that may fall back
    :param category: the fallback category, one of ``'untranslated'``,
        ``'explicit_empty'``, ``'fuzzy'``, ``'plural_missing'`` or
        ``'obsolete'``
    :param will_fallback: whether the message will actually fall back to the
        source string given the caller's ``use_fuzzy`` strategy
    :param missing_slots: the plural slot numbers that are missing or empty
        (empty for singular messages)
    """

    message: Message
    category: str
    will_fallback: bool
    missing_slots: list[int] = field(default_factory=list)


def _missing_slots(message: Message, num_plurals: int) -> list[int]:
    """Return the plural slot numbers that are missing or empty.

    A slot is considered missing when it is beyond the length of the
    message's ``string`` tuple or when its value is falsy (empty string).
    """
    if not message.pluralizable:
        return []
    slots = message.string
    if not isinstance(slots, (list, tuple)):
        # Defensive: a pluralizable message should always have a sequence,
        # but if it does not, every slot is missing.
        return list(range(num_plurals))
    missing = []
    for i in range(num_plurals):
        if i >= len(slots) or not slots[i]:
            missing.append(i)
    return missing


def _classify(
    message: Message,
    catalog: Catalog,
    use_fuzzy: bool,
) -> FallbackEntry | None:
    """Classify a single message, returning a `FallbackEntry` or ``None``.

    Returns ``None`` for messages that are fully translated and would not
    fall back.
    """
    if message.fuzzy:
        # Fuzzy messages are excluded from the MO file unless use_fuzzy is
        # true, regardless of whether they also have missing plural slots.
        return FallbackEntry(
            message=message,
            category='fuzzy',
            will_fallback=not use_fuzzy,
        )

    if message.pluralizable:
        missing = _missing_slots(message, catalog.num_plurals)
        if not missing:
            return None  # every slot is filled, no fallback
        if len(missing) == catalog.num_plurals:
            category = 'explicit_empty'
        else:
            category = 'plural_missing'
        return FallbackEntry(
            message=message,
            category=category,
            will_fallback=True,
            missing_slots=missing,
        )

    # Singular message: an empty translation is omitted from the MO file.
    if not message.string:
        return FallbackEntry(
            message=message,
            category='untranslated',
            will_fallback=True,
        )

    return None  # translated, no fallback


def list_fallbacks(
    catalog: Catalog,
    use_fuzzy: bool = False,
) -> tuple[list[FallbackEntry], list[FallbackEntry]]:
    """Generate a read-only fallback list for the catalog.

    The list classifies each message that would fall back at runtime,
    following the rules used by ``write_mo`` to decide which messages are
    compiled into a MO file:

    * A singular message with an empty translation is omitted from the MO
      file and falls back to the source string.
    * A fuzzy message is omitted unless ``use_fuzzy`` is true.
    * A plural message is always compiled, but any empty slot falls back to
      the singular or plural source form.

    Obsolete messages (those in ``catalog.obsolete``) are listed separately
    and are not classified.

    :param catalog: the `Catalog` to inspect
    :param use_fuzzy: whether fuzzy translations are considered usable
        (matching the ``use_fuzzy`` argument of `write_mo`)
    :return: a tuple of ``(entries, obsolete_entries)``, where ``entries``
        is the fallback list for active messages (in catalog order) and
        ``obsolete_entries`` lists messages that are no longer part of the
        catalog
    """
    entries: list[FallbackEntry] = []
    for message in catalog._messages.values():
        entry = _classify(message, catalog, use_fuzzy)
        if entry is not None:
            entries.append(entry)

    obsolete_entries: list[FallbackEntry] = []
    for message in catalog.obsolete.values():
        obsolete_entries.append(
            FallbackEntry(
                message=message,
                category='obsolete',
                will_fallback=True,
            ),
        )

    return entries, obsolete_entries
