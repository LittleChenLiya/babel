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

from datetime import datetime
from io import BytesIO

import pytest

from babel import __version__ as VERSION
from babel.core import Locale, UnknownLocaleError
from babel.dates import format_datetime
from babel.messages import Catalog, Message, checkers
from babel.messages.catalog import TranslationError
from babel.messages.checkers import (
    PlaceholderError,
    _validate_format,
    python_brace_format,
    python_format,
)
from babel.messages.plurals import PLURALS
from babel.messages.pofile import read_po
from babel.util import LOCALTZ

# the last msgstr[idx] is always missing except for singular plural forms


def test_1_num_plurals_checkers():
    for _locale in [p for p in PLURALS if PLURALS[p][0] == 1]:
        try:
            locale = Locale.parse(_locale)
        except UnknownLocaleError:
            # Just an alias? Not what we're testing here, let's continue
            continue
        date = format_datetime(datetime.now(LOCALTZ), 'yyyy-MM-dd HH:mmZ', tzinfo=LOCALTZ, locale=_locale)
        plural = PLURALS[_locale][0]
        po_file = (f"""\
# {locale.english_name} translations for TestProject.
# Copyright (C) 2007 FooBar, Inc.
# This file is distributed under the same license as the TestProject
# project.
# FIRST AUTHOR <EMAIL@ADDRESS>, 2007.
#
msgid ""
msgstr ""
"Project-Id-Version: TestProject 0.1\\n"
"Report-Msgid-Bugs-To: bugs.address@email.tld\\n"
"POT-Creation-Date: 2007-04-01 15:30+0200\\n"
"PO-Revision-Date: {date}\\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"
"Language-Team: {_locale} <LL@li.org>\n"
"Plural-Forms: nplurals={plural}; plural={plural};\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=utf-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Generated-By: Babel {VERSION}\\n"

#. This will be a translator comment,
#. that will include several lines
#: project/file1.py:8
msgid "bar"
msgstr ""

#: project/file2.py:9
msgid "foobar"
msgid_plural "foobars"
msgstr[0] ""

""").encode('utf-8')

        # This test will fail for revisions <= 406 because so far
        # catalog.num_plurals was neglected
        catalog = read_po(BytesIO(po_file), _locale)
        message = catalog['foobar']
        checkers.num_plurals(catalog, message)


def test_2_num_plurals_checkers():
    # in this testcase we add an extra msgstr[idx], we should be
    # disregarding it
    for _locale in [p for p in PLURALS if PLURALS[p][0] == 2]:
        if _locale in ['nn', 'no']:
            _locale = 'nn_NO'
            num_plurals = PLURALS[_locale.split('_')[0]][0]
            plural_expr = PLURALS[_locale.split('_')[0]][1]
        else:
            num_plurals = PLURALS[_locale][0]
            plural_expr = PLURALS[_locale][1]
        try:
            locale = Locale(_locale)
            date = format_datetime(datetime.now(LOCALTZ),
                                   'yyyy-MM-dd HH:mmZ',
                                   tzinfo=LOCALTZ, locale=_locale)
        except UnknownLocaleError:
            # Just an alias? Not what we're testing here, let's continue
            continue
        po_file = f"""\
# {locale.english_name} translations for TestProject.
# Copyright (C) 2007 FooBar, Inc.
# This file is distributed under the same license as the TestProject
# project.
# FIRST AUTHOR <EMAIL@ADDRESS>, 2007.
#
msgid ""
msgstr ""
"Project-Id-Version: TestProject 0.1\\n"
"Report-Msgid-Bugs-To: bugs.address@email.tld\\n"
"POT-Creation-Date: 2007-04-01 15:30+0200\\n"
"PO-Revision-Date: {date}\\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"
"Language-Team: {_locale} <LL@li.org>\\n"
"Plural-Forms: nplurals={num_plurals}; plural={plural_expr};\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=utf-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Generated-By: Babel {VERSION}\\n"

#. This will be a translator comment,
#. that will include several lines
#: project/file1.py:8
msgid "bar"
msgstr ""

#: project/file2.py:9
msgid "foobar"
msgid_plural "foobars"
msgstr[0] ""
msgstr[1] ""
msgstr[2] ""

""".encode('utf-8')
        # we should be adding the missing msgstr[0]

        # This test will fail for revisions <= 406 because so far
        # catalog.num_plurals was neglected
        catalog = read_po(BytesIO(po_file), _locale)
        message = catalog['foobar']
        checkers.num_plurals(catalog, message)


