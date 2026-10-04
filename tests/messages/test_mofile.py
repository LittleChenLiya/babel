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

import os
from io import BytesIO

import pytest

from babel.messages import Catalog, mofile
from babel.support import Translations

data_dir = os.path.join(os.path.dirname(__file__), 'data')


def test_basics():
    mo_path = os.path.join(data_dir, 'project', 'i18n', 'de', 'LC_MESSAGES', 'messages.mo')
    with open(mo_path, 'rb') as mo_file:
        catalog = mofile.read_mo(mo_file)
        assert len(catalog) == 2
        assert catalog.project == 'TestProject'
        assert catalog.version == '0.1'
        assert catalog['bar'].string == 'Stange'
        assert catalog['foobar'].string == ['Fuhstange', 'Fuhstangen']



def test_sorting():
    # Ensure the header is sorted to the first entry so that its charset
    # can be applied to all subsequent messages by GNUTranslations
    # (ensuring all messages are safely converted to unicode)
    catalog = Catalog(locale='en_US')
    catalog.add('', '''\
"Content-Type: text/plain; charset=utf-8\n"
"Content-Transfer-Encoding: 8bit\n''',
    )
    catalog.add('foo', 'Voh')
    catalog.add(('There is', 'There are'), ('Es gibt', 'Es gibt'))
    catalog.add('Fizz', '')
    catalog.add(('Fuzz', 'Fuzzes'), ('', ''))
    buf = BytesIO()
    mofile.write_mo(buf, catalog)
    buf.seek(0)
    translations = Translations(fp=buf)
    assert translations.ugettext('foo') == 'Voh'
    assert translations.ungettext('There is', 'There are', 1) == 'Es gibt'
    assert translations.ugettext('Fizz') == 'Fizz'
    assert translations.ugettext('Fuzz') == 'Fuzz'
    assert translations.ugettext('Fuzzes') == 'Fuzzes'


def test_more_plural_forms():
    catalog2 = Catalog(locale='ru_RU')
    catalog2.add(('Fuzz', 'Fuzzes'), ('', '', ''))
    buf = BytesIO()
    mofile.write_mo(buf, catalog2)


def test_empty_translation_with_fallback():
    catalog1 = Catalog(locale='fr_FR')
    catalog1.add('', '''\
"Content-Type: text/plain; charset=utf-8\n"
"Content-Transfer-Encoding: 8bit\n''')
    catalog1.add('Fuzz', '')
    buf1 = BytesIO()
    mofile.write_mo(buf1, catalog1)
    buf1.seek(0)
    catalog2 = Catalog(locale='fr')
    catalog2.add('', '''\
"Content-Type: text/plain; charset=utf-8\n"
"Content-Transfer-Encoding: 8bit\n''')
    catalog2.add('Fuzz', 'Flou')
    buf2 = BytesIO()
    mofile.write_mo(buf2, catalog2)
    buf2.seek(0)

    translations = Translations(fp=buf1)
    translations.add_fallback(Translations(fp=buf2))

    assert translations.ugettext('Fuzz') == 'Flou'


def test_read_mo_decodes_message_context() -> None:
    catalog = Catalog(locale='fi_FI')
    catalog.add('', '''\
"Content-Type: text/plain; charset=utf-8\n"
"Content-Transfer-Encoding: 8bit\n''')
    catalog.add('x', 'åäöÅÄÖ', context='ほげ')
    buf = BytesIO()
    mofile.write_mo(buf, catalog)
    buf.seek(0)
    del catalog

    catalog = mofile.read_mo(buf)
    message = catalog.get('x', context='ほげ')
    assert message is not None
    assert message.id == 'x'
    assert message.context == 'ほげ'
    assert message.string == 'åäöÅÄÖ'
    assert not catalog.get('x')  # Not without the context


def _snapshot_catalog(catalog):
    return (
        catalog.charset,
        catalog.fuzzy,
        [(m.id, m.string, frozenset(m.flags), m.context) for m in catalog],
    )


def test_check_mo_charset_ascii_reports_slot_and_position():
    catalog = Catalog(locale='zh_CN', charset='ascii')
    catalog.add('hello', '你好')
    catalog.add('ok', 'fine')

    errors = mofile.check_mo_charset(catalog)

    assert len(errors) == 1
    error = errors[0]
    assert error.message is catalog['hello']
    assert error.slot == 'msgstr'
    assert error.position == 0
    assert error.character == '你'
    assert isinstance(error.error, UnicodeEncodeError)
    assert 'msgstr' in str(error)


