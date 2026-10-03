#
# Copyright (C) 2007-2011 Edgewall Software, 2013-2025 the Babel team
# All rights reserved.
#
# This software is licensed as described in the file LICENSE, which
# you should have received as part of this distribution. The terms
# are also available at https://github.com/python-babel/babel/blob/master/LICENSE.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at https://github.com/python-babel/babel/commits/master/.

import io

import pytest

from babel.messages.pofile import read_po
from babel.messages.pofile_header import HeaderEditError, edit_po_header

BS = chr(92)  # backslash
NL = chr(10)  # newline
CR = chr(13)  # carriage return


def _make_po(lines, crlf=False):
    sep = CR + NL if crlf else NL
    return sep.join(lines).encode('utf-8')


def _header_lines(language='de', extra_fields=None):
    fields = [
        '"Project-Id-Version: Foobar 1.0' + BS + 'n"',
        '"Report-Msgid-Bugs-To: ' + BS + 'n"',
        '"Language: ' + language + BS + 'n"',
        '"Language-Team: ' + BS + 'n"',
        '"MIME-Version: 1.0' + BS + 'n"',
        '"Content-Type: text/plain; charset=utf-8' + BS + 'n"',
        '"Content-Transfer-Encoding: 8bit' + BS + 'n"',
        '"Generated-By: Babel 2.0' + BS + 'n"',
    ]
    if extra_fields:
        fields.extend(extra_fields)
    return [
        '# Translations template for PROJECT.',
        '# Copyright (C) 2024 ORGANIZATION',
        '#',
        'msgid ""',
        'msgstr ""',
        *fields,
        '',
    ]


def test_crlf_preserves_newline_style():
    data = _make_po(
        [
            *_header_lines(),
            'msgid "Language"',
            'msgstr "Sprache"',
            '',
            'msgid "Hello"',
            'msgstr "Hallo"',
        ],
        crlf=True,
    )
    result = edit_po_header(data, {'Language': 'fr'})
    assert (CR + NL).encode() in result
    assert b'"Language: fr' in result
    assert b'"Language: de' not in result


def test_crlf_body_unchanged():
    data = _make_po(
        [
            *_header_lines(),
            'msgid "Language"',
            'msgstr "Sprache"',
            '',
            'msgid "Hello"',
            'msgstr "Hallo"',
        ],
        crlf=True,
    )
    result = edit_po_header(data, {'Language': 'fr'})
    # Split on the blank line that separates the header from the body.
    sep = (CR + NL + CR + NL).encode()
    old_body = data.split(sep, 1)[1]
    new_body = result.split(sep, 1)[1]
    assert old_body == new_body


def test_crlf_readback_gets_new_language():
    data = _make_po(
        [
            *_header_lines(),
            'msgid "foo"',
            'msgstr "bar"',
        ],
        crlf=True,
    )
    result = edit_po_header(data, {'Language': 'fr'})
    catalog = read_po(io.BytesIO(result))
    assert str(catalog.locale) == 'fr'


