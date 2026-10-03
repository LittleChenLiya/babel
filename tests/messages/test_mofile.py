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


def test_check_mo_encoding_ascii_reports_slot_and_character():
    catalog = Catalog(charset='ascii')
    catalog.add('hello', '你好')
    errors = mofile.check_mo_encoding(catalog)
    assert len(errors) == 1
    error = errors[0]
    assert error.message.id == 'hello'
    assert error.slot == 'msgstr'
    assert error.start == 0
    assert error.end > error.start
    assert error.character == '你'
    assert error.charset == 'ascii'


def test_check_mo_encoding_utf8_passes_and_keeps_catalog():
    catalog = Catalog(charset='utf-8')
    catalog.add('hello', '你好')
    catalog.add(('one', 'two'), ('一', '二'))
    catalog.add('ctx', '测', context='menu')
    before = (
        catalog.charset,
        catalog['hello'].string,
        catalog.get('ctx', context='menu').string,
        catalog.get('ctx', context='menu').context,
    )
    assert mofile.check_mo_encoding(catalog) == []
    after = (
        catalog.charset,
        catalog['hello'].string,
        catalog.get('ctx', context='menu').string,
        catalog.get('ctx', context='menu').context,
    )
    assert before == after


def test_check_mo_encoding_does_not_modify_catalog_on_error():
    catalog = Catalog(charset='ascii')
    catalog.add('hello', '你好')
    catalog.add(('one', 'two'), ('一个', '两个'))
    catalog.add('ctx', '上下文', context='menu')
    before = (
        catalog.charset,
        catalog['hello'].string,
        catalog.get(('one', 'two')).string,
        catalog.get('ctx', context='menu').string,
        catalog.get('ctx', context='menu').context,
    )
    errors = mofile.check_mo_encoding(catalog)
    assert len(errors) == 4
    after = (
        catalog.charset,
        catalog['hello'].string,
        catalog.get(('one', 'two')).string,
        catalog.get('ctx', context='menu').string,
        catalog.get('ctx', context='menu').context,
    )
    assert before == after


def test_check_mo_encoding_plural_second_slot():
    catalog = Catalog(charset='ascii')
    catalog.add(('one file', 'two files'), ('一个文件', '两个文件'))
    errors = mofile.check_mo_encoding(catalog)
    slots = {e.slot for e in errors}
    assert 'msgstr' in slots
    assert 'msgstr[1]' in slots
    for error in errors:
        assert error.start == 0
        assert error.character in '一两'


def test_check_mo_encoding_context_message():
    catalog = Catalog(charset='ascii')
    catalog.add('file', '文件', context='menu')
    errors = mofile.check_mo_encoding(catalog)
    assert len(errors) == 1
    error = errors[0]
    assert error.slot == 'msgstr'
    assert error.start == 0
    assert error.character == '文'
    assert error.message.context == 'menu'


def test_check_mo_encoding_against_write_mo():
    # An ascii catalog with non-ascii translations: write_mo fails on the
    # first unencodable string, while check_mo_encoding reports it up front.
    ascii_catalog = Catalog(charset='ascii')
    ascii_catalog.add('hello', '你好')
    buf = BytesIO()
    with pytest.raises(UnicodeEncodeError):
        mofile.write_mo(buf, ascii_catalog)
    errors = mofile.check_mo_encoding(ascii_catalog)
    assert len(errors) == 1
    assert errors[0].slot == 'msgstr'
    assert errors[0].start == 0
    assert errors[0].character == '你'

    # A utf-8 catalog with the same translations writes fine and passes.
    utf8_catalog = Catalog(charset='utf-8')
    utf8_catalog.add('hello', '你好')
    utf8_catalog.add(('one', 'two'), ('一', '二'))
    buf2 = BytesIO()
    mofile.write_mo(buf2, utf8_catalog)
    assert mofile.check_mo_encoding(utf8_catalog) == []


def test_check_mo_encoding_fuzzy_and_empty_not_conflated():
    catalog = Catalog(charset='ascii')
    catalog.add('fuzzy msg', '模糊', flags=['fuzzy'])
    catalog.add('empty msg', '')
    catalog.add('real msg', '真实')

    # By default fuzzy and empty translations are skipped, just like
    # write_mo does -- they are not reported as encoding errors.
    errors = mofile.check_mo_encoding(catalog)
    assert len(errors) == 1
    assert errors[0].message.id == 'real msg'

    # With use_fuzzy the fuzzy translation is checked too, but the empty
    # translation is still skipped (there is nothing to encode).
    errors_fuzzy = mofile.check_mo_encoding(catalog, use_fuzzy=True)
    assert len(errors_fuzzy) == 2
    assert {e.message.id for e in errors_fuzzy} == {'fuzzy msg', 'real msg'}
    assert all(e.message.id != 'empty msg' for e in errors_fuzzy)


def test_check_mo_encoding_header_message():
    # The catalog header is always written by write_mo, so it is checked too.
    catalog = Catalog(charset='ascii')
    catalog.add(
        '',
        'Content-Type: text/plain; charset=ascii\n'
        'Last-Translator: 翻译员 <translator@example.com>',
    )
    errors = mofile.check_mo_encoding(catalog)
    assert len(errors) == 1
    assert errors[0].slot == 'msgstr'
    assert errors[0].character == '翻'
