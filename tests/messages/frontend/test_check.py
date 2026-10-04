#
# Copyright (C) 2007-2011 Edgewall Software, 2013-2026 the Babel team
# All rights reserved.
#
# This software is licensed as described in the file LICENSE, which
# you should have received as part of this distribution. The terms
# are also available at https://github.com/python-babel/babel/blob/master/LICENSE.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at https://github.com/python-babel/babel/commits/master/.

from __future__ import annotations

import logging

import pytest

from babel.messages import frontend
from babel.messages.frontend import OptionError
from babel.messages.pofile import read_po

PO_TEMPLATE = """\
msgid ""
msgstr ""
"Content-Type: text/plain; charset={charset}\\n"

msgid "hello"
msgstr "{translation}"

msgctxt "menu"
msgid "verb"
msgstr "{context_translation}"

msgid "one thing"
msgid_plural "many things"
msgstr[0] "one"
msgstr[1] "{plural_translation}"
"""


def _write_po(tmp_path, charset='ascii', translation='hello',
              context_translation='run', plural_translation='many'):
    po_file = tmp_path / 'messages.po'
    po_file.write_text(
        PO_TEMPLATE.format(
            charset=charset,
            translation=translation,
            context_translation=context_translation,
            plural_translation=plural_translation,
        ),
        encoding='utf-8',
    )
    return po_file


def _run_cli(argv):
    return frontend.CommandLineInterface().run(argv)


def test_check_no_input_specified():
    cmd = frontend.CheckCatalog()
    cmd.initialize_options()
    with pytest.raises(OptionError):
        cmd.finalize_options()


def test_check_clean_catalog_passes(tmp_path, caplog):
    po_file = _write_po(tmp_path)
    with caplog.at_level(logging.INFO, logger='babel'):
        assert _run_cli(['pybabel', 'check', '-i', str(po_file)]) == 0
    assert 'encodable' in caplog.text
    assert 'error' not in caplog.text


def test_check_reports_unencodable_slots(tmp_path, caplog):
    # The PO file itself is UTF-8 (so it can be read), but compiling it
    # with an ASCII charset would fail; --charset checks that up front.
    po_file = _write_po(
        tmp_path,
        charset='utf-8',
        translation='你好',
        context_translation='跑',
        plural_translation='许多',
    )
    with caplog.at_level(logging.ERROR, logger='babel'):
        assert _run_cli([
            'pybabel', 'check', '-i', str(po_file), '--charset', 'ascii',
        ]) == 1
    text = caplog.text
    assert 'msgstr' in text
    assert 'msgstr[1]' in text
    assert 'position 0' in text
    assert "'hello'" in text
    assert "'verb'" in text
    assert 'encoding errors encountered' in text


def test_check_charset_override(tmp_path, caplog):
    po_file = _write_po(tmp_path, charset='utf-8', translation='你好')
    with caplog.at_level(logging.INFO, logger='babel'):
        assert _run_cli(['pybabel', 'check', '-i', str(po_file)]) == 0
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger='babel'):
        assert _run_cli([
            'pybabel', 'check', '-i', str(po_file), '--charset', 'ascii',
        ]) == 1
    assert 'msgstr' in caplog.text
    # The catalog on disk is untouched, and re-reading still shows utf-8.
    with open(po_file, 'rb') as f:
        assert read_po(f).charset == 'utf-8'


def test_check_fuzzy_not_an_error_by_default(tmp_path, caplog):
    po_file = tmp_path / 'messages.po'
    po_file.write_text(
        'msgid ""\n'
        'msgstr ""\n'
        '"Content-Type: text/plain; charset=utf-8\\n"\n'
        '\n'
        '#, fuzzy\n'
        'msgid "fuzzy one"\n'
        'msgstr "模糊"\n',
        encoding='utf-8',
    )
    with caplog.at_level(logging.INFO, logger='babel'):
        assert _run_cli([
            'pybabel', 'check', '-i', str(po_file), '--charset', 'ascii',
        ]) == 0
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger='babel'):
        assert _run_cli([
            'pybabel', 'check', '-f', '-i', str(po_file), '--charset', 'ascii',
        ]) == 1
    assert 'msgstr' in caplog.text