def test_3_num_plurals_checkers():
    for _locale in [p for p in PLURALS if PLURALS[p][0] == 3]:
        plural = format_datetime(datetime.now(LOCALTZ), 'yyyy-MM-dd HH:mmZ', tzinfo=LOCALTZ, locale=_locale)
        english_name = Locale.parse(_locale).english_name
        po_file = rf"""\
# {english_name} translations for TestProject.
# Copyright (C) 2007 FooBar, Inc.
# This file is distributed under the same license as the TestProject
# project.
# FIRST AUTHOR <EMAIL@ADDRESS>, 2007.
#
msgid ""
msgstr ""
"Project-Id-Version: TestProject 0.1\n"
"Report-Msgid-Bugs-To: bugs.address@email.tld\n"
"POT-Creation-Date: 2007-04-01 15:30+0200\n"
"PO-Revision-Date: {plural}\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: {_locale} <LL@li.org>\n"
"Plural-Forms: nplurals={PLURALS[_locale][0]}; plural={PLURALS[_locale][0]};\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=utf-8\n"
"Content-Transfer-Encoding: 8bit\n"
"Generated-By: Babel {VERSION}\n"

#. This will be a translator comment,
#. that will include several lines
#: project/file1.py:8
msgid "bar"
msgstr ""

#: project/file2.py:9
msgid "foobar"
msgid_plural "foobars"
msgstr[0] ""
msgstr[1] ""

""".encode('utf-8')

        # This test will fail for revisions <= 406 because so far
        # catalog.num_plurals was neglected
        catalog = read_po(BytesIO(po_file), _locale)
        message = catalog['foobar']
        checkers.num_plurals(catalog, message)


def test_4_num_plurals_checkers():
    for _locale in [p for p in PLURALS if PLURALS[p][0] == 4]:
        date = format_datetime(datetime.now(LOCALTZ), 'yyyy-MM-dd HH:mmZ', tzinfo=LOCALTZ, locale=_locale)
        english_name = Locale.parse(_locale).english_name
        plural = PLURALS[_locale][0]
        po_file = rf"""\
# {english_name} translations for TestProject.
# Copyright (C) 2007 FooBar, Inc.
# This file is distributed under the same license as the TestProject
# project.
# FIRST AUTHOR <EMAIL@ADDRESS>, 2007.
#
msgid ""
msgstr ""
"Project-Id-Version: TestProject 0.1\n"
"Report-Msgid-Bugs-To: bugs.address@email.tld\n"
"POT-Creation-Date: 2007-04-01 15:30+0200\n"
"PO-Revision-Date: {date}\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: {_locale} <LL@li.org>\n"
"Plural-Forms: nplurals={plural}; plural={plural};\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=utf-8\n"
"Content-Transfer-Encoding: 8bit\n"
"Generated-By: Babel {VERSION}\n"

#. This will be a translator comment,
#. that will include several lines
#: project/file1.py:8
msgid "bar"
msgstr ""

#: project/file2.py:9
msgid "foobar"
msgid_plural "foobars"
msgstr[0] ""
msgstr[1] ""
msgstr[2] ""

""".encode('utf-8')

        # This test will fail for revisions <= 406 because so far
        # catalog.num_plurals was neglected
        catalog = read_po(BytesIO(po_file), _locale)
        message = catalog['foobar']
        checkers.num_plurals(catalog, message)


