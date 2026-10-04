"""
babel.messages.merge
~~~~~~~~~~~~~~~~~~~~

Merging two extraction result sets into a single source list.

The :func:`merge_extraction_results` function consumes extraction records as
produced by :func:`babel.messages.extract.extract_from_dir` (i.e. 5-tuples of
``(filename, lineno, message, comments, context)``) and combines them into one
deduplicated source list.  Messages are deduplicated by their identity
(message id, context and plural composition), while every file line number
together with the extraction method that produced it is kept as a source.

Locations that the two extractors disagree on (different message identity at
the same file and line) are reported as conflicts instead of being silently
picked from one side.

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple

# An extraction record as emitted by the extractor:
#   (filename, lineno, message, comments, context)
_ExtractionRecord = tuple[
    str,
    int,
    "str | tuple[str, ...]",
    "list[str]",
    "str | None",
]


class SourceRecord(NamedTuple):
    """An extraction record augmented with the method that produced it."""

    filename: str
    lineno: int
    message: str | tuple[str, ...]
    comments: list[str]
    context: str | None
    method: str


class Location(NamedTuple):
    """A single source location: normalized file path, line and method."""

    filename: str
    lineno: int
    method: str


class MergedMessage(NamedTuple):
    """A message deduplicated by identity, carrying all of its sources."""

    message: str | tuple[str, ...]
    context: str | None
    locations: list[Location]
    comments: list[str]


class Conflict(NamedTuple):
    """A location the two extractors disagree on, with both full records."""

    filename: str
    lineno: int
    record_a: SourceRecord
    record_b: SourceRecord


class MergeResult(NamedTuple):
    """The result of merging two extraction result sets."""

    messages: list[MergedMessage]
    conflicts: list[Conflict]


def _normalize_filename(filename: str) -> str:
    """Normalize a relative file path, converting Windows separators."""
    return filename.replace("\\", "/")


def _to_source_record(record: _ExtractionRecord, method: str) -> SourceRecord:
    filename, lineno, message, comments, context = record
    return SourceRecord(
        filename=_normalize_filename(filename),
        lineno=lineno,
        message=message,
        comments=list(comments),
        context=context,
        method=method,
    )


def _identity(message, context) -> tuple:
    """The dedup key for a message.

    The full plural composition is part of the identity, so a singular
    message and its plural form (or two plural forms with different plural
    tuples) never collapse into one another.  ``None`` and empty-string
    contexts are kept distinct.
    """
    return (message, context)


def _message_sort_key(message) -> tuple:
    # Tag singular vs. plural so str and tuple are never compared directly.
    if isinstance(message, (list, tuple)):
        return (1, tuple(message))
    return (0, message)


def _context_sort_key(context) -> tuple:
    # ``None`` and empty-string are distinct identities but need a total order.
    if context is None:
        return (0, "")
    return (1, context)


def _add_to_message_map(
    message_map: dict,
    record: SourceRecord,
) -> None:
    identity = _identity(record.message, record.context)
    entry = message_map.get(identity)
    if entry is None:
        entry = {"locations": set(), "comments": []}
        message_map[identity] = entry
    entry["locations"].add(Location(record.filename, record.lineno, record.method))
    for comment in record.comments:
        if comment not in entry["comments"]:
            entry["comments"].append(comment)


def merge_extraction_results(
    results_a: Iterable[_ExtractionRecord],
    results_b: Iterable[_ExtractionRecord],
    method_a: str = "",
    method_b: str = "",
) -> MergeResult:
    """Merge two sets of extraction records into a single source list.

    The function only consumes the given extraction records; it does not read
    any files or run an extraction itself.

    :param results_a: an iterable of extraction records
                       ``(filename, lineno, message, comments, context)``
    :param results_b: an iterable of extraction records in the same form
    :param method_a: name of the extraction method that produced ``results_a``
                     (recorded on every source of that side)
    :param method_b: name of the extraction method that produced ``results_b``
    :return: a :class:`MergeResult` with deduplicated ``messages`` and a list
             of ``conflicts`` for locations the two sides disagree on

    >>> a = [('a.py', 5, 'hello', [], None)]
    >>> b = [('a.py', 5, 'hello', [], None)]
    >>> result = merge_extraction_results(a, b, 'python', 'javascript')
    >>> len(result.messages)
    1
    >>> [loc.method for loc in result.messages[0].locations]
    ['javascript', 'python']
    >>> result.conflicts
    []
    """
    # Index each side by location, deduplicating same-identity records within
    # one side (duplicate locations collapse to a single source).
    index_a: dict = {}
    index_b: dict = {}

    for record in results_a:
        source = _to_source_record(record, method_a)
        location = (source.filename, source.lineno)
        records = index_a.setdefault(location, [])
        if not any(
            existing.message == source.message and existing.context == source.context
            for existing in records
        ):
            records.append(source)

    for record in results_b:
        source = _to_source_record(record, method_b)
        location = (source.filename, source.lineno)
        records = index_b.setdefault(location, [])
        if not any(
            existing.message == source.message and existing.context == source.context
            for existing in records
        ):
            records.append(source)

    # Build the deduplicated message map.
    message_map: dict = {}
    for records in index_a.values():
        for source in records:
            _add_to_message_map(message_map, source)
    for records in index_b.values():
        for source in records:
            _add_to_message_map(message_map, source)

    # Detect conflicts: locations present on both sides with differing
    # message identities.  Every mismatched pair is reported with both full
    # records; no side is silently picked.
    conflicts: list[Conflict] = []
    common_locations = sorted(set(index_a) & set(index_b))
    for location in common_locations:
        for record_a in index_a[location]:
            for record_b in index_b[location]:
                if _identity(record_a.message, record_a.context) != _identity(
                    record_b.message,
                    record_b.context,
                ):
                    conflicts.append(
                        Conflict(
                            location[0],
                            location[1],
                            record_a,
                            record_b,
                        ),
                    )

    # Assemble the sorted message list.  Sorting is stable by the earliest
    # source location, then by message identity.
    messages: list[MergedMessage] = []
    for identity, entry in message_map.items():
        message, context = identity
        locations = sorted(entry["locations"])
        messages.append(
            MergedMessage(
                message=message,
                context=context,
                locations=locations,
                comments=list(entry["comments"]),
            ),
        )

    def _sort_key_for_message(item: MergedMessage) -> tuple:
        first = item.locations[0]
        return (
            first.filename,
            first.lineno,
            _message_sort_key(item.message),
            _context_sort_key(item.context),
        )

    messages.sort(key=_sort_key_for_message)
    conflicts.sort(key=lambda conflict: (conflict.filename, conflict.lineno))

    return MergeResult(messages=messages, conflicts=conflicts)
