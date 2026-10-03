"""
babel.messages.pofile_header
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Editor for gettext PO file headers that preserves the body text.

When only a few metadata headers of a PO file need to change, re-writing
the whole catalog through :func:`~babel.messages.pofile.write_po` would
re-flow every message and destroy the original formatting of the body.
This module provides :func:`edit_po_header`, which uses the existing PO
parsing rules (see :class:`~babel.messages.pofile.PoFileParser`) to locate
the header message and its continuation lines, then replaces only the
specified header fields while leaving every other byte of the file
untouched.

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

import os

from babel.messages.catalog import Catalog
from babel.messages.pofile import PoFileParser, escape, unescape


class HeaderEditError(Exception):
    """Exception raised when a PO file header cannot be edited.

    This is raised in the following situations:

    * the input does not contain a uniquely identifiable header message
      (``msgid ""``),
    * a header field to replace appears more than once (duplicate field),
    * the input is not a valid PO file.
    """


class _HeaderFindingParser(PoFileParser):
    """Parser that records the line number of the unique header message.

    The header is the non-obsolete message with an empty ``msgid`` and no
    ``msgctxt``.  There must be exactly one such message in a valid PO
    file.  The parser records the 1-based line number of the header's
    ``msgid`` line.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.header_lineno: int | None = None
        self._header_count = 0

    def _add_message(self) -> None:
        if not self.obsolete and self.context is None and self.messages:
            msgid = self.messages[0].denormalize()
            if msgid == '':
                self._header_count += 1
                if self._header_count == 1:
                    self.header_lineno = self.offset + 1  # 1-based
                # Do not feed the header to the catalog: doing so would
                # parse the locale from the header fields, which is
                # unnecessary for structural identification and may fail
                # if the locale data is not built.  Just reset state.
                self.counter += 1
                self._reset_message_state()
                return
        super()._add_message()


def _read_source(source):
    """Read the source PO file into bytes."""
    if isinstance(source, bytes):
        return source
    if isinstance(source, (str, os.PathLike)):
        with open(source, 'rb') as f:
            return f.read()
    # File-like object
    data = source.read()
    if isinstance(data, str):
        return data.encode('utf-8')
    return data


def _build_line_offsets(data):
    """Build a list of (start, end) byte offsets for each line.

    Each tuple includes the line's trailing newline (if any).
    """
    offsets = []
    start = 0
    for i, b in enumerate(data):
        if b == 0x0A:  # newline
            offsets.append((start, i + 1))
            start = i + 1
    if start < len(data):
        offsets.append((start, len(data)))
    return offsets


def _decode_line(data):
    """Decode a line for structural matching.

    Tries UTF-8 first (the Babel default), falling back to latin-1 which
    never fails.  The decoded text is only used to identify the header
    structure; the output is always spliced at the byte level.
    """
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('latin-1')


def _find_header_block(text_lines, header_lineno):
    """Find the msgstr line and continuation-line range of the header.

    Returns (msgstr_idx, cont_end) where msgstr_idx is the 0-based
    index of the header's msgstr line and cont_end is the 0-based
    index just past the last continuation line.
    """
    msgid_idx = header_lineno - 1
    msgstr_idx = msgid_idx
    while msgstr_idx < len(text_lines):
        stripped = text_lines[msgstr_idx].lstrip()
        if stripped.startswith('msgstr'):
            break
        msgstr_idx += 1
    else:
        raise HeaderEditError(
            "header message has no msgstr line; cannot identify header fields",
        )

    cont_start = msgstr_idx + 1
    cont_end = cont_start
    while cont_end < len(text_lines) and text_lines[cont_end].lstrip().startswith('"'):
        cont_end += 1

    return msgstr_idx, cont_end


def _extract_field_name(line):
    """Extract the field name from a header continuation line.

    Returns the field name (the part before the first colon) or None
    if the line is not a field line.
    """
    stripped = line.strip()
    if not (stripped.startswith('"') and stripped.endswith('"')):
        return None
    raw = unescape(stripped)
    if ':' not in raw:
        return None
    return raw.split(':', 1)[0]


def edit_po_header(source, fields, *, output=None):
    """Edit the metadata header fields of a PO file, preserving the body.

    This function locates the header message (msgid "") using the
    existing PO parsing rules, then replaces only the specified header
    fields.  Every other byte of the file -- including the body messages,
    comments, unknown header fields, and newline style (CRLF or LF) -- is
    preserved exactly.

    :param source: the PO file to edit; a path, bytes, or binary file-like
                   object
    :param fields: a mapping of header field names to their new values
    :param output: optional output destination; a path or binary file-like
                   object.  If None, the modified bytes are returned.
    :return: the modified PO file as bytes (always, even when output is
             given)
    :raises HeaderEditError: if the header cannot be identified, a field
                             is duplicated, or the input is invalid
    """
    data = _read_source(source)
    crlf = b'\r\n' in data

    line_offsets = _build_line_offsets(data)
    text_lines = [_decode_line(data[s:e]) for s, e in line_offsets]

    # Use the existing parser to find the header message.
    parser = _HeaderFindingParser(Catalog())
    parser.parse(text_lines)
    header_lineno = parser.header_lineno
    if header_lineno is None:
        raise HeaderEditError(
            "input does not contain a uniquely identifiable header message (msgid \"\")",
        )
    if parser._header_count > 1:
        raise HeaderEditError(
            f"input contains {parser._header_count} header messages (msgid \"\"); "
            "cannot uniquely identify the header",
        )

    msgstr_idx, cont_end = _find_header_block(text_lines, header_lineno)

    # Extract field names from the continuation lines.
    field_lines = {}
    for idx in range(msgstr_idx + 1, cont_end):
        name = _extract_field_name(text_lines[idx])
        if name is not None:
            field_lines.setdefault(name.lower(), []).append(idx)

    # Check for duplicate fields and build the replacement plan.
    replacements = {}
    additions = []
    for field_name, value in fields.items():
        key = field_name.lower()
        matches = field_lines.get(key, [])
        if len(matches) > 1:
            raise HeaderEditError(
                f"header field {field_name!r} appears {len(matches)} times; "
                "cannot replace a duplicated field",
            )
        if len(matches) == 1:
            idx = matches[0]
            # Preserve the original field name's case.
            original_name = _extract_field_name(text_lines[idx])
            line = escape(f"{original_name}: {value}\n")
            new_bytes = line.encode('utf-8') + (b'\r\n' if crlf else b'\n')
            replacements[idx] = new_bytes
        else:
            # Field is missing; add it at the end of the header.
            additions.append((field_name, value))

    # Apply replacements at the byte level (from end to start to preserve
    # offsets).
    result = data
    for idx in sorted(replacements, reverse=True):
        start, end = line_offsets[idx]
        result = result[:start] + replacements[idx] + result[end:]

    # Append missing fields at the end of the header block.
    if additions:
        if cont_end > msgstr_idx + 1:
            insert_pos = line_offsets[cont_end - 1][1]
        else:
            insert_pos = line_offsets[msgstr_idx][1]
        for field_name, value in additions:
            line = escape(f"{field_name}: {value}\n")
            new_bytes = line.encode('utf-8') + (b'\r\n' if crlf else b'\n')
            result = result[:insert_pos] + new_bytes + result[insert_pos:]
            insert_pos += len(new_bytes)

    if output is not None:
        if isinstance(output, (str, os.PathLike)):
            with open(output, 'wb') as f:
                f.write(result)
        else:
            output.write(result)

    return result