def test_5_num_plurals_checkers():
    for _locale in [p for p in PLURALS if PLURALS[p][0] == 5]:
        date = format_datetime(datetime.now(LOCALTZ), 'yyyy-MM-dd HH:mmZ', tzinfo=LOCALTZ, locale=_locale)
        english_name = Locale.parse(_locale).english_name
        plural = PLURALS[_locale][0]
        po_file = rf"""\
# {english_name} translations for TestProject.
# Copyright (C) 2007 FooBar, Inc.
# This file is distributed under the same license as the TestProject
# project.
# FIRST AUTHOR <EMAIL@ADDRESS>, 2007.
#
msgid ""
msgstr ""
"Project-Id-Version: TestProject 0.1\n"
"Report-Msgid-Bugs-To: bugs.address@email.tld\n"
"POT-Creation-Date: 2007-04-01 15:30+0200\n"
"PO-Revision-Date: {date}\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: {_locale} <LL@li.org>\n"
"Plural-Forms: nplurals={plural}; plural={plural};\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=utf-8\n"
"Content-Transfer-Encoding: 8bit\n"
"Generated-By: Babel {VERSION}\n"

#. This will be a translator comment,
#. that will include several lines
#: project/file1.py:8
msgid "bar"
msgstr ""

#: project/file2.py:9
msgid "foobar"
msgid_plural "foobars"
msgstr[0] ""
msgstr[1] ""
msgstr[2] ""
msgstr[3] ""

""".encode('utf-8')

        # This test will fail for revisions <= 406 because so far
        # catalog.num_plurals was neglected
        catalog = read_po(BytesIO(po_file), _locale)
        message = catalog['foobar']
        checkers.num_plurals(catalog, message)


def test_6_num_plurals_checkers():
    for _locale in [p for p in PLURALS if PLURALS[p][0] == 6]:
        english_name = Locale.parse(_locale).english_name
        date = format_datetime(datetime.now(LOCALTZ), 'yyyy-MM-dd HH:mmZ', tzinfo=LOCALTZ, locale=_locale)
        plural = PLURALS[_locale][0]
        po_file = rf"""\
# {english_name} translations for TestProject.
# Copyright (C) 2007 FooBar, Inc.
# This file is distributed under the same license as the TestProject
# project.
# FIRST AUTHOR <EMAIL@ADDRESS>, 2007.
#
msgid ""
msgstr ""
"Project-Id-Version: TestProject 0.1\n"
"Report-Msgid-Bugs-To: bugs.address@email.tld\n"
"POT-Creation-Date: 2007-04-01 15:30+0200\n"
"PO-Revision-Date: {date}\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: {_locale} <LL@li.org>\n"
"Plural-Forms: nplurals={plural}; plural={plural};\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=utf-8\n"
"Content-Transfer-Encoding: 8bit\n"
"Generated-By: Babel {VERSION}\n"

#. This will be a translator comment,
#. that will include several lines
#: project/file1.py:8
msgid "bar"
msgstr ""

#: project/file2.py:9
msgid "foobar"
msgid_plural "foobars"
msgstr[0] ""
msgstr[1] ""
msgstr[2] ""
msgstr[3] ""
msgstr[4] ""

""".encode('utf-8')

        # This test will fail for revisions <= 406 because so far
        # catalog.num_plurals was neglected
        catalog = read_po(BytesIO(po_file), _locale)
        message = catalog['foobar']
        checkers.num_plurals(catalog, message)


@pytest.mark.parametrize(
    ('msgid', 'msgstr'),
    [
        ('foo %s', 'foo'),
        (('foo %s', 'bar'), ('foo', 'bar')),
        (('foo', 'bar %s'), ('foo', 'bar')),
        (('foo %s', 'bar'), 'foo'),
        (('foo %s', 'bar %d'), ('foo %s', 'bar %d', 'baz')),
        (('foo %s', 'bar %d'), ('foo %s', 'bar %d', 'baz %d', 'qux')),
        ('%(foo)s', 'foo'),
    ],
)
def test_python_format_invalid(msgid, msgstr):
    msg = Message(msgid, msgstr)
    assert python_format(None, msg)


@pytest.mark.parametrize(
    ('msgid', 'msgstr'),
    [
        ('foo', 'foo'),
        ('foo %s', ''),
        (('foo %s', 'bar %d'), ('foo %s', 'bar %d')),
        (('foo', 'bar %s'), ('foo')),
        (('foo', 'bar %s'), ('', '')),
        (('foo', 'bar %s'), ('foo', '')),
        (('foo %s', 'bar %d'), ('foo %s', '')),
        (('foo %s', 'bar %d'), ('foo %s', 'bar %d', 'baz %d')),
        ('%(bar)s foo %(n)d', '%(n)d foo %(bar)s'),
        ('%(foo)s', '%(foo)s %(foo)s'),
    ],
)
def test_python_format_valid(msgid, msgstr):
    assert python_format(None, Message(msgid, msgstr)) == []


