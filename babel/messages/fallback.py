"""
    babel.messages.fallback
    ~~~~~~~~~~~~~~~~~~~~~~~

    Per-message translation source resolution along an explicit, directed
    fallback graph.

    A `FallbackResolver` is built from a mapping of locale names to
    `Catalog` instances plus an explicit fallback table.  The graph is
    validated up front (missing catalog references and cycles are
    reported before any message is looked up), and each lookup walks the
    chain in depth-first declaration order, de-duplicating locales, until
    a usable translation is found.

    A message is identified by its context and its full id (the complete
    ``(singular, plural)`` tuple for pluralizable messages).  Messages
    that are fuzzy, obsolete, empty, or fail the catalog's placeholder
    checks are not usable, and plural translations are never spliced
    together from two locales: the selected catalog must provide every
    plural slot its own locale requires, and the winning text is picked
    with the *source* locale's plural rules.

    Caching and snapshots
    ---------------------

    The resolver holds an immutable snapshot of the catalog *mapping*
    and the fallback table (both are copied at construction time), and
    memoizes lookups per resolver instance.  The `Catalog` and
    `Message` objects themselves are shared by reference and are never
    mutated.  If a catalog is updated in place, build a new
    ``FallbackResolver`` (a new snapshot) to pick up the changes; the
    old resolver's cache keeps reflecting the old message objects.

    :copyright: (c) 2013-2025 by the Babel Team.
    :license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Mapping

if TYPE_CHECKING:
    from babel.messages.catalog import Catalog, Message

__all__ = [
    "FallbackCycleError",
    "FallbackError",
    "FallbackResolver",
    "LocaleSkip",
    "MissingCatalogError",
    "Resolution",
]

_MessageIdentity = str | tuple[str, ...]


class FallbackError(Exception):
    """Base class for fallback resolution errors."""


class MissingCatalogError(FallbackError):
    """Raised when the fallback graph references an unknown catalog."""


class FallbackCycleError(FallbackError):
    """Raised when the fallback graph contains a cycle."""


@dataclass(frozen=True)
class LocaleSkip:
    """Records why one locale in the chain did not provide a translation."""

    locale: str
    reason: str


@dataclass(frozen=True)
class Resolution:
    """The outcome of resolving one message through the fallback chain.

    ``found`` is ``False`` for an explicit miss; in that case
    ``source_locale``, ``text`` and ``message`` are ``None``
    and ``diagnostics`` explains, per locale, why nothing was usable.
    No silent default (such as the English singular) is substituted.
    """

    found: bool
    source_locale: str | None
    text: str | None
    message: Message | None
    visited: tuple[str, ...]
    skipped: tuple[LocaleSkip, ...]
    diagnostics: tuple[str, ...]


class FallbackResolver:
    """Resolve messages across catalogs along an explicit fallback graph.

    :param catalogs: mapping of locale name to `Catalog`.  The mapping is
                     copied into an immutable snapshot; the catalogs
                     themselves are shared by reference and never mutated.
    :param fallbacks: mapping of locale name to an iterable of fallback
                      locale names, consulted in declaration order.
    :raises MissingCatalogError: if the graph references a locale that has
                                 no catalog
    :raises FallbackCycleError: if the graph contains a cycle
    """

    def __init__(
        self,
        catalogs: Mapping[str, Catalog],
        fallbacks: Mapping[str, Iterable[str]],
    ) -> None:
        self._catalogs = {str(locale): catalog for locale, catalog in catalogs.items()}
        self._fallbacks = {
            str(locale): tuple(str(target) for target in chain)
            for locale, chain in fallbacks.items()
        }
        self._check_references()
        self._check_cycles()
        self._cache: dict[tuple, Resolution] = {}

    @property
    def catalogs(self) -> Mapping[str, Catalog]:
        """A copy of the resolver's immutable catalog snapshot."""
        return dict(self._catalogs)

    @property
    def fallbacks(self) -> Mapping[str, tuple[str, ...]]:
        """A copy of the resolver's immutable fallback table snapshot."""
        return dict(self._fallbacks)

    def _check_references(self) -> None:
        missing = set()
        for locale, chain in self._fallbacks.items():
            if locale not in self._catalogs:
                missing.add(locale)
            for target in chain:
                if target not in self._catalogs:
                    missing.add(target)
        if missing:
            raise MissingCatalogError(
                "fallback graph references unknown catalog(s): "
                + ", ".join(sorted(missing)),
            )

    def _check_cycles(self) -> None:
        color: dict[str, int] = {}  # 1 = on current path, 2 = done
        for root in self._fallbacks:
            if color.get(root) is not None:
                continue
            color[root] = 1
            path = [root]
            stack = [iter(self._fallbacks.get(root, ()))]
            while stack:
                advanced = False
                for target in stack[-1]:
                    state = color.get(target)
                    if state == 1:
                        cycle = path[path.index(target):] + [target]
                        raise FallbackCycleError(
                            "fallback graph contains a cycle: "
                            + " -> ".join(cycle),
                        )
                    if state is None:
                        color[target] = 1
                        path.append(target)
                        stack.append(iter(self._fallbacks.get(target, ())))
                        advanced = True
                        break
                if not advanced:
                    color[path.pop()] = 2
                    stack.pop()

    def _resolution_order(self, locale: str) -> tuple[str, ...]:
        """Depth-first order over the chain, each locale visited once."""
        order: list[str] = []
        seen: set[str] = set()

        def visit(loc: str) -> None:
            if loc in seen:
                return
            seen.add(loc)
            order.append(loc)
            for target in self._fallbacks.get(loc, ()):
                visit(target)

        visit(locale)
        return tuple(order)

    def resolve(
        self,
        locale: str,
        id: str | tuple[str, ...] | list[str],
        context: str | None = None,
        n: float | None = None,
    ) -> Resolution:
        """Resolve one message, returning a `Resolution`.

        :param locale: the requested locale; its fallback chain is walked
                       in depth-first declaration order
        :param id: the message id, or the full ``(singular, plural)``
                   tuple for pluralizable messages
        :param context: the message context (part of the message identity)
        :param n: the plural count; required when the resolved message is
                  pluralizable.  The *source* locale's plural expression
                  selects the slot, never the requested locale's.
        """
        locale = str(locale)
        norm_id: _MessageIdentity = (
            tuple(id) if isinstance(id, (list, tuple)) else id
        )
        key = (locale, context, norm_id, n)
        if key not in self._cache:
            self._cache[key] = self._resolve(locale, norm_id, context, n)
        return self._cache[key]

    def _resolve(
        self,
        locale: str,
        norm_id: _MessageIdentity,
        context: str | None,
        n: float | None,
    ) -> Resolution:
        order = self._resolution_order(locale)
        visited: list[str] = []
        skipped: list[LocaleSkip] = []
        for loc in order:
            visited.append(loc)
            message, reason = self._candidate(
                self._catalogs[loc], norm_id, context,
            )
            if message is None:
                skipped.append(LocaleSkip(loc, reason))
                continue
            if message.pluralizable:
                if n is None:
                    msg = (
                        f"n is required to resolve plural message {norm_id!r}"
                    )
                    raise ValueError(msg)
                index = _evaluate_plural_expr(
                    self._catalogs[loc].plural_expr, n,
                )
                text = message.string[index]
            else:
                text = message.string
            return Resolution(
                found=True,
                source_locale=loc,
                text=text,
                message=message,
                visited=tuple(visited),
                skipped=tuple(skipped),
                diagnostics=tuple(
                    f"{skip.locale}: {skip.reason}" for skip in skipped
                ),
            )
        if context is None:
            identity = f"id={norm_id!r}"
        else:
            identity = f"context={context!r}, id={norm_id!r}"
        diagnostics = tuple(
            f"{skip.locale}: {skip.reason}" for skip in skipped
        ) + (
            f"no usable translation for {identity} "
            f"in chain {' -> '.join(order)}",
        )
        return Resolution(
            found=False,
            source_locale=None,
            text=None,
            message=None,
            visited=tuple(visited),
            skipped=tuple(skipped),
            diagnostics=diagnostics,
        )

    def _candidate(
        self,
        catalog: Catalog,
        norm_id: _MessageIdentity,
        context: str | None,
    ) -> tuple[Message | None, str]:
        """Return the catalog's message if usable, else a skip reason."""
        key = catalog._key_for(norm_id, context)
        if key in catalog.obsolete:
            return None, "message is obsolete"
        message = catalog.get(norm_id, context)
        if message is None:
            return None, "message not found in catalog"
        message_id = (
            tuple(message.id)
            if isinstance(message.id, (list, tuple))
            else message.id
        )
        if message_id != norm_id:
            return None, f"message id mismatch (catalog holds {message_id!r})"
        if message.fuzzy:
            return None, "message is marked fuzzy"
        if message.pluralizable:
            strings = message.string
            if not isinstance(strings, (list, tuple)):
                strings = (strings,)
            expected = catalog.num_plurals
            if len(strings) != expected:
                return None, (
                    f"incomplete plural slots "
                    f"({len(strings)} of {expected} provided)"
                )
            empty = [i for i, value in enumerate(strings) if not value]
            if empty:
                return None, (
                    "empty plural slot(s): "
                    + ", ".join(str(i) for i in empty)
                )
        elif not message.string or not isinstance(message.string, str):
            return None, "empty translation"
        errors = message.check(catalog)
        if errors:
            return None, (
                "failed checks: " + "; ".join(str(error) for error in errors)
            )
        return message, ""