def test_check_mo_charset_utf8_passes_and_catalog_unmodified():
    catalog = Catalog(locale='zh_CN', charset='utf-8')
    catalog.add('hello', '你好')
    catalog.add(('bar', 'bars'), ('条', '些条'), flags=['fuzzy'])
    catalog.add('ctx', '上下文', context='menu')
    before = _snapshot_catalog(catalog)

    assert mofile.check_mo_charset(catalog) == []
    assert mofile.check_mo_charset(catalog, use_fuzzy=True) == []
    assert _snapshot_catalog(catalog) == before


def test_check_mo_charset_does_not_modify_catalog_on_failure():
    catalog = Catalog(locale='zh_CN', charset='ascii')
    catalog.add('hello', '你好', flags=['fuzzy'])
    before = _snapshot_catalog(catalog)

    errors = mofile.check_mo_charset(catalog, use_fuzzy=True)

    assert errors
    assert _snapshot_catalog(catalog) == before


def test_check_mo_charset_plural_second_slot():
    catalog = Catalog(locale='zh_CN', charset='ascii')
    catalog.add(('one thing', 'many things'), ('one', '许多东西'))

    errors = mofile.check_mo_charset(catalog)

    assert [(e.slot, e.position, e.character) for e in errors] == [
        ('msgstr[1]', 0, '许'),
    ]
    assert errors[0].message.id == ('one thing', 'many things')


def test_check_mo_charset_context_locatable():
    catalog = Catalog(locale='zh_CN', charset='ascii')
    catalog.add('verb', '跑', context='菜单')
    catalog.add('plain', 'plain')

    errors = mofile.check_mo_charset(catalog)

    assert [(e.slot, e.position, e.character) for e in errors] == [
        ('msgctxt', 0, '菜'),
        ('msgstr', 0, '跑'),
    ]
    for error in errors:
        assert error.message.context == '菜单'
        assert error.message.id == 'verb'


def test_check_mo_charset_fuzzy_and_empty_are_selection_not_errors():
    catalog = Catalog(locale='zh_CN', charset='ascii')
    catalog.add('fuzzy one', '模糊', flags=['fuzzy'])
    catalog.add('empty one', '')
    catalog.add(('empty plural', 'empty plurals'), ('', ''))

    # Fuzzy and untranslated messages are skipped by write_mo (and thus by
    # the check) by default; that is output selection, not an encoding error.
    assert mofile.check_mo_charset(catalog) == []

    # With use_fuzzy=True the fuzzy message is written, so it is checked.
    errors = mofile.check_mo_charset(catalog, use_fuzzy=True)
    assert [(e.message.id, e.slot) for e in errors] == [('fuzzy one', 'msgstr')]


def test_check_mo_charset_charset_override_does_not_touch_catalog():
    catalog = Catalog(locale='zh_CN', charset='utf-8')
    catalog.add('hello', '你好')

    assert mofile.check_mo_charset(catalog, charset='ascii')
    assert catalog.charset == 'utf-8'


def test_check_mo_charset_matches_write_mo_results():
    # A clean catalog: the check passes and write_mo succeeds.
    clean = Catalog(locale='en_US', charset='ascii')
    clean.add('foo', 'Voh')
    clean.add(('bar', 'bars'), ('Bahr', 'Bahrs'))
    clean.add('ctx', 'CTX', context='menu')
    assert mofile.check_mo_charset(clean) == []
    buf = BytesIO()
    mofile.write_mo(buf, clean)
    assert buf.getvalue()

    # A catalog with unencodable strings: the check reports exactly the
    # pieces that make write_mo fail with UnicodeEncodeError.
    bad = Catalog(locale='zh_CN', charset='ascii')
    bad.add('hello', '你好')
    bad.add(('one', 'many'), ('一', '许多'))
    bad.add('verb', '跑', context='菜单')
    errors = mofile.check_mo_charset(bad)
    assert [(e.message.id, e.slot) for e in errors] == [
        ('hello', 'msgstr'),
        (('one', 'many'), 'msgstr[0]'),
        (('one', 'many'), 'msgstr[1]'),
        ('verb', 'msgctxt'),
        ('verb', 'msgstr'),
    ]
    with pytest.raises(UnicodeEncodeError):
        mofile.write_mo(BytesIO(), bad)

    # Every reported piece is genuinely unencodable, and re-encoding the
    # reported string reproduces the reported error position.
    for error in errors:
        with pytest.raises(UnicodeEncodeError) as excinfo:
            error.string.encode(bad.charset)
        assert excinfo.value.start == error.position
