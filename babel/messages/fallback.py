"""
babel.messages.fallback
~~~~~~~~~~~~~~~~~~~~~~~

Explicit, directed fallback resolution across message catalogs.

Given a set of catalogs keyed by locale name and an explicit fallback table
describing directed locale edges, this module finds the translation of a
message by walking the graph depth-first in declaration order.  Every locale
is visited at most once, so diamond-shaped graphs are not searched twice.

The resolver does not mutate the catalogs passed to it: it builds an
immutable :class:`CatalogSnapshot` by cloning the messages when it is
constructed.  After a catalog is updated, build a new snapshot (and hence a
new :class:`FallbackResolver`); existing resolvers keep resolving against
the snapshot they were created with.

A typical lookup looks like this::

    >>> from babel.messages import Catalog, Message
    >>> en = Catalog()
    >>> en['hello'] = Message('hello', 'hello world')
    >>> resolver = FallbackResolver({'fr': Catalog(), 'en': en},
    ...                             {'fr': ['en']})
    >>> result = resolver.resolve('fr', 'hello')
    >>> result.found
    True
    >>> result.source_locale
    'en'
    >>> result.text
    'hello world'

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from gettext import c2py
from types import MappingProxyType

from babel.messages.catalog import Catalog, Message, TranslationError
from babel.messages.checkers import python_format

__all__ = [
    "CatalogSnapshot",
    "FallbackGraphError",
    "FallbackResolver",
    "Resolution",
    "SkipRecord",
]

MessageID = str | tuple[str, ...]


def _key_for(
    message_id: MessageID,
    context: str | None,
) -> str | tuple[str, str]:
    """Replicate `Catalog._key_for`: the singular id, plus the context."""
    key = message_id[0] if isinstance(message_id, (list, tuple)) else message_id
    if context is not None:
        key = (key, context)
    return key


def _normalize_id(message_id: MessageID) -> str | tuple[str, ...]:
    if isinstance(message_id, (list, tuple)):
        return tuple(message_id)
    return message_id


@dataclass(frozen=True)
class _LocaleSnapshot:
    """Frozen view of a single catalog as seen during resolution."""

    messages: Mapping[str | tuple[str, str], Message]
    obsolete: frozenset
    num_plurals: int
    plural_expr: str


class CatalogSnapshot:
    """Immutable snapshot of a mapping of locale names to catalogs.

    Every message (including obsolete message keys) and every plural-forms
    declaration is copied when the snapshot is built.  Later changes to the
    source catalogs, their messages, or their flags never reach the snapshot.

    When catalogs change, create a fresh snapshot (and a new
    :class:`FallbackResolver`); snapshots can not be updated in place.

    :param catalogs: mapping of locale names to catalogs
    """

    def __init__(self, catalogs: Mapping[str, Catalog]) -> None:
        locales: dict[str, _LocaleSnapshot] = {}
        for name, catalog in catalogs.items():
            messages: dict[str | tuple[str, str], Message] = {}
            for message in catalog._messages.values():
                messages[_key_for(message.id, message.context)] = message.clone()
            locales[name] = _LocaleSnapshot(
                messages=MappingProxyType(messages),
                obsolete=frozenset(catalog.obsolete),
                num_plurals=catalog.num_plurals,
                plural_expr=catalog.plural_expr,
            )
        self._locales: Mapping[str, _LocaleSnapshot] = MappingProxyType(locales)

    @property
    def locale_names(self) -> tuple[str, ...]:
        """Locale names captured by the snapshot, in declaration order."""
        return tuple(self._locales)

    def __contains__(self, locale: str) -> bool:
        return locale in self._locales

    def __len__(self) -> int:
        return len(self._locales)

    def __repr__(self) -> str:
        return f"<CatalogSnapshot locales={list(self._locales)!r}>"


class FallbackGraphError(ValueError):
    """Raised when a fallback table is structurally invalid.

    All missing references and cycles found in the table are reported at
    once; the error is raised before any message lookup is attempted.

    :ivar missing: locale names referenced by the table that are not in the
                   catalogs
    :ivar cycles: cycles found in the graph, each given as the tuple of
                  locale names that close the loop
    """

    def __init__(
        self,
        missing: Iterable[str],
        cycles: Iterable[Sequence[str]],
    ) -> None:
        self.missing: tuple[str, ...] = tuple(sorted(missing))
        self.cycles: tuple[tuple[str, ...], ...] = tuple(tuple(cycle) for cycle in cycles)
        parts = []
        if self.missing:
            parts.append(
                "fallback table references unknown locales: " + ", ".join(self.missing),
            )
        for cycle in self.cycles:
            parts.append(
                "fallback cycle detected: " + " -> ".join((*cycle, cycle[0])),
            )
        super().__init__("; ".join(parts))


@dataclass(frozen=True)
class SkipRecord:
    """A locale that was visited but could not provide the message.

    :ivar locale: locale name that was skipped
    :ivar reasons: human-readable reasons why the locale was skipped, in the
                   order the checks were performed
    """

    locale: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Resolution:
    """Outcome of a single fallback lookup.

    :ivar found: whether a usable translation was found
    :ivar text: the selected translation, or `None` on a miss
    :ivar source_locale: locale that provided the translation, or `None`
    :ivar plural_index: index of the selected plural form within the source
                        message (`None` for non-plural messages)
    :ivar visited: all locale names visited during the search, in visit order,
                   deduplicated
    :ivar skipped: reasons each visited locale was rejected
    """

    found: bool
    text: str | None
    source_locale: str | None
    plural_index: int | None
    visited: tuple[str, ...]
    skipped: tuple[SkipRecord, ...]
    message_id: MessageID
    context: str | None = field(default=None)
    n: int | float | None = field(default=None)

    def explain(self) -> str:
        """Return a readable multi-line description of the resolution.

        It always names the resolved source (or states that nothing matched),
        lists every locale on the traversed path, and gives the skip reasons
        for every rejected locale.
        """
        subject = f"message id={self.message_id!r}"
        if self.context is not None:
            subject += f" context={self.context!r}"
        if self.n is not None:
            subject += f" n={self.n}"
        lines: list[str] = []
        if self.found:
            lines.append(f"Resolved {subject} from locale '{self.source_locale}'.")
            if self.plural_index is not None:
                lines.append(
                    f"Plural form index {self.plural_index} was selected using the "
                    f"plural rules of the source locale '{self.source_locale}'.",
                )
            lines.append(f"Selected text: {self.text!r}")
        else:
            lines.append(f"No usable translation found for {subject} in any visited locale.")
            lines.append(
                "No fallback text (such as an untranslated English singular) was returned.",
            )
        lines.append(
            "Fallback path visited (each locale at most once): " + " -> ".join(self.visited),
        )
        for record in self.skipped:
            for reason in record.reasons:
                lines.append(f"Skipped locale '{record.locale}': {reason}.")
        return "\n".join(lines)


class FallbackResolver:
    """Resolve messages against catalogs using an explicit fallback table.

    The fallback table maps a locale name to the ordered list of locales it
    may fall back to.  Searches are depth-first, children are expanded in
    declaration order, and each locale is visited at most once.

    The table is validated eagerly: every referenced locale must have a
    catalog, and the graph must be acyclic.  A :class:`FallbackGraphError`
    reporting all problems is raised during construction, before any message
    can be looked up.

    Messages are considered usable only when they are not fuzzy, not
    obsolete, have a non-empty translation, carry the exact requested id
    (including its plural id and context), pass all plural-slot and
    placeholder checks of the catalog that holds them, and provide every
    plural form required by that catalog.  Plural forms from different
    locales are never combined; the selected form is indexed with the
    *source* locale's plural expression, not the requesting locale's.

    Compiled plural expressions are cached per locale for the lifetime of
    this resolver.  The cache never outlives the immutable snapshot passed
    at construction time: after updating a catalog, build a new snapshot and
    a new resolver.

    :param catalogs: either a mapping of locale names to catalogs, or a
                     :class:`CatalogSnapshot` to share between resolvers
    :param fallbacks: mapping of locale names to ordered fallback locales
    """

    def __init__(
        self,
        catalogs: Mapping[str, Catalog] | CatalogSnapshot,
        fallbacks: Mapping[str, Sequence[str]],
    ) -> None:
        if isinstance(catalogs, CatalogSnapshot):
            self.snapshot = catalogs
        else:
            self.snapshot = CatalogSnapshot(catalogs)
        self._fallback_edges: Mapping[str, tuple[str, ...]] = MappingProxyType(
            {locale: tuple(targets) for locale, targets in fallbacks.items()},
        )
        missing = self._find_missing_references()
        cycles = self._find_cycles()
        if missing or cycles:
            raise FallbackGraphError(missing, cycles)
        self._plural_functions: dict[str, object] = {}

    def _find_missing_references(self) -> set[str]:
        missing: set[str] = set()
        for locale, targets in self._fallback_edges.items():
            if locale not in self.snapshot:
                missing.add(locale)
            for target in targets:
                if target not in self.snapshot:
                    missing.add(target)
        return missing

    def _find_cycles(self) -> list[tuple[str, ...]]:
        white, gray, black = 0, 1, 2
        colors = dict.fromkeys(self.snapshot.locale_names, white)
        stack: list[str] = []
        cycles: list[tuple[str, ...]] = []

        def visit(locale: str) -> None:
            colors[locale] = gray
            stack.append(locale)
            for target in self._fallback_edges.get(locale, ()):
                if target not in colors:
                    continue
                if colors[target] == gray:
                    cycles.append(tuple(stack[stack.index(target) :]))
                elif colors[target] == white:
                    visit(target)
            stack.pop()
            colors[locale] = black

        for name in self.snapshot.locale_names:
            if colors[name] == white:
                visit(name)
        return cycles

    def resolve(
        self,
        locale: str,
        message_id: MessageID,
        context: str | None = None,
        n: int | float | None = None,
    ) -> Resolution:
        """Look up `message_id` starting at `locale`.

        :param locale: locale to start the search at
        :param message_id: singular id, or `(singular, plural)` for plural
                           messages; the full id (plus the context) identifies
                           the message
        :param context: message context, if any
        :param n: number used to select the plural form; required for plural
                  messages
        """
        if locale not in self.snapshot:
            raise ValueError(f"unknown start locale {locale!r}")
        visited: list[str] = []
        skipped: list[SkipRecord] = []
        seen: set[str] = set()

        def visit(candidate: str):
            if candidate in seen:
                return None
            seen.add(candidate)
            visited.append(candidate)
            data = self.snapshot._locales[candidate]
            message, reasons = self._inspect(data, message_id, context)
            if message is not None:
                text, plural_index = self._select(data, candidate, message, n)
                return candidate, message, text, plural_index
            skipped.append(SkipRecord(candidate, tuple(reasons)))
            for target in self._fallback_edges.get(candidate, ()):
                result = visit(target)
                if result is not None:
                    return result
            return None

        match = visit(locale)
        common = {
            "message_id": message_id,
            "context": context,
            "n": n,
            "visited": tuple(visited),
            "skipped": tuple(skipped),
        }
        if match is None:
            return Resolution(
                found=False,
                text=None,
                source_locale=None,
                plural_index=None,
                **common,
            )
        source_locale, _message, text, plural_index = match
        return Resolution(
            found=True,
            text=text,
            source_locale=source_locale,
            plural_index=plural_index,
            **common,
        )

    def _inspect(
        self,
        data: _LocaleSnapshot,
        message_id: MessageID,
        context: str | None,
    ) -> tuple[Message | None, list[str]]:
        key = _key_for(message_id, context)
        if key in data.obsolete:
            return None, ["message is marked obsolete"]
        message = data.messages.get(key)
        if message is None:
            return None, ["message is not present in the catalog"]
        if _normalize_id(message.id) != _normalize_id(message_id):
            return None, [
                f"message id does not match the requested full id (stored id: {message.id!r})",
            ]
        reasons: list[str] = []
        if message.fuzzy:
            reasons.append("message is marked fuzzy")
        if message.pluralizable:
            strings = message.string
            if isinstance(strings, str):
                strings = (strings,)
            strings = tuple(strings)
            if len(strings) != data.num_plurals:
                reasons.append(
                    f"incomplete plural slots: the catalog requires "
                    f"{data.num_plurals} forms but the message provides {len(strings)}",
                )
            else:
                for index, text in enumerate(strings):
                    if not text:
                        reasons.append(f"empty translation in plural slot {index}")
        elif not message.string:
            reasons.append("translation is empty")
        try:
            python_format(None, message)
        except TranslationError as error:
            reasons.append(f"placeholder check failed: {error}")
        if reasons:
            return None, reasons
        return message, []

    def _select(
        self,
        data: _LocaleSnapshot,
        locale: str,
        message: Message,
        n: int | float | None,
    ) -> tuple[str, int | None]:
        if not message.pluralizable:
            return message.string, None
        if n is None:
            raise ValueError(
                "n is required to select a plural form of a pluralizable message",
            )
        plural = self._plural_function(locale, data)
        index = plural(n)
        strings = tuple(message.string)
        if not 0 <= index < len(strings):
            raise ValueError(
                f"plural expression of locale {locale!r} selected index {index}, "
                f"but the message only has {len(strings)} forms",
            )
        return strings[index], index

    def _plural_function(self, locale: str, data: _LocaleSnapshot):
        function = self._plural_functions.get(locale)
        if function is None:
            function = c2py(data.plural_expr)
            self._plural_functions[locale] = function
        return function
