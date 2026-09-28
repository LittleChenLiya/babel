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
from babel.messages import Message, checkers
from babel.messages import catalog as catalog_module
from babel.messages.catalog import TranslationError
from babel.messages.checkers import (
    _check_brace_string,
    _check_percent_string,
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
        (('foo %s', 'bar'), ('foo')),
        (('foo %s', 'bar %d'), ('foo %s', 'bar %d', 'baz')),
        (('foo %s', 'bar %d'), ('foo %s', 'bar %d', 'baz %d', 'qux')),
    ],
)
def test_python_format_invalid(msgid, msgstr):
    msg = Message(msgid, msgstr)
    with pytest.raises(TranslationError):
        python_format(None, msg)


@pytest.mark.parametrize(
    ('msgid', 'msgstr'),
    [
        ('foo', 'foo'),
        ('foo', 'foo %s'),
        ('foo %s', ''),
        (('foo %s', 'bar %d'), ('foo %s', 'bar %d')),
        (('foo %s', 'bar %d'), ('foo %s', 'bar %d', 'baz %d')),
        (('foo', 'bar %s'), ('foo')),
        (('foo', 'bar %s'), ('', '')),
        (('foo', 'bar %s'), ('foo', '')),
        (('foo %s', 'bar %d'), ('foo %s', '')),
    ],
)
def test_python_format_valid(msgid, msgstr):
    msg = Message(msgid, msgstr)
    python_format(None, msg)


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


@pytest.mark.parametrize(
    ('msgid', 'msgstr', 'error'),
    [
        # missing named placeholder, including one nested in a format spec
        (
            '{name}: {value:{width}.2f}',
            '{name}: {value.2f}',
            "missing named placeholder 'width'",
        ),
        ('{a} {b}', '{a}', "missing named placeholder 'b'"),
        # extra named placeholder
        ('{a}', '{a} {b}', "extra named placeholder 'b'"),
        # nested attribute/item access resolves against the named parameter
        ('{x[0]}', '{x.y}', None),
        # incompatible conversion
        ('{a!r}', '{a!s}', "incompatible conversion for placeholder 'a'"),
        # missing and extra positional placeholders
        ('{} {}', '{}', 'missing positional placeholder 2'),
        ('{0} {0}', '{0} {1}', 'extra positional placeholder 2'),
        # escaped braces are not placeholders
        ('{{literal}} {name}', '{{}} {name}', None),
        ('{name}', '{{oops}}', "missing named placeholder 'name'"),
        # malformed format strings
        ('{name', '{name}', 'malformed brace-format string'),
        ('{name}', '}name', 'malformed brace-format string'),
        ('{} {0}', '{} {0}', 'cannot switch from automatic field numbering'),
    ],
)
def test__check_brace_string(msgid, msgstr, error):
    problems = _check_brace_string(msgid, msgstr)
    if error is None:
        assert problems == []
    else:
        assert any(error in problem for problem in problems)


@pytest.mark.parametrize(
    ('msgid', 'msgstr'),
    [
        # named placeholders may be reordered
        ('{a} {b}', '{b} {a}'),
        # repeated positional placeholders need no extra arguments
        ('{0} {0}', '{0} {0}'),
        ('{0} {1} {0}', '{1} {0} {0}'),
        # default (no) conversion is compatible with the explicit ``s`` one
        ('{a}', '{a!s}'),
        # automatic and explicit numbering with equal slots are compatible
        ('{} {}', '{0} {1}'),
        # escaped doubled braces are literal text
        ('{{}} {}', '{{}} {}'),
        ('{name}: {value:{width}.2f}', '{value:{width}.2f}: {name}'),
    ],
)
def test__check_brace_string_valid(msgid, msgstr):
    assert _check_brace_string(msgid, msgstr) == []