def test_lf_preserves_newline_style():
    data = _make_po(
        [
            *_header_lines(),
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    result = edit_po_header(data, {'Language': 'fr'})
    assert CR.encode() not in result
    assert NL.encode() in result


def test_unknown_fields_preserved():
    data = _make_po(
        [
            *_header_lines(extra_fields=['"X-Custom: preserved' + BS + 'n"']),
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    result = edit_po_header(data, {'Language': 'fr'})
    assert b'"X-Custom: preserved' in result


def test_multiple_fields_replaced():
    data = _make_po(
        [
            *_header_lines(),
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    result = edit_po_header(data, {'Language': 'fr', 'Project-Id-Version': 'Bar 2.0'})
    assert b'"Language: fr' in result
    assert b'"Project-Id-Version: Bar 2.0' in result


def test_value_with_quotes():
    data = _make_po(
        [
            *_header_lines(extra_fields=['"X-Custom: old' + BS + 'n"']),
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    result = edit_po_header(data, {'X-Custom': 'say "hello"'})
    assert b'"X-Custom: say ' + BS.encode() + b'"hello' + BS.encode() + b'"' in result
    # The result must be readable by the existing parser.
    read_po(io.BytesIO(result))


def test_value_with_newlines():
    data = _make_po(
        [
            *_header_lines(),
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    result = edit_po_header(data, {'Language': 'fr' + NL + 'be'})
    # The newline must be escaped as a PO string escape.
    assert b'"Language: fr' + BS.encode() + b'nbe' in result
    # The result must be readable by the existing parser.
    read_po(io.BytesIO(result))


def test_duplicate_language_rejected():
    data = _make_po(
        [
            'msgid ""',
            'msgstr ""',
            '"Language: de' + BS + 'n"',
            '"Language: fr' + BS + 'n"',
            '"Content-Type: text/plain; charset=utf-8' + BS + 'n"',
            '',
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    original = data
    with pytest.raises(HeaderEditError):
        edit_po_header(data, {'Language': 'fr'})
    # The original input must be unchanged (byte-identical).
    assert data == original


def test_missing_header_rejected():
    data = _make_po(
        [
            'msgid "foo"',
            'msgstr "bar"',
            '',
            'msgid "baz"',
            'msgstr "qux"',
        ],
    )
    original = data
    with pytest.raises(HeaderEditError):
        edit_po_header(data, {'Language': 'fr'})
    # The original input must be unchanged (byte-identical).
    assert data == original


def test_multiple_headers_rejected():
    data = _make_po(
        [
            'msgid ""',
            'msgstr ""',
            '"Language: de' + BS + 'n"',
            '',
            'msgid ""',
            'msgstr ""',
            '"Language: fr' + BS + 'n"',
            '',
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    original = data
    with pytest.raises(HeaderEditError):
        edit_po_header(data, {'Language': 'fr'})
    # The original input must be unchanged (byte-identical).
    assert data == original


def test_case_insensitive_field_matching():
    data = _make_po(
        [
            *_header_lines(),
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    result = edit_po_header(data, {'language': 'fr'})
    # The original field name's case is preserved.
    assert b'"Language: fr' in result
    assert b'"language: fr' not in result


def test_missing_field_is_added():
    data = _make_po(
        [
            'msgid ""',
            'msgstr ""',
            '"Content-Type: text/plain; charset=utf-8' + BS + 'n"',
            '',
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    result = edit_po_header(data, {'Language': 'fr'})
    assert b'"Language: fr' in result
    # The result must be readable by the existing parser.
    catalog = read_po(io.BytesIO(result))
    assert str(catalog.locale) == 'fr'


def test_output_to_file(tmp_path):
    data = _make_po(
        [
            *_header_lines(),
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    out = tmp_path / 'out.po'
    result = edit_po_header(data, {'Language': 'fr'}, output=out)
    assert out.read_bytes() == result


def test_output_to_fileobj():
    data = _make_po(
        [
            *_header_lines(),
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    out = io.BytesIO()
    result = edit_po_header(data, {'Language': 'fr'}, output=out)
    assert out.getvalue() == result


def test_input_from_file(tmp_path):
    data = _make_po(
        [
            *_header_lines(),
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    src = tmp_path / 'in.po'
    src.write_bytes(data)
    result = edit_po_header(src, {'Language': 'fr'})
    assert b'"Language: fr' in result


def test_input_from_fileobj():
    data = _make_po(
        [
            *_header_lines(),
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    result = edit_po_header(io.BytesIO(data), {'Language': 'fr'})
    assert b'"Language: fr' in result


def test_input_from_bytes():
    data = _make_po(
        [
            *_header_lines(),
            'msgid "foo"',
            'msgstr "bar"',
        ],
    )
    result = edit_po_header(data, {'Language': 'fr'})
    assert isinstance(result, bytes)
    assert b'"Language: fr' in result
