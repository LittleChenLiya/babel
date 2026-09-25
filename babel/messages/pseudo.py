"""
    babel.messages.pseudo
    ~~~~~~~~~~~~~~~~~~~~~

    Pseudo-localization support for message catalogs.

    Pseudo-localization transforms source messages into deterministic
    "fake translations" so that user interfaces can be checked for
    length/expansion problems and interpolation errors before real
    translations are available.

    The transformation:

    * maps Latin letters to accented look-alikes using a fixed,
      deterministic table,
    * expands plain text by a configurable ratio with deterministic
      padding (driven by a fixed seed),
    * wraps every message in boundary markers (U+27E6/U+27E7),
    * keeps python-format and brace-format placeholders (including
      nested width fields and escaped percent signs) intact and
      parseable,
    * keeps HTML tags, entities and attributes untouched, transforming
      only text nodes,
    * transforms plural branches independently,
    * is idempotent: messages already carrying boundary markers are
      returned unchanged.

    :copyright: (c) 2013-2025 by the Babel Team.
    :license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

import random
import re
import string
from html.parser import HTMLParser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from babel.messages.catalog import Catalog

#: Boundary markers placed around every pseudo-localized message.
MARKER_START = "⟦"  # ⟦
MARKER_END = "⟧"  # ⟧

#: Default expansion ratio (30%).
DEFAULT_EXPANSION = 0.3

#: Default seed for the deterministic expansion padding.
DEFAULT_SEED = 0

#: Deterministic mapping of Latin letters to accented look-alikes.
_CHAR_MAP = str.maketrans({
    "a": "à", "b": "ƀ", "c": "ç", "d": "ð", "e": "è", "f": "ƒ",
    "g": "ĝ", "h": "ĥ", "i": "î", "j": "ĵ", "k": "ķ", "l": "ļ",
    "m": "ṃ", "n": "ñ", "o": "ö", "p": "ƥ", "q": "ǫ", "r": "ŕ",
    "s": "ŝ", "t": "ţ", "u": "ü", "v": "ṽ", "w": "ŵ", "x": "ẋ",
    "y": "ÿ", "z": "ẑ",
    "A": "À", "B": "Ɓ", "C": "Ç", "D": "Ð", "E": "È", "F": "Ƒ",
    "G": "Ĝ", "H": "Ĥ", "I": "Î", "J": "Ĵ", "K": "Ķ", "L": "Ļ",
    "M": "Ṁ", "N": "Ñ", "O": "Ö", "P": "Ƥ", "Q": "Ǫ", "R": "Ŕ",
    "S": "Ŝ", "T": "Ţ", "U": "Ü", "V": "Ṽ", "W": "Ŵ", "X": "Ẋ",
    "Y": "Ÿ", "Z": "Ẑ",
})

#: Characters used for deterministic expansion padding.
_FILLER_CHARS = "àèìòùåçê"

#: python-format placeholders: %s, %(name)s, %05.2f, %%, ...
_PYTHON_FORMAT_RE = re.compile(
    r"""
    %
    (?:\([^)]+\))?          # optional mapping key: %(name)
    [#0\- +]*               # conversion flags
    (?:\*|\d+)?             # minimum field width
    (?:\.(?:\*|\d+))?       # precision
    [hlL]?                  # length modifier
    [diouxXeEfFgGcrsa%]     # conversion type (%% is the escaped percent)
    """,
    re.VERBOSE,
)

#: brace-format placeholders, including escaped braces ({{ / }}) and
#: one level of nested fields in the format spec ({name:{width}}).
_BRACE_FORMAT_RE = re.compile(
    r"\{\{|\}\}|\{(?:[^{}]|\{[^{}]*\})*\}",
)

#: Heuristic to detect HTML content in a message.
_HTML_RE = re.compile(r"</?[a-zA-Z][^>]*>|&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);")

_PLACEHOLDER_RE = re.compile(
    _PYTHON_FORMAT_RE.pattern + "|" + _BRACE_FORMAT_RE.pattern,
    re.VERBOSE,
)


class PseudoTransformError(Exception):
    """Raised when a single message cannot be pseudo-localized."""


def is_marked(text: str) -> bool:
    """Check whether *text* already carries pseudo-localization markers."""
    stripped = text.strip()
    return stripped.startswith(MARKER_START) and stripped.endswith(MARKER_END)


def _expand_segment(segment: str, expansion: float, rng: random.Random) -> str:
    """Map characters and append deterministic padding to a literal segment."""
    mapped = segment.translate(_CHAR_MAP)
    pad_length = int(round(len(segment) * expansion))
    if pad_length > 0:
        padding = "".join(rng.choice(_FILLER_CHARS) for _ in range(pad_length))
        return f"{mapped} {padding}"
    return mapped


def _transform_literal(text: str, expansion: float, seed: int) -> str:
    """Transform plain text, keeping format placeholders intact."""
    if not text:
        return text
    rng = random.Random(f"babel-pseudo:{seed}:{text}")
    parts: list[str] = []
    pos = 0
    for match in _PLACEHOLDER_RE.finditer(text):
        if match.start() > pos:
            parts.append(_expand_segment(text[pos:match.start()], expansion, rng))
        parts.append(match.group(0))
        pos = match.end()
    if pos < len(text):
        parts.append(_expand_segment(text[pos:], expansion, rng))
    return "".join(parts)


class _PseudoHTMLParser(HTMLParser):
    """Transform only text nodes; keep tags, attributes and entities."""

    def __init__(self, expansion: float, seed: int) -> None:
        super().__init__(convert_charrefs=False)
        self.expansion = expansion
        self.seed = seed
        self.parts: list[str] = []
        self._tag_stack: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(_transform_literal(data, self.expansion, self.seed))

    def handle_starttag(self, tag: str, attrs) -> None:
        self.parts.append(self.get_starttag_text())
        self._tag_stack.append(tag)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        if not self._tag_stack or self._tag_stack[-1] != tag:
            raise PseudoTransformError(
                f"mismatched HTML end tag </{tag}>",
            )
        self._tag_stack.pop()
        self.parts.append(f"</{tag}>")

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.parts.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self.parts.append(f"<?{data}>")

    def close(self) -> None:
        super().close()
        if self._tag_stack:
            raise PseudoTransformError(
                f"unclosed HTML tag(s): {', '.join(self._tag_stack)}",
            )


def looks_like_html(text: str) -> bool:
    """Heuristically detect whether *text* contains HTML markup."""
    return bool(_HTML_RE.search(text))


def pseudo_transform(
    text: str,
    expansion: float = DEFAULT_EXPANSION,
    seed: int = DEFAULT_SEED,
    html: bool | None = None,
) -> str:
    """Pseudo-localize a single message string.

    :param text: the source message.
    :param expansion: ratio by which plain text is expanded (0.3 = 30%).
    :param seed: seed for the deterministic expansion padding.
    :param html: True to force HTML handling, False to disable it,
                 None to auto-detect markup.
    :return: the pseudo-localized message, wrapped in boundary markers.
    :raises PseudoTransformError: if the message contains malformed HTML.
    """
    if not text:
        return text
    if is_marked(text):
        return text
    if html is None:
        html = looks_like_html(text)
    if html:
        parser = _PseudoHTMLParser(expansion, seed)
        try:
            parser.feed(text)
            parser.close()
        except PseudoTransformError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise PseudoTransformError(str(exc)) from exc
        body = "".join(parser.parts)
    else:
        body = _transform_literal(text, expansion, seed)
    return f"{MARKER_START}{body}{MARKER_END}"


def pseudo_transform_string(
    string_value,
    expansion: float = DEFAULT_EXPANSION,
    seed: int = DEFAULT_SEED,
    html: bool | None = None,
):
    """Pseudo-localize a message string, transforming plural branches
    independently when given a tuple."""
    if isinstance(string_value, (list, tuple)):
        return tuple(
            pseudo_transform(branch, expansion=expansion, seed=seed, html=html)
            for branch in string_value
        )
    return pseudo_transform(string_value, expansion=expansion, seed=seed, html=html)


def pseudo_localize_catalog(
    catalog: Catalog,
    expansion: float = DEFAULT_EXPANSION,
    seed: int = DEFAULT_SEED,
    html: bool | None = None,
) -> list:
    """Pseudo-localize every message in *catalog* in place.

    Messages without a translation yet use their message ID as the
    transformation source, so pseudo-localization works directly on
    freshly extracted POT templates.

    Each message is processed independently: a message that fails to
    transform (for example because of malformed HTML) is left unchanged
    and reported in the returned error list, without affecting the rest
    of the catalog.

    :return: a list of (message_id, error) tuples for failed messages.
    """
    errors = []
    # Iterate the private message mapping directly: the public iterator
    # also yields a generated header message, which requires locale data
    # and is never a translation target anyway.
    for message in catalog._messages.values():
        if not message.id:
            continue
        source = message.string
        if not source or (isinstance(source, (list, tuple)) and not any(source)):
            source = message.id
        try:
            message.string = pseudo_transform_string(
                source, expansion=expansion, seed=seed, html=html,
            )
        except PseudoTransformError as exc:
            errors.append((message.id, str(exc)))
    return errors


def sample_values(text: str) -> dict:
    """Build deterministic sample interpolation values for a message.

    Useful for smoke-testing that a pseudo-localized message can still
    be formatted with real values.
    """
    values = {}
    formatter = string.Formatter()
    pending = [text]
    while pending:
        for _, field_name, format_spec, _ in formatter.parse(pending.pop()):
            if field_name:
                root = re.split(r"[.[]", field_name, maxsplit=1)[0]
                if not root.isdigit():
                    values.setdefault(root, _sample_value_for(root))
            if format_spec:
                pending.append(format_spec)
    for match in _PYTHON_FORMAT_RE.finditer(text):
        token = match.group(0)
        key = re.match(r"%\(([^)]+)\)", token)
        if key:
            values.setdefault(key.group(1), _sample_value_for(key.group(1)))
    return values


def _sample_value_for(name: str):
    lowered = name.lower()
    if lowered in {
        "count", "n", "num", "number", "total", "amount", "qty", "quantity",
        "width", "precision", "size", "len", "length",
    }:
        return 3
    if lowered == "name":
        return "Li"
    return "Sample"


def interpolate_sample(text: str) -> str:
    """Interpolate *text* with deterministic sample values.

    Tries brace-format first, then python-format; returns the result of
    the first strategy that applies, or raises the encountered error.
    """
    values = sample_values(text)
    errors = []
    if "{" in text:
        try:
            return text.format(**values)
        except Exception as exc:
            errors.append(exc)
    if "%" in text:
        try:
            return text % values
        except Exception as exc:
            errors.append(exc)
    if errors:
        raise errors[0]
    return text