@pytest.mark.parametrize(
    ('msgid', 'msgstr'),
    [
        # missing and extra named percent placeholders
        ('%(a)s %(b)s', '%(a)s'),
        ('%(a)s', '%(a)s %(b)s'),
        # malformed percent sequences, escaped %% is fine
        ('100 %%', '100 %'),
    ],
)
def test_python_format_contract_invalid(msgid, msgstr):
    msg = Message(msgid, msgstr)
    with pytest.raises(TranslationError):
        python_format(None, msg)


@pytest.mark.parametrize(
    ('msgid', 'msgstr'),
    [
        # named placeholders may be reordered
        ('%(bar)s foo %(n)d', '%(n)d foo %(bar)s'),
        # repeated positional placeholders are fine
        ('%s %s', '%s %s'),
        # doubled percent signs are escapes, not placeholders
        ('100%%', '100 %%'),
    ],
)
def test_python_format_contract_valid(msgid, msgstr):
    msg = Message(msgid, msgstr)
    python_format(None, msg)


def test_percent_contract_reports_incompatible_conversion():
    msg = Message('%(n)d', '%(n)s')
    with pytest.raises(TranslationError, match="placeholder 'n'"):
        python_format(None, msg)
    assert _check_percent_string('%(n)d', '%(n)s')


def test_brace_format_checker_ignores_non_brace_messages():
    msg = Message('%(name)s', '%(name)s')
    python_brace_format(None, msg)  # no exception


def test_plural_branch_index_is_reported():
    msgid = ('{name}: {value:{width}.2f}', '{name}: {value:{width}.2f}')
    # branch 0 misses width, branch 1 has an extra placeholder
    msg = Message(msgid, ('{name}: {value.2f}', '{name}: {value:{width}.2f} {extra}'))
    with pytest.raises(TranslationError) as exc_info:
        python_brace_format(None, msg)
    message = str(exc_info.value)
    assert "plural branch 0: missing named placeholder 'width'" in message
    assert "plural branch 1: extra named placeholder 'extra'" in message


def test_context_and_branch_are_reported():
    msgid = ('{value:{width}.2f}', '{value:{width}.2f}')
    msg = Message(msgid, ('{value.2f}', '{value.2f}'), context='measurements')
    with pytest.raises(TranslationError) as exc_info:
        python_brace_format(None, msg)
    message = str(exc_info.value)
    assert "context 'measurements' plural branch 0" in message
    assert "context 'measurements' plural branch 1" in message


def test_percent_plural_branches_are_reported():
    msgid = ('%(count)d item', '%(count)d items')
    msg = Message(msgid, ('%(count)s item', ''))
    with pytest.raises(TranslationError) as exc_info:
        python_format(None, msg)
    assert "plural branch 0:" in str(exc_info.value)
    assert "plural branch 1:" not in str(exc_info.value)


def test_message_with_mixed_flags_runs_both_checkers():
    # the string is flagged both as percent- and brace-format
    msg = Message('%(n)d {name}', '%(n)s {name}',
                  flags=['python-format', 'python-brace-format'])
    errors = msg.check()
    messages = '\n'.join(str(error) for error in errors)
    # the brace checker is happy while the percent checker flags the conversion
    assert any("placeholder 'n'" in str(error) for error in errors)
    assert "missing named placeholder 'name'" not in messages


def test_catalog_check_reports_problems_in_message_order():
    catalog = catalog_module.Catalog()
    catalog.add('aaa {width}', 'aaa')
    catalog.add('mmm {width}', 'mmm')
    catalog.add('zzz {width}', 'zzz')
    checked = list(catalog.check())
    assert [message.id for message, _errors in checked] == [
        'aaa {width}',
        'mmm {width}',
        'zzz {width}',
    ]
    for _message, errors in checked:
        assert any('missing' in str(error) for error in errors)


def test_checkers_are_registered():
    assert checkers.python_brace_format in checkers.checkers
    assert checkers.python_format in checkers.checkers
    assert checkers.num_plurals in checkers.checkers