# --- Gettext plural expression evaluation ---------------------------------

_PLURAL_TOKEN_RE = re.compile(
    r"\s*(?:(?P<number>\d+)|(?P<name>n)|(?P<op>\|\||&&|==|!=|<=|>=|[<>?:()%!]))",
)

_RELATIONAL_OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


def _evaluate_plural_expr(expr: str, n: float) -> int:
    """Evaluate a gettext plural expression (e.g. ``(n != 1)``) for ``n``."""
    tokens = _tokenize_plural_expr(expr.strip())
    value, pos = _parse_ternary(tokens, 0, n)
    if pos != len(tokens):
        msg = f"unexpected trailing tokens in plural expression: {expr!r}"
        raise ValueError(msg)
    return int(value)


def _tokenize_plural_expr(expr: str) -> list[tuple[str, object]]:
    tokens: list[tuple[str, object]] = []
    pos = 0
    while pos < len(expr):
        match = _PLURAL_TOKEN_RE.match(expr, pos)
        if match is None or match.end() == pos:
            msg = f"cannot tokenize plural expression: {expr!r}"
            raise ValueError(msg)
        pos = match.end()
        kind = match.lastgroup
        if kind == "number":
            tokens.append(("number", int(match.group("number"))))
        elif kind == "name":
            tokens.append(("n", None))
        else:
            tokens.append(("op", match.group("op")))
    return tokens


