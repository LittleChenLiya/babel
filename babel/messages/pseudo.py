"""
babel.messages.pseudo
~~~~~~~~~~~~~~~~~~~~~

Pseudo-localization support for message catalogs.

Pseudo-localization transforms the messages of a catalog into
deterministic "fake translations" so that user interfaces can be
checked for length problems and interpolation errors without real
translations being available.

The transformation:

* replaces Latin letters with accented look-alikes using a fixed
  mapping (non-Latin text is passed through unchanged),
* expands the text by a configurable ratio using deterministic
  filler characters derived from a fixed seed,
* wraps every message in boundary markers (U+27E6 and U+27E7)
  so truncated or concatenated messages are easy to spot,
* keeps python-format and python-brace-format placeholders
  (including nested width fields such as {value:{width}}) and
  escapes (%%, {{, }}) intact and parseable,
* keeps tags, entities and attributes of messages flagged as HTML
  intact, transforming only text nodes,
* transforms each plural branch of a message separately,
* is idempotent: messages that already carry boundary markers are
  returned unchanged.

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from html.parser import HTMLParser

#: Boundary markers placed around every pseudo-localized message.
START_MARKER = '⟦'
END_MARKER = '⟧'

#: Default ratio by which plain text is expanded.
DEFAULT_EXPANSION = 0.3

#: Fixed default seed, so output is reproducible between runs.
DEFAULT_SEED = 0xBA5E1

#: Flags that mark a message as containing HTML.
HTML_FLAGS = frozenset({'html', 'html-format'})

#: Deterministic accent mapping for Latin letters.  Characters not in
#: this table (digits, punctuation, non-Latin scripts) pass through.
_ACCENT_MAP = str.maketrans(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
    'àƀçðéƒĝĥîĵķľṁñóƥɋŕşţúṽŵẋýžÀƁÇÐÉƑĜĤÎĴĶĿṀÑÓƤɊŔŞŢÚṼŴẊÝŽ',
)

#: Characters used to pad messages to the requested expansion ratio.
#: They are wide on purpose to make length problems visible.
_FILLER_CHARS = '～〜﹏的一是不了人我在有'

#: A python-format conversion, e.g. %(name)s, %05.2f or %%.
_PY_FORMAT_RE = re.compile(
    r"""
    %
    (?:\([^)]*\))?        # mapping key, e.g. (name)
    [#0\- +]*             # conversion flags
    (?:\*|\d+)?           # minimum field width
    (?:\.(?:\*|\d+))?     # precision
    [hlL]?                # length modifier
    [diouxXeEfFgGcrsa%]   # conversion type (%% is a literal percent)
""",
    re.VERBOSE,
)


class PseudoLocalizationError(Exception):
    """Raised when a single message cannot be pseudo-localized."""


def _split_brace_format(text):
    """Split *text* into (is_placeholder, segment) pairs.

    Understands python-brace-format replacement fields, including
    nested replacement fields in the format spec (e.g. nested width
    fields such as {value:{width}.{precision}f}) and the {{ / }}
    escapes.  Unbalanced braces are treated as literal text.
    """
    literal = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == '{':
            if text[index : index + 2] == '{{':
                literal.append('{{')
                index += 2
                continue
            depth = 1
            end = index + 1
            while end < length and depth:
                if text[end] == '{':
                    depth += 1
                elif text[end] == '}':
                    depth -= 1
                end += 1
            if depth:  # unbalanced opening brace: keep the rest literal
                literal.append(text[index:])
                index = length
                continue
            if literal:
                yield False, ''.join(literal)
                literal = []
            yield True, text[index:end]
            index = end
        elif char == '}' and text[index : index + 2] == '}}':
            literal.append('}}')
            index += 2
        else:
            literal.append(char)
            index += 1
    if literal:
        yield False, ''.join(literal)


def _split_python_format(text):
    """Split *text* into (is_placeholder, segment) pairs.

    Understands python-format conversions such as %(name)s and the %%
    escape.  Percent signs that do not start a valid conversion are
    treated as literal text.
    """
    position = 0
    for match in _PY_FORMAT_RE.finditer(text):
        if match.start() > position:
            yield False, text[position : match.start()]
        yield True, match.group(0)
        position = match.end()
    if position < len(text):
        yield False, text[position:]


class _PseudoHTMLParser(HTMLParser):
    """Rebuilds HTML verbatim, transforming only text nodes."""

    def __init__(self, transform):
        super().__init__(convert_charrefs=False)
        self._transform = transform
        self.parts = []

    def handle_starttag(self, tag, attrs):
        self.parts.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        self.parts.append('</%s>' % tag)

    def handle_data(self, data):
        self.parts.append(self._transform(data))

    def handle_entityref(self, name):
        self.parts.append('&%s;' % name)

    def handle_charref(self, name):
        self.parts.append('&#%s;' % name)

    def handle_comment(self, data):
        self.parts.append('<!--%s-->' % data)

    def handle_decl(self, decl):
        self.parts.append('<!%s>' % decl)

    def handle_pi(self, data):
        self.parts.append('<?%s>' % data)

    def unknown_decl(self, data):
        self.parts.append('<![%s]>' % data)


class PseudoLocalizer:
    """Deterministically pseudo-localize message strings.

    :param expansion: ratio by which plain text is expanded with filler
                      characters (0.3 means roughly 30% longer)
    :param seed: fixed seed selecting the filler characters; identical
                 input, expansion and seed always produce identical
                 output
    :param start_marker: boundary marker prepended to every message
    :param end_marker: boundary marker appended to every message
    """

    def __init__(
        self,
        expansion=DEFAULT_EXPANSION,
        seed=DEFAULT_SEED,
        start_marker=START_MARKER,
        end_marker=END_MARKER,
    ):
        if expansion < 0:
            raise ValueError('expansion must not be negative')
        self.expansion = float(expansion)
        self.seed = seed
        self.start_marker = start_marker
        self.end_marker = end_marker

    def is_marked(self, text):
        """Check whether *text* already carries the boundary markers."""
        return text.startswith(self.start_marker) and text.endswith(self.end_marker)

    def localize(self, text, *, html=False):
        """Pseudo-localize a single message string.

        Already localized (marked) text is returned unchanged, so
        repeated processing is idempotent.

        :param text: the message to transform
        :param html: treat the message as HTML, transforming only text
                     nodes and keeping tags, entities and attributes
        """
        if not isinstance(text, str):
            raise PseudoLocalizationError(f'cannot pseudo-localize non-string {text!r}')
        if not text or self.is_marked(text):
            return text
        if html:
            return self._localize_html(text)
        return self._localize_plain(text)

    def localize_message(self, message, *, html=None):
        """Pseudo-localize the translation of a catalog message in place.

        Each plural branch is transformed separately.  The message flags
        are consulted to decide whether HTML must be preserved unless
        *html* is given explicitly.

        Untranslated messages (empty msgstr) are pseudo-localized
        from their message ID, so the command is useful on POT files
        and untranslated PO files alike.
        """
        if html is None:
            html = bool(message.flags & HTML_FLAGS)
        ids = message.id if isinstance(message.id, (list, tuple)) else (message.id,)
        strings = message.string
        if isinstance(strings, (list, tuple)):
            message.string = type(strings)(
                self.localize(
                    string or ids[min(index, len(ids) - 1)],
                    html=html,
                )
                for index, string in enumerate(strings)
            )
        else:
            message.string = self.localize(strings or message.id, html=html)
        return message

    def localize_catalog(self, catalog, *, html=None):
        """Pseudo-localize every translated message of *catalog* in place.

        Errors are reported independently: a message that fails keeps
        its original string and is returned, together with the error,
        in the result list; all other messages are still processed.
        """
        errors = []
        for message in catalog:
            if not message.id:
                continue  # the header entry
            try:
                self.localize_message(message, html=html)
            except Exception as error:  # reported, not raised
                errors.append((message, error))
        return errors

    def _localize_plain(self, text):
        parts = []
        plain_length = 0
        for is_placeholder, segment in self._split_placeholders(text):
            if is_placeholder:
                parts.append(segment)
            else:
                plain_length += len(segment)
                parts.append(segment.translate(_ACCENT_MAP))
        body = ''.join(parts)
        return self._wrap(text, body, plain_length)

    def _localize_html(self, text):
        counter = _LengthCounter()
        parser = _PseudoHTMLParser(
            lambda data: counter.counted(data.translate(_ACCENT_MAP), data),
        )
        try:
            parser.feed(text)
            parser.close()
        except Exception as error:
            raise PseudoLocalizationError(
                f'cannot pseudo-localize HTML {text!r}: {error}',
            ) from error
        return self._wrap(text, ''.join(parser.parts), counter.length)

    def _split_placeholders(self, text):
        # A message is python-format, brace-format, or plain; scanning
        # with both splitters is safe because each only treats valid
        # placeholder syntax as placeholders.
        for is_placeholder, segment in _split_python_format(text):
            if is_placeholder:
                yield True, segment
            else:
                yield from _split_brace_format(segment)

    def _wrap(self, source, body, plain_length):
        filler = self._filler(source, plain_length)
        return f'{self.start_marker}{body}{filler}{self.end_marker}'

    def _filler(self, source, plain_length):
        count = round(plain_length * self.expansion)
        if count <= 0:
            return ''
        digest = hashlib.sha256(f'{self.seed}:{source}'.encode('utf-8')).digest()
        return ''.join(
            _FILLER_CHARS[digest[index % len(digest)] % len(_FILLER_CHARS)]
            for index in range(count)
        )


class _LengthCounter:
    """Counts the length of the original text nodes while transforming."""

    def __init__(self):
        self.length = 0

    def counted(self, transformed, original):
        self.length += len(original)
        return transformed


def interpolate(message, params):
    """Interpolate *params* into a (pseudo-localized) message.

    Brace-format messages are interpolated with str.format,
    python-format messages with the % operator.
    """
    if '{' in message:
        return message.format(**params)
    if '%' in message:
        return message % params
    return message


def _coerce_param(value):
    for converter in (int, float):
        try:
            return converter(value)
        except ValueError:
            continue
    return value


def main(argv=None):
    """Compare a source message, its pseudo-localization and the
    interpolated result, e.g.::

        python -m babel.messages.pseudo "Hello {name}" name=Li
    """
    parser = argparse.ArgumentParser(
        prog='python -m babel.messages.pseudo',
        description='Pseudo-localize a message and show the interpolated result.',
    )
    parser.add_argument('message', help='the source message to transform')
    parser.add_argument(
        'params',
        nargs='*',
        metavar='name=value',
        help='interpolation parameters',
    )
    parser.add_argument(
        '--html',
        action='store_true',
        help='treat the message as HTML and transform only text nodes',
    )
    parser.add_argument(
        '--expansion',
        type=float,
        default=DEFAULT_EXPANSION,
        help=f'expansion ratio (default: {DEFAULT_EXPANSION})',
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=DEFAULT_SEED,
        help=f'filler seed (default: {DEFAULT_SEED})',
    )
    args = parser.parse_args(argv)

    params = {}
    for item in args.params:
        name, separator, value = item.partition('=')
        if not separator:
            parser.error(f'invalid parameter {item!r}, expected name=value')
        params[name] = _coerce_param(value)

    localizer = PseudoLocalizer(expansion=args.expansion, seed=args.seed)
    pseudo = localizer.localize(args.message, html=args.html)
    print(f'source:        {args.message}')
    print(f'pseudo:        {pseudo}')
    print(f'interpolated:  {interpolate(pseudo, params)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
