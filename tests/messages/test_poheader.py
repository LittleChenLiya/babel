"""Tests for babel.messages.poheader (surgical PO header editing)."""

import io
from email import message_from_string

import pytest

from babel.core import Locale, UnknownLocaleError
from babel.messages.catalog import Catalog
from babel.messages.pofile import PoFileParser, escape, read_po
from babel.messages.poheader import (
    PoHeaderError,
    edit_po_file,
    edit_po_header,
    main,
    replace_po_header_fields,
)

# A CRLF file whose *body* deliberately contains the exact same text as the
# header field we are going to change ("Language: de"), plus an obsolete
# entry and header comments that must all survive byte for byte.
CRLF_PO = (
    b'# German translations for the demo package.\r\n'
    b'# Copyright (C) 2026 The demo team.\r\n'
    b'msgid ""\r\n'
    b'msgstr ""\r\n'
    b'"Project-Id-Version: demo 1.0\\n"\r\n'
    b'"Report-Msgid-Bugs-To: bugs@example.com\\n"\r\n'
    b'"Content-Type: text/plain; charset=UTF-8\\n"\r\n'
    b'"Language: de\\n"\r\n'
    b'"X-Generator: custom tool 3000\\n"\r\n'
    b'\r\n'
    b'#. A comment mentioning Language: de on purpose\r\n'
    b'#: main.py:1\r\n'
    b'msgid "Language"\r\n'
    b'msgstr "Language: de"\r\n'
    b'\r\n'
    b'#~ msgid "old"\r\n'
    b'#~ msgstr "Language: de\\n"\r\n'
)

NO_HEADER_PO = b'msgid "hello"\nmsgstr "world"\n'

LF_PO = (
    b'msgid ""\n'
    b'msgstr ""\n'
    b'"Content-Type: text/plain; charset=UTF-8\\n"\n'
    b'"Language: de\\n"\n'
    b'\n'
    b'msgid "hello"\n'
    b'msgstr "world"\n'
)

LATIN1_PO = (
    b'msgid ""\n'
    b'msgstr ""\n'
    b'"Content-Type: text/plain; charset=ISO-8859-1\\n"\n'
    b'"Last-Translator: Someone\\n"\n'
    b'\n'
    b'msgid "hello"\n'
    b'msgstr "world"\n'
)


@pytest.fixture
def locale_parse_stub(monkeypatch):
    """Make ``Locale.parse`` usable without compiled CLDR data.

    A fresh source checkout has no ``babel/global.dat``, so ``Locale.parse``
    would raise ``RuntimeError``.  Raise ``UnknownLocaleError`` instead,
    which ``Catalog._set_locale`` handles gracefully (the locale identifier
    is still recorded on the catalog).
    """

    def parse(cls, identifier, *args, **kwargs):
        raise UnknownLocaleError(identifier)

    monkeypatch.setattr(Locale, "parse", classmethod(parse))


def read_header_string(data: bytes, charset: str = "utf-8") -> str:
    """Parse *data* with the stock PO parser and return the header
    message's ``msgstr`` exactly as the parser denormalized it."""
    captured = {}

    class Capture(Catalog):
        def __setitem__(self, id, message):
            if id == '':
                captured["header"] = message.string
            super().__setitem__(id, message)

    catalog = Capture(charset=charset)
    PoFileParser(catalog, abort_invalid=True).parse(io.BytesIO(data))
    return captured["header"]


def read_header_fields(data: bytes, charset: str = "utf-8"):
    """Header fields of *data* as an ordered (name, value) list, parsed
    with babel's PO parser and the stdlib email parser only."""
    return message_from_string(read_header_string(data, charset)).items()


@pytest.mark.usefixtures("locale_parse_stub")
def test_crlf_language_change_only_touches_header():
    edit = edit_po_header(CRLF_PO, {"Language": "fr"})
    new = edit.data

    # The modified range is exactly the header msgstr section.
    assert edit.old_lines[0].rstrip(b"\r") == b'msgstr ""'
    assert edit.start_line == CRLF_PO.split(b"\n").index(b'msgstr ""\r')

    # Read back with the stock parser: the catalog got the new language.
    catalog = read_po(io.BytesIO(new), abort_invalid=True)
    assert catalog.locale_identifier == "fr"
    fields = read_header_fields(new)
    assert dict(fields)["Language"] == "fr"

    # Unknown fields kept their relative order.
    assert [name for name, _ in fields] == [
        "Project-Id-Version",
        "Report-Msgid-Bugs-To",
        "Content-Type",
        "Language",
        "X-Generator",
    ]

    # Everything before the header msgstr is byte-identical ...
    assert new[: new.index(b'msgstr')] == CRLF_PO[: CRLF_PO.index(b'msgstr')]
    # ... and so is everything after the header, including the body text
    # that is identical to the old header value.
    body_marker = b'#. A comment mentioning'
    assert new[new.index(body_marker) :] == CRLF_PO[CRLF_PO.index(body_marker) :]
    assert b'msgstr "Language: de"\r\n' in new  # body entry, untouched

    # Newline style preserved: CRLF only, same line count.
    assert new.count(b'\r\n') == CRLF_PO.count(b'\r\n')
    assert b'\n' not in new.replace(b'\r\n', b'')


@pytest.mark.usefixtures("locale_parse_stub")
def test_lf_file_keeps_lf():
    new = replace_po_header_fields(LF_PO, {"Language": "fr"})
    assert b'\r' not in new
    assert dict(read_header_fields(new))["Language"] == "fr"