def _peek(tokens: list[tuple[str, object]], pos: int) -> object:
    if pos < len(tokens) and tokens[pos][0] == "op":
        return tokens[pos][1]
    return None


def _expect(tokens: list[tuple[str, object]], pos: int, op: str) -> int:
    if _peek(tokens, pos) != op:
        msg = f"expected {op!r} in plural expression"
        raise ValueError(msg)
    return pos + 1


def _parse_ternary(
    tokens: list[tuple[str, object]], pos: int, n: float,
) -> tuple[object, int]:
    cond, pos = _parse_or(tokens, pos, n)
    if _peek(tokens, pos) == "?":
        then, pos = _parse_ternary(tokens, pos + 1, n)
        pos = _expect(tokens, pos, ":")
        otherwise, pos = _parse_ternary(tokens, pos, n)
        return (then if cond else otherwise), pos
    return cond, pos


def _parse_or(
    tokens: list[tuple[str, object]], pos: int, n: float,
) -> tuple[object, int]:
    value, pos = _parse_and(tokens, pos, n)
    while _peek(tokens, pos) == "||":
        rhs, pos = _parse_and(tokens, pos + 1, n)
        value = 1 if (value or rhs) else 0
    return value, pos


def _parse_and(
    tokens: list[tuple[str, object]], pos: int, n: float,
) -> tuple[object, int]:
    value, pos = _parse_relational(tokens, pos, n)
    while _peek(tokens, pos) == "&&":
        rhs, pos = _parse_relational(tokens, pos + 1, n)
        value = 1 if (value and rhs) else 0
    return value, pos


def _parse_relational(
    tokens: list[tuple[str, object]], pos: int, n: float,
) -> tuple[object, int]:
    value, pos = _parse_modulo(tokens, pos, n)
    while _peek(tokens, pos) in _RELATIONAL_OPS:
        op = tokens[pos][1]
        rhs, pos = _parse_modulo(tokens, pos + 1, n)
        value = 1 if _RELATIONAL_OPS[op](value, rhs) else 0
    return value, pos


def _parse_modulo(
    tokens: list[tuple[str, object]], pos: int, n: float,
) -> tuple[object, int]:
    value, pos = _parse_unary(tokens, pos, n)
    while _peek(tokens, pos) == "%":
        rhs, pos = _parse_unary(tokens, pos + 1, n)
        value = value % rhs
    return value, pos


def _parse_unary(
    tokens: list[tuple[str, object]], pos: int, n: float,
) -> tuple[object, int]:
    if _peek(tokens, pos) == "!":
        value, pos = _parse_unary(tokens, pos + 1, n)
        return (0 if value else 1), pos
    return _parse_atom(tokens, pos, n)


def _parse_atom(
    tokens: list[tuple[str, object]], pos: int, n: float,
) -> tuple[object, int]:
    if pos >= len(tokens):
        msg = "unexpected end of plural expression"
        raise ValueError(msg)
    kind, value = tokens[pos]
    if kind == "number":
        return value, pos + 1
    if kind == "n":
        return n, pos + 1
    if value == "(":
        result, pos = _parse_ternary(tokens, pos + 1, n)
        return result, _expect(tokens, pos, ")")
    msg = f"unexpected token {value!r} in plural expression"
    raise ValueError(msg)
