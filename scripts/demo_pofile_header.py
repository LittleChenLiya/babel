#!/usr/bin/env python
"""
Demo: editing a PO file header while preserving the body.

This script shows how to use :func:`babel.messages.pofile_header.edit_po_header`
to change a header field of a PO file without re-flowing the whole file.
It prints the byte-level diff so you can see that only the header field
line changes; the body, comments, unknown fields, and newline style are
all preserved.

Run it with::

    python scripts/demo_pofile_header.py
"""

import difflib
import sys

# Make sure we're using the Babel source, not a previously installed version.
sys.path.insert(0, '.')

from babel.messages.pofile_header import edit_po_header  # noqa: E402

BS = chr(92)  # backslash
NL = chr(10)  # newline
CR = chr(13)  # carriage return

# A sample PO file with CRLF line endings and a body message whose text
# contains the word "Language" (to prove the body is not touched).
_lines = [
    '# Translations template for PROJECT.',
    '# Copyright (C) 2024 ORGANIZATION',
    '#',
    'msgid ""',
    'msgstr ""',
    '"Project-Id-Version: Foobar 1.0' + BS + 'n"',
    '"Report-Msgid-Bugs-To: ' + BS + 'n"',
    '"Language: de' + BS + 'n"',
    '"Language-Team: ' + BS + 'n"',
    '"MIME-Version: 1.0' + BS + 'n"',
    '"Content-Type: text/plain; charset=utf-8' + BS + 'n"',
    '"Content-Transfer-Encoding: 8bit' + BS + 'n"',
    '"Generated-By: Babel 2.0' + BS + 'n"',
    '',
    'msgid "Language"',
    'msgstr "Sprache"',
    '',
    'msgid "Hello"',
    'msgstr "Hallo"',
]
SAMPLE = (CR + NL).join(_lines).encode('utf-8')


def show_diff(old: bytes, new: bytes) -> None:
    """Print a unified diff between the old and new byte strings."""
    old_lines = old.decode('utf-8').splitlines(keepends=True)
    new_lines = new.decode('utf-8').splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile='before',
        tofile='after',
        lineterm='',
    )
    for line in diff:
        sys.stdout.write(line)


def main() -> None:
    print('=== Before ===')
    print(SAMPLE.decode('utf-8'))

    # Change the Language header field.
    result = edit_po_header(SAMPLE, {'Language': 'fr'})

    print('=== After ===')
    print(result.decode('utf-8'))

    print('=== Byte-level diff (only the Language line changes) ===')
    show_diff(SAMPLE, result)

    # Verify the body is byte-identical.
    sep = b'\r\n\r\n'
    old_body = SAMPLE.split(sep, 1)[1]
    new_body = result.split(sep, 1)[1]
    assert old_body == new_body, 'body changed!'
    print()
    print('Body is byte-identical: YES')
    print(
        'CRLF line endings preserved:',
        b'\r\n' in result and b'\n' not in result.replace(b'\r\n', b''),
    )


if __name__ == '__main__':
    main()
