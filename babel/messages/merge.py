"""Merge multiple Babel extraction result listings into one source list.

This module *only consumes existing extraction records*; it never re-reads
source files or re-runs extractors.

Records may be supplied as:

* :class:`ExtractionRecord` instances,
* mappings with the keys ``filename``, ``lineno``, ``message`` and
  optionally ``context`` (default ``None``) and ``method``,
* plain Babel extraction tuples of the form
  ``(filename, lineno, message, comments, context)`` as produced by
  :func:`babel.messages.extract.extract_from_dir`; for these the extractor
  method name is taken from the per-list ``methods`` argument.

Merging rules:

* Records are deduplicated by message identity: the message id (for plural
  messages the *complete* plural tuple), the context (``None`` and ``""``
  are distinct identities) and the plural/singular kind.
* Every distinct source -- ``(normalized path, lineno, method)`` -- is
  preserved on the merged entry; identical sources collapse into one.
* If one position (normalized path + line number) is reported with
  *different* message identities by *different* extraction methods, the
  position is a conflict: no side is picked, the records are withheld from
  the merged list and reported separately, keeping both sides' records.
* Output is stably ordered by normalized relative path, line number and
  message identity.  Paths are normalized to POSIX-style relative paths
  (Windows separators become forward slashes).

Example
-------

>>> from babel.messages.merge import merge_extraction_results
>>> python_run = [
...     ("a.py", 5, "Hello", [], None),
...     ("b.py", 3, ("apple", "apples"), [], None),
... ]
>>> js_run = [
...     ("a.py", 5, "Hello", [], None),  # same message, other extractor
...     ("b.py", 7, "Bye", [], "button"),
... ]
>>> result = merge_extraction_results(
...     python_run, js_run, methods=("python", "javascript"))
>>> for entry in result.entries:
...     print(entry.message, entry.context, sorted(entry.sources))
Hello None [Source(path='a.py', lineno=5, method='javascript'), Source(path='a.py', lineno=5, method='python')]
('apple', 'apples') None [Source(path='b.py', lineno=3, method='python')]
Bye button [Source(path='b.py', lineno=7, method='javascript')]
>>> result.conflicts
()
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, NamedTuple, Sequence

__all__ = [
    "ExtractionConflict",
    "ExtractionRecord",
    "MergeResult",
    "MergedEntry",
    "Source",
    "merge_extraction_results",
    "normalize_path",
]

_UNKNOWN_METHOD = "unknown"
_WINDOWS_SEP = chr(92)  # the Windows path separator


class Source(NamedTuple):
    """One origin of a merged message: file, line and extractor method."""

    path: str  # normalized, relative, POSIX-style separators
    lineno: int
    method: str


@dataclass(frozen=True)
class ExtractionRecord:
    """A single normalized extraction record.

    ``message`` is the message id: a string, or a tuple of strings for
    plural messages (the full tuple is part of the message identity).
    ``context`` is ``None`` when no context was extracted; an empty string
    is a distinct, valid context.
    """

    filename: str
    lineno: int
    message: "str | tuple[str, ...]"
    context: "str | None" = None
    method: str = _UNKNOWN_METHOD
    comments: "tuple[str, ...]" = ()


@dataclass(frozen=True)
class MergedEntry:
    """A deduplicated message with all of its sources."""

    message: "str | tuple[str, ...]"
    context: "str | None"
    sources: "tuple[Source, ...]" = field(default_factory=tuple)


@dataclass(frozen=True)
class ExtractionConflict:
    """Records from disagreeing extractors for one position.

    The records of *all* sides are kept; neither is preferred.
    """

    path: str  # normalized, relative, POSIX-style separators
    lineno: int
    records: "tuple[ExtractionRecord, ...]" = field(default_factory=tuple)


@dataclass(frozen=True)
class MergeResult:
    """Outcome of :func:`merge_extraction_results`."""

    entries: "tuple[MergedEntry, ...]" = ()
    conflicts: "tuple[ExtractionConflict, ...]" = ()


def normalize_path(path: "str | Any") -> str:
    """Normalize a path to a relative, POSIX-style form.

    Windows separators are unified so that ``dir/a.py`` written with
    either separator identifies the same position.
    """
    normalized = posixpath.normpath(str(path).replace(_WINDOWS_SEP, "/"))
    if normalized == ".":
        return ""
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _message_parts(message: Any) -> "tuple[bool, tuple[str, ...]]":
    """Split a message into (is_plural, full plural/singular identity)."""
    if isinstance(message, (tuple, list)):
        return True, tuple(str(part) for part in message)
    return False, (str(message),)


def _identity_key(record: ExtractionRecord) -> tuple:
    """Message identity: plural kind, complete message, exact context.

    ``None`` (no context) and ``""`` (empty context) deliberately remain
    different identities.
    """
    is_plural, parts = _message_parts(record.message)
    if record.context is None:
        context_key = (0, "")
    else:
        context_key = (1, record.context)
    return (is_plural, parts, context_key)


def _coerce_record(item: Any, default_method: str) -> ExtractionRecord:
    if isinstance(item, ExtractionRecord):
        return item
    if isinstance(item, Mapping):
        message = item["message"]
        if isinstance(message, list):
            message = tuple(message)
        return ExtractionRecord(
            filename=str(item["filename"]),
            lineno=int(item["lineno"]),
            message=message,
            context=item.get("context"),
            method=str(item.get("method") or default_method),
            comments=tuple(item.get("comments") or ()),
        )
    if isinstance(item, (tuple, list)) and len(item) == 5:
        # (filename, lineno, message, comments, context) as yielded by
        # babel.messages.extract.extract_from_dir
        filename, lineno, message, comments, context = item
        if isinstance(message, list):
            message = tuple(message)
        return ExtractionRecord(
            filename=str(filename),
            lineno=int(lineno),
            message=message,
            context=context,
            method=default_method,
            comments=tuple(comments or ()),
        )
    raise TypeError(
        "unsupported extraction record: %r; expected ExtractionRecord, "
        "mapping, or (filename, lineno, message, comments, context) tuple"
        % (item,),
    )


def merge_extraction_results(
    *result_sets: Iterable[Any],
    methods: "Sequence[str] | None" = None,
) -> MergeResult:
    """Merge two or more extraction result listings into one source list.

    :param result_sets: iterables of extraction records (see module
        docstring for accepted shapes).  The inputs are only read, never
        mutated, and no files are re-extracted.
    :param methods: optional extractor method names, one per result set,
        used for plain Babel tuples and mapping records without an
        explicit ``method`` key.
    :return: a :class:`MergeResult` with deduplicated ``entries`` and
        cross-extractor ``conflicts``, both stably ordered by normalized
        relative path, line number and message identity.
    """
    if methods is None:
        methods = tuple(_UNKNOWN_METHOD for _ in result_sets)
    elif len(methods) != len(result_sets):
        raise ValueError("methods must have one entry per result set")

    # position -> list of records (insertion order preserved per position)
    positions: "dict[tuple[str, int], list[ExtractionRecord]]" = {}
    for result_set, default_method in zip(result_sets, methods):
        for item in result_set:
            record = _coerce_record(item, default_method)
            key = (normalize_path(record.filename), record.lineno)
            positions.setdefault(key, []).append(record)

    entries: "list[tuple[tuple, MergedEntry]]" = []
    conflicts: "list[ExtractionConflict]" = []

    for (path, lineno), records in positions.items():
        identities = {_identity_key(record) for record in records}
        methods_at_position = {record.method for record in records}
        if len(identities) > 1 and len(methods_at_position) > 1:
            # Different extractors disagree about the message at this
            # position: report both sides, pick neither.
            side_records = tuple(
                sorted(records, key=lambda r: (r.method, _identity_key(r))),
            )
            conflicts.append(
                ExtractionConflict(path=path, lineno=lineno, records=side_records),
            )
            continue

        # identity -> merged sources (deduplicated)
        by_identity: "dict[tuple, dict[str, Any]]" = {}
        for record in records:
            identity = _identity_key(record)
            bucket = by_identity.setdefault(
                identity, {"record": record, "sources": {}},
            )
            source = Source(path=path, lineno=lineno, method=record.method)
            bucket["sources"].setdefault(source, source)

        for identity, bucket in by_identity.items():
            record = bucket["record"]
            sources = tuple(sorted(bucket["sources"]))
            sort_key = (path, lineno, identity)
            entries.append(
                (
                    sort_key,
                    MergedEntry(
                        message=record.message,
                        context=record.context,
                        sources=sources,
                    ),
                ),
            )

    entries.sort(key=lambda item: item[0])
    conflicts.sort(key=lambda conflict: (conflict.path, conflict.lineno))
    return MergeResult(
        entries=tuple(entry for _, entry in entries),
        conflicts=tuple(conflicts),
    )