@pytest.mark.parametrize(
    ('msgid', 'msgstr', 'error'),
    [
        ('%s %(foo)s', '%s %(foo)s', 'format string mixes positional and named placeholders'),
        ('foo %s', 'foo', 'placeholders are incompatible'),
        ('%s', '%(foo)s', 'the format strings are of different kinds'),
        ('%s', '%s %d', 'positional format placeholders are unbalanced'),
        ('%s', '%d', "incompatible format for placeholder 1: 's' and 'd' are not compatible"),
        (
            '%s %s %d',
            '%s %s %s',
            "incompatible format for placeholder 3: 'd' and 's' are not compatible",
        ),
        ('%(foo)s', '%(bar)s', "unknown named placeholder 'bar'"),
        ('%(foo)s', '%(bar)d', "unknown named placeholder 'bar'"),
        (
            '%(foo)s',
            '%(foo)d',
            "incompatible format for placeholder 'foo': 'd' and 's' are not compatible",
        ),
    ],
)
def test__validate_format_invalid(msgid, msgstr, error):
    with pytest.raises(TranslationError, match=error):
        _validate_format(msgid, msgstr)


@pytest.mark.parametrize(
    ('msgid', 'msgstr'),
    [
        ('foo', 'foo'),
        ('foo', 'foo %s'),
        ('%s foo', 'foo %s'),
        ('%i', '%d'),
        ('%d', '%u'),
        ('%x', '%X'),
        ('%f', '%F'),
        ('%F', '%g'),
        ('%g', '%G'),
        ('%(foo)s', 'foo'),
        ('%(foo)s', '%(foo)s %(foo)s'),
        ('%(bar)s foo %(n)d', '%(n)d foo %(bar)s'),
    ],
)
def test__validate_format_valid(msgid, msgstr):
    _validate_format(msgid, msgstr)


def test_python_brace_format_missing_nested_field():
    # {width} is nested inside the format spec of {value}.
    msg = Message('{name}: {value:{width}.2f}', '{name}: {value:.2f}')
    errors = python_brace_format(None, msg)
    assert len(errors) == 1
    error = errors[0]
    assert error.kind == 'missing'
    assert error.placeholders == ('width',)
    assert "'width'" in str(error)


def test_python_format_incompatible_named_conversion():
    msg = Message('%(n)d', '%(n)s')
    errors = python_format(None, msg)
    assert len(errors) == 1
    error = errors[0]
    assert isinstance(error, PlaceholderError)
    assert error.kind == 'incompatible_conversion'
    assert "'n'" in str(error)


def test_python_format_repeated_positional_placeholders():
    # Two %s twice must stay balanced; an extra one is reported.
    assert python_format(None, Message('%s %s', '%s %s')) == []
    errors = python_format(None, Message('%s %s', '%s %s %s'))
    assert len(errors) == 1
    assert errors[0].kind == 'extra'
    assert 'expected 2, found 3' in str(errors[0])

    errors = python_format(None, Message('%s %s', '%s'))
    assert len(errors) == 1
    assert errors[0].kind == 'missing'
    assert 'expected 2, found 1' in str(errors[0])


def test_python_brace_format_repeated_positional_fields():
    assert python_brace_format(None, Message('{0} {0}', '{0} {0}')) == []
    errors = python_brace_format(None, Message('{0} {0}', '{0}'))
    assert errors and errors[0].kind == 'missing'
    assert errors[0].placeholders == ('0',)


def test_named_placeholders_may_be_reordered():
    assert (
        python_format(
            None,
            Message(
                '%(bar)s %(n)d',
                '%(n)d %(bar)s',
            ),
        )
        == []
    )
    assert (
        python_brace_format(
            None,
            Message(
                '{bar} {n}',
                '{n} {bar}',
            ),
        )
        == []
    )