@pytest.mark.usefixtures("locale_parse_stub")
def test_value_with_quotes_and_newline_is_escaped():
    value = 'say "hi"\nsecond\tline'
    new = replace_po_header_fields(CRLF_PO, {"X-Quote": value})
    # Emitted as PO string escapes (one continuation line per header line,
    # the standard PO header style), using the parser's own escaping ...
    assert escape('X-Quote: say "hi"\n').encode("utf-8") + b"\r" in new
    assert escape("second\tline\n").encode("utf-8") + b"\r" in new
    # ... which the stock parser unescapes back to the original value.
    header = read_header_string(new)
    assert f"X-Quote: {value}\n" in header
    # The rest of the file still parses cleanly (parser resynchronized).
    catalog = read_po(io.BytesIO(new), abort_invalid=True)
    assert catalog.get("Language").string == "Language: de"


@pytest.mark.usefixtures("locale_parse_stub")
def test_missing_field_is_appended_after_existing_fields():
    new = replace_po_header_fields(CRLF_PO, {"Language-Team": "de <li@example.com>"})
    names = [name for name, _ in read_header_fields(new)]
    assert names == [
        "Project-Id-Version",
        "Report-Msgid-Bugs-To",
        "Content-Type",
        "Language",
        "X-Generator",
        "Language-Team",
    ]


def test_duplicate_header_field_rejected(tmp_path):
    dup = CRLF_PO.replace(
        b'"X-Generator: custom tool 3000\\n"',
        b'"Language: fr\\n"',
    )
    with pytest.raises(PoHeaderError, match="duplicate header field"):
        edit_po_header(dup, {"Language": "fr"})

    # The file on disk is left untouched, byte for byte.
    path = tmp_path / "dup.po"
    path.write_bytes(dup)
    with pytest.raises(PoHeaderError):
        edit_po_file(path, {"Language": "fr"})
    assert path.read_bytes() == dup


def test_missing_header_rejected(tmp_path):
    with pytest.raises(PoHeaderError, match="no header message"):
        edit_po_header(NO_HEADER_PO, {"Language": "fr"})

    path = tmp_path / "noheader.po"
    path.write_bytes(NO_HEADER_PO)
    with pytest.raises(PoHeaderError):
        edit_po_file(path, {"Language": "fr"})
    assert path.read_bytes() == NO_HEADER_PO


def test_non_unique_header_rejected():
    two_headers = LF_PO + b'\nmsgid ""\nmsgstr ""\n"Language: it\\n"\n'
    with pytest.raises(PoHeaderError, match="not unique"):
        edit_po_header(two_headers, {"Language": "fr"})


def test_obsolete_only_header_rejected():
    data = b'#~ msgid ""\n#~ msgstr ""\n\nmsgid "x"\nmsgstr "y"\n'
    with pytest.raises(PoHeaderError, match="no header message"):
        edit_po_header(data, {"Language": "fr"})


def test_empty_msgid_with_msgctxt_is_not_the_header():
    data = LF_PO + b'\nmsgctxt "button"\nmsgid ""\nmsgstr "leer"\n'
    new = replace_po_header_fields(data, {"Language": "fr"})
    assert b'"Language: fr\\n"' in new
    # The msgctxt message is outside the edited range, byte-identical.
    marker = b'msgctxt "button"'
    assert new[new.index(marker) :] == data[data.index(marker) :]


@pytest.mark.usefixtures("locale_parse_stub")
def test_inline_msgstr_header():
    data = b'msgid ""\nmsgstr "Language: de\\n"\n\nmsgid "x"\nmsgstr "y"\n'
    new = replace_po_header_fields(data, {"Language": "fr"})
    assert dict(read_header_fields(new))["Language"] == "fr"


@pytest.mark.usefixtures("locale_parse_stub")
def test_non_utf8_charset_roundtrip():
    new = replace_po_header_fields(LATIN1_PO, {"Last-Translator": "Jürgen"})
    # The replacement is encoded with the charset declared in the header.
    assert "Jürgen".encode("iso-8859-1") in new
    assert "Jürgen".encode("utf-8") not in new
    fields = read_header_fields(new, charset="iso-8859-1")
    assert dict(fields)["Last-Translator"] == "Jürgen"


def test_empty_replacements_is_byte_identical_noop():
    assert replace_po_header_fields(CRLF_PO, {}) == CRLF_PO


def test_invalid_field_name_rejected():
    with pytest.raises(PoHeaderError, match="invalid header field name"):
        edit_po_header(LF_PO, {"Bad:Name": "x"})


@pytest.mark.usefixtures("locale_parse_stub")
def test_edit_po_file_roundtrip(tmp_path):
    path = tmp_path / "app.po"
    path.write_bytes(CRLF_PO)
    edit = edit_po_file(path, {"Language": "fr"})
    assert path.read_bytes() == edit.data
    catalog = read_po(io.BytesIO(path.read_bytes()), abort_invalid=True)
    assert catalog.locale_identifier == "fr"


def test_cli_shows_modified_range_and_writes_only_in_place(tmp_path, capsys):
    path = tmp_path / "app.po"
    path.write_bytes(CRLF_PO)

    # Dry run: shows the modified line range, does not write.
    assert main([str(path), "Language=fr"]) == 0
    out = capsys.readouterr().out
    assert "@@" in out
    assert '-"Language: de\\n"' in out
    assert '+"Language: fr\\n"' in out
    assert "dry run" in out
    assert path.read_bytes() == CRLF_PO

    # In-place: writes the new header.
    assert main([str(path), "Language=fr", "--in-place"]) == 0
    assert b'"Language: fr\\n"' in path.read_bytes()

    # Failure: exit code 1, file untouched.
    dup = CRLF_PO.replace(b'"X-Generator: custom tool 3000\\n"', b'"Language: fr\\n"')
    path.write_bytes(dup)
    assert main([str(path), "Language=fr"]) == 1
    assert path.read_bytes() == dup
