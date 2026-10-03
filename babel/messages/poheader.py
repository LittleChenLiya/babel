r"""
babel.messages.poheader
~~~~~~~~~~~~~~~~~~~~~~~

Surgical, in-place editing of PO file header metadata.

The regular :func:`babel.messages.pofile.write_po` always rewrites a whole
catalog, re-wrapping and re-ordering everything in the process.  This module
is for the opposite use case: you only want to change a handful of header
fields (``Language``, ``PO-Revision-Date``, ...) of an existing ``.po`` file
and keep every other byte -- message entries, comments, unknown header
fields, line endings -- exactly as it was.

How it works
------------

1. The file is scanned with the same structural rules the regular PO parser
   uses (keywords ``msgid``/``msgctxt``/``msgid_plural``/``msgstr``,
   ``#`` comments, ``#~`` obsolete entries, ``"..."`` continuation lines),
   so the header message (the message with an empty ``msgid`` and no
   ``msgctxt``) and the exact line range of its ``msgstr`` are located
   reliably instead of by guessing with regular expressions.
2. The ``msgstr`` string literals are decoded with the parser's own
   :func:`~babel.messages.pofile.unescape` and split into RFC-822-style
   ``Name: value`` fields.  Unknown fields keep their relative order.
3. Only the requested fields are replaced (missing fields are appended at
   the end of the header); values are emitted with the parser's own
   :func:`~babel.messages.pofile.escape`, so values containing newlines,
   quotes or tabs come out as valid PO string escapes and the result can be
   read back by :func:`~babel.messages.pofile.read_po`.
4. Only the byte range of the header ``msgstr`` section is spliced; the
   rest of the file -- including its newline style (LF or CRLF) -- is
   preserved byte for byte.

The edit is refused (raising :class:`PoHeaderError`, leaving the input
untouched) when

* the file has no uniquely identifiable header message (none at all, or
  more than one message with an empty ``msgid``),
* the header contains the same field name twice,
* the header ``msgstr`` is malformed or not a contiguous run of lines, or
* a replacement field name is itself invalid.

Usage
-----

>>> from babel.messages.poheader import replace_po_header_fields
>>> data = b'msgid ""\nmsgstr ""\n"Language: de\\n"\n\nmsgid "x"\nmsgstr "y"\n'
>>> new_data = replace_po_header_fields(data, {"Language": "fr"})
>>> b"Language: fr" in new_data
True

There is also a small command line demo which shows the modified line
range (a dry run unless ``--in-place`` is given)::

    python -m babel.messages.poheader locale/fr/LC_MESSAGES/app.po Language=fr

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

import argparse
import codecs
import os
import sys
from collections.abc import Mapping
from typing import NamedTuple

from babel.messages.pofile import escape, unescape

__all__ = [
    "HeaderEdit",
    "PoHeaderError",
    "edit_po_file",
    "edit_po_header",
    "replace_po_header_fields",
]

#: Keywords the PO parser understands at message level.
_KEYWORDS = frozenset({"msgid", "msgid_plural", "msgctxt", "msgstr"})


class PoHeaderError(ValueError):
    """Raised when a PO file header cannot be edited safely in place."""


class _Section:
    """One keyword section (e.g. ``msgstr`` plus its continuation lines)."""

    __slots__ = ("keyword", "lineno", "first_fragment", "continuations")

    def __init__(self, keyword: str, lineno: int, first_fragment: str) -> None:
        self.keyword = keyword
        self.lineno = lineno  # 0-based line number of the keyword line
        self.first_fragment = first_fragment
        # list of (lineno, fragment) for the ``"..."`` continuation lines
        self.continuations: list[tuple[int, str]] = []

    @property
    def fragments(self) -> list[str]:
        return [self.first_fragment, *(frag for _, frag in self.continuations)]

    @property
    def line_numbers(self) -> list[int]:
        return [self.lineno, *(n for n, _ in self.continuations)]


class _Message:
    __slots__ = ("obsolete", "sections")

    def __init__(self) -> None:
        self.obsolete = False
        self.sections: list[_Section] = []


def _scan_messages(lines: list[str]) -> list[_Message]:
    """Split *lines* into messages using the same structural rules as
    :class:`babel.messages.pofile.PoFileParser`.

    Raises :class:`PoHeaderError` for input the parser would flag as
    invalid; editing such a file surgically would not be safe.
    """
    messages: list[_Message] = []
    msg: _Message | None = None
    section: _Section | None = None

    def has_msgid(message: _Message | None) -> bool:
        return message is not None and any(
            s.keyword.partition("[")[0] in ("msgid", "msgid_plural") for s in message.sections
        )

    def finish() -> None:
        nonlocal msg, section
        if msg is not None and msg.sections:
            messages.append(msg)
        msg = None
        section = None

    for lineno, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        obsolete = False
        if stripped.startswith("#"):
            if stripped.startswith("#~"):
                obsolete = True
                stripped = stripped[2:].lstrip()
                if not stripped:
                    continue
            else:
                # A comment terminates the preceding message, but (like in
                # the PO parser) only once a msgid has been seen; a comment
                # between msgctxt and msgid does not split the message.
                if has_msgid(msg):
                    finish()
                continue
        if stripped.startswith('"'):
            if section is None:
                raise PoHeaderError(
                    "string continuation outside of msgid/msgstr/msgctxt "
                    f"on line {lineno + 1}",
                )
            section.continuations.append((lineno, stripped))
            continue
        keyword, _, arg = stripped.partition(" ")
        base_keyword = keyword.partition("[")[0]
        if base_keyword not in _KEYWORDS:
            raise PoHeaderError(
                f"unknown or misformatted keyword {keyword!r} on line {lineno + 1}",
            )
        if base_keyword in ("msgid", "msgctxt"):
            # These keywords terminate the preceding message -- but only
            # when it already has a msgid, mirroring the PO parser, so a
            # msgctxt line stays attached to the msgid that follows it.
            if has_msgid(msg):
                finish()
            if msg is None:
                msg = _Message()
        elif msg is None:
            raise PoHeaderError(
                f"keyword {keyword!r} outside of a message on line {lineno + 1}",
            )
        msg.obsolete = msg.obsolete or obsolete
        section = _Section(keyword, lineno, arg.strip())
        msg.sections.append(section)
    finish()
    return messages


def _unquote(fragment: str, lineno: int) -> str:
    """Decode one PO string literal with the parser's own unescape rules.

    The fragment must be a complete double-quoted string; the closing quote
    is located by honoring backslash escapes, never by grabbing the first
    pair of quotes with a regex.
    """
    if len(fragment) < 2 or not fragment.startswith('"') or not fragment.endswith('"'):
        raise PoHeaderError(f"malformed string literal near line {lineno + 1}")
    # The final quote only closes the string if it is not itself escaped,
    # i.e. it is preceded by an even number of backslashes.
    backslashes = 0
    for char in reversed(fragment[:-1]):
        if char == "\\":
            backslashes += 1
        else:
            break
    if backslashes % 2:
        raise PoHeaderError(f"unterminated string literal near line {lineno + 1}")
    return unescape(fragment)


def _denormalize(fragments: list[str], lineno: int) -> str:
    return "".join(_unquote(fragment, lineno) for fragment in fragments if fragment)


def _is_header_candidate(msg: _Message) -> bool:
    if msg.obsolete:
        return False
    if any(section.keyword == "msgctxt" for section in msg.sections):
        return False
    msgid_sections = [s for s in msg.sections if s.keyword == "msgid"]
    if len(msgid_sections) != 1:
        return False
    section = msgid_sections[0]
    try:
        return _denormalize(section.fragments, section.lineno) == ""
    except PoHeaderError:
        return False


def _detect_charset(header_text: str, default_charset: str) -> str:
    for line in header_text.split("\n"):
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() == "content-type":
            for param in value.split(";"):
                name, eq, val = param.partition("=")
                if eq and name.strip().lower() == "charset" and val.strip():
                    return val.strip()
    return default_charset


class HeaderEdit(NamedTuple):
    """Describes an in-place header edit.

    ``data`` is the new file content; ``start_line`` is the 0-based number
    of the first replaced line; ``old_lines`` and ``new_lines`` are the
    replaced and replacement lines (without line endings), so callers can
    display the exact modified range.
    """

    data: bytes
    start_line: int
    old_lines: tuple[bytes, ...]
    new_lines: tuple[bytes, ...]
    charset: str


def edit_po_header(
    data: bytes,
    replacements: Mapping[str, str],
    *,
    default_charset: str = "utf-8",
) -> HeaderEdit:
    """Replace header fields of a PO file given as ``bytes``.

    ``replacements`` maps header field names (matched case-insensitively,
    like RFC 822 header names) to their new values.  Fields not present in
    the header are appended after the last existing field; all other fields
    keep their relative order.  Values may contain newlines, quotes and
    tabs -- they are emitted with PO string escaping.

    Returns a :class:`HeaderEdit`.  Raises :class:`PoHeaderError` (and
    changes nothing) when the header is not uniquely identifiable, contains
    a duplicate field, or is malformed.
    """
    if not isinstance(data, bytes):
        raise TypeError("edit_po_header() requires the file content as bytes")
    if not replacements:
        # Nothing to do: return the input untouched, byte for byte.
        return HeaderEdit(data, 0, (), (), default_charset)

    for name, value in replacements.items():
        if not name or any(c in name for c in ':\r\n"'):
            raise PoHeaderError(f"invalid header field name {name!r}")
        if not isinstance(value, str):
            raise TypeError(f"replacement value for {name!r} must be str")

    # Split into lines, keeping exact bytes so the file can be reassembled
    # with only the header lines swapped out.
    raw_lines = data.split(b"\n")
    # Decode for structural scanning only; undecodable bytes become
    # surrogates and can be round-tripped losslessly.
    lines = [raw.decode("ascii", "surrogateescape") for raw in raw_lines]

    messages = _scan_messages(lines)
    candidates = [m for m in messages if _is_header_candidate(m)]
    if not candidates:
        raise PoHeaderError("no header message (empty msgid) found")
    if len(candidates) > 1:
        raise PoHeaderError(
            "header message is not unique "
            "(found empty msgid on lines "
            + ", ".join(str(m.sections[0].lineno + 1) for m in candidates)
            + ")",
        )
    header = candidates[0]

    msgstr_sections = [s for s in header.sections if s.keyword == "msgstr"]
    other_sections = [s for s in header.sections if s.keyword not in ("msgid", "msgstr")]
    if other_sections or len(msgstr_sections) != 1:
        raise PoHeaderError("header message is malformed (unexpected keywords)")
    msgstr = msgstr_sections[0]

    line_numbers = msgstr.line_numbers
    if line_numbers != list(range(msgstr.lineno, msgstr.lineno + len(line_numbers))):
        raise PoHeaderError("header msgstr lines are not contiguous; refusing to edit")

    # First pass with surrogate escapes, only to find the declared charset
    # (the charset token itself is plain ASCII).
    rough_text = _denormalize(msgstr.fragments, msgstr.lineno)
    charset = _detect_charset(rough_text, default_charset)
    try:
        codecs.lookup(charset)
    except LookupError:
        raise PoHeaderError(f"unknown charset {charset!r} declared in header") from None

    # Second pass: decode the string literals with the real charset.
    try:
        fragments = [
            fragment.encode("ascii", "surrogateescape").decode(charset)
            for fragment in msgstr.fragments
            if fragment
        ]
        header_text = "".join(_unquote(fragment, msgstr.lineno) for fragment in fragments)
    except UnicodeDecodeError as exc:
        raise PoHeaderError(
            f"header is not decodable with charset {charset!r}: {exc}",
        ) from None

    # Split into fields, keeping empty and otherwise opaque lines in place.
    field_lines = header_text.split("\n")
    trailing_empty = bool(field_lines) and field_lines[-1] == ""
    field_index: dict[str, int] = {}
    for index, field_line in enumerate(field_lines):
        key, sep, _ = field_line.partition(":")
        if not sep or not key.strip():
            continue  # opaque line, preserved as-is
        lowered = key.strip().lower()
        if lowered in field_index:
            raise PoHeaderError(
                f"duplicate header field {key.strip()!r}; refusing to edit",
            )
        field_index[lowered] = index

    for name, value in replacements.items():
        lowered = name.lower()
        if lowered in field_index:
            index = field_index[lowered]
            original_key = field_lines[index].partition(":")[0]
            field_lines[index] = f"{original_key}: {value}"
        else:
            at = len(field_lines) - 1 if trailing_empty else len(field_lines)
            field_lines.insert(at, f"{name}: {value}")

    # Re-emit the msgstr section: `msgstr ""` followed by one continuation
    # line per header line, escaped with the parser's own rules so the
    # result can be read back by read_po.
    out_lines = ['msgstr ""']
    new_text = "\n".join(field_lines)
    parts = new_text.split("\n")
    for i, part in enumerate(parts):
        if i < len(parts) - 1:
            out_lines.append(escape(part + "\n"))
        elif part:
            out_lines.append(escape(part))

    try:
        encoded = [line.encode(charset) for line in out_lines]
    except UnicodeEncodeError as exc:
        raise PoHeaderError(
            f"replacement is not encodable with charset {charset!r}: {exc}",
        ) from None

    # Match the newline style of the section being replaced.
    if raw_lines[msgstr.lineno].endswith(b"\r"):
        encoded = [line + b"\r" for line in encoded]

    start, end = line_numbers[0], line_numbers[-1]
    new_raw_lines = [*raw_lines[:start], *encoded, *raw_lines[end + 1 :]]
    return HeaderEdit(
        data=b"\n".join(new_raw_lines),
        start_line=start,
        old_lines=tuple(raw_lines[start : end + 1]),
        new_lines=tuple(encoded),
        charset=charset,
    )


def replace_po_header_fields(
    data: bytes,
    replacements: Mapping[str, str],
    *,
    default_charset: str = "utf-8",
) -> bytes:
    """Like :func:`edit_po_header`, but returns only the new file content."""
    return edit_po_header(data, replacements, default_charset=default_charset).data


def edit_po_file(
    filename: str | os.PathLike[str],
    replacements: Mapping[str, str],
    *,
    default_charset: str = "utf-8",
) -> HeaderEdit:
    """Edit header fields of a PO file in place.

    The file is only written when the edit succeeds; on :class:`PoHeaderError`
    the file is left untouched, byte for byte.
    """
    with open(filename, "rb") as fileobj:
        data = fileobj.read()
    edit = edit_po_header(data, replacements, default_charset=default_charset)
    if edit.data != data:
        with open(filename, "wb") as fileobj:
            fileobj.write(edit.data)
    return edit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m babel.messages.poheader",
        description=(
            "Replace PO file header fields in place, leaving the rest of "
            "the file byte-identical.  Without --in-place this is a dry run "
            "that only shows the modified line range."
        ),
    )
    parser.add_argument("file", help="the PO file to edit")
    parser.add_argument(
        "fields",
        nargs="+",
        metavar="NAME=VALUE",
        help="header field replacements, e.g. Language=fr",
    )
    parser.add_argument(
        "-i",
        "--in-place",
        action="store_true",
        help="write the result back to the file",
    )
    args = parser.parse_args(argv)

    replacements: dict[str, str] = {}
    for field in args.fields:
        name, sep, value = field.partition("=")
        if not sep:
            parser.error(f"invalid field specification {field!r} (expected NAME=VALUE)")
        replacements[name] = value

    with open(args.file, "rb") as fileobj:
        data = fileobj.read()
    try:
        edit = edit_po_header(data, replacements)
    except PoHeaderError as exc:
        print(f"error: {exc}; {args.file} left unchanged", file=sys.stderr)
        return 1

    end_line = edit.start_line + len(edit.old_lines)
    print(f"@@ {args.file}: header lines {edit.start_line + 1}-{end_line} @@")
    for line in edit.old_lines:
        print("-" + line.rstrip(b"\r").decode(edit.charset, "replace"))
    for line in edit.new_lines:
        print("+" + line.rstrip(b"\r").decode(edit.charset, "replace"))

    if args.in_place:
        if edit.data != data:
            with open(args.file, "wb") as fileobj:
                fileobj.write(edit.data)
        print(f"{args.file}: header updated")
    else:
        print("(dry run; pass --in-place to apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