def test_plural_branches_are_checked_individually():
    msg = Message(
        ('%(n)d thing', '%(n)d things'),
        ('%(n)s thing', '%(n)s things'),
    )
    errors = python_format(None, msg)
    assert [error.branch_index for error in errors] == [0, 1]
    for error in errors:
        assert isinstance(error, PlaceholderError)
        assert f'plural form {error.branch_index}' in str(error)
        assert error.kind == 'incompatible_conversion'


def test_plural_branch_missing_nested_field():
    msg = Message(
        ('{value:{width}.2f}', '{value:{width}.2f}'),
        ('{value:.2f}', '{value:.2f}'),
    )
    errors = python_brace_format(None, msg)
    assert [error.branch_index for error in errors] == [0, 1]
    assert {error.placeholders[0] for error in errors} == {'width'}


def test_error_messages_report_message_context():
    msg = Message('%(n)d', '%(n)s', context='things')
    errors = python_format(None, msg)
    assert len(errors) == 1
    assert errors[0].context == 'things'
    assert "message context 'things'" in str(errors[0])

    msg = Message('{n:d} {width}', '{n:d}', context='things')
    errors = python_brace_format(None, msg)
    assert len(errors) == 1
    assert errors[0].context == 'things'
    assert "message context 'things'" in str(errors[0])

    msg = Message('{n!r}', '{n!s}', context='things')
    errors = python_brace_format(None, msg)
    assert errors
    assert errors[0].context == 'things'


def test_mixed_percent_flags_are_reported():
    msg = Message('%s %(foo)s', '%s')
    errors = python_format(None, msg)
    assert len(errors) == 1
    assert errors[0].kind == 'mixed_placeholders'


def test_mixed_brace_numbering_is_reported():
    msg = Message('{} {1}', 'x')
    errors = python_brace_format(None, msg)
    assert len(errors) == 1
    assert errors[0].kind == 'mixed_placeholders'


@pytest.mark.parametrize(
    ('msgid', 'msgstr'),
    [
        ('%s', '%s %'),
        ('%s', '%'),
    ],
)
def test_bad_percent_format_strings_are_reported(msgid, msgstr):
    errors = python_format(None, Message(msgid, msgstr))
    assert errors
    assert all(error.kind == 'invalid_format' for error in errors)


@pytest.mark.parametrize(
    ('msgid', 'msgstr'),
    [
        ('{0} {x}', '{0} {1'),
        ('{x}', '{x'),
        ('{x}', '{x {y}'),
    ],
)
def test_bad_brace_format_strings_are_reported(msgid, msgstr):
    errors = python_brace_format(None, Message(msgid, msgstr))
    assert errors
    assert all(error.kind == 'invalid_format' for error in errors)


def test_escapes_are_not_placeholders():
    assert python_format(None, Message('100%% of %s', '100%% de %s')) == []
    assert python_format(None, Message('100%% done', '100%% fertig')) == []
    assert python_brace_format(None, Message('{{literal}} {x}', '{{wrtlprnft}} {x}')) == []
    assert python_brace_format(None, Message('{{x}}', '{x}')) == []


def test_message_check_collects_errors_from_all_checkers():
    msg = Message('{name}: {value:{width}.2f} %(n)d', '{name}: {value:.2f} %(n)s')
    errors = msg.check()
    kinds = {(error.branch_index, error.kind) for error in errors}
    assert (None, 'missing') in kinds
    assert (None, 'incompatible_conversion') in kinds


def test_catalog_check_results_are_in_message_order():
    catalog = Catalog()
    catalog.add('a %(n)d', 'a %(n)s')
    catalog.add('b %s %s', 'b %s')
    catalog.add('c {value:{width}.2f}', 'c {value:.2f}')

    messages_and_errors = list(catalog.check())
    assert [message.id for message, errors in messages_and_errors] == [
        'a %(n)d',
        'b %s %s',
        'c {value:{width}.2f}',
    ]


def test_brace_fields_keep_conversions_and_nested_paths():
    msg = Message('{name!r}', '{name!s}')
    errors = python_brace_format(None, msg)
    assert len(errors) == 1
    assert errors[0].kind == 'incompatible_conversion'

    msg = Message('{value:{width}}', '{value:{other}}')
    errors = python_brace_format(None, msg)
    kinds = {error.kind for error in errors}
    assert kinds == {'missing', 'extra'}
