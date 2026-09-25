"""Tests for the `pybabel pseudo` frontend command."""

import pathlib

import pytest

from babel.messages import frontend, pofile
from babel.messages.frontend import OptionError
from babel.messages.pseudo import END_MARKER, START_MARKER


@pytest.fixture
def pot_file(tmp_path: pathlib.Path):
    pot = tmp_path / "messages.pot"
    pot.write_text(
        '#, python-brace-format\n'
        'msgid "Hello {name}"\n'
        'msgstr ""\n'
        '\n'
        '#, html-format\n'
        'msgid "<a title=\'Keep\'>Text</a>"\n'
        'msgstr ""\n'
        '\n'
        'msgid "{count} file"\n'
        'msgid_plural "{count} files"\n'
        'msgstr[0] ""\n'
        'msgstr[1] ""\n',
        encoding='utf-8',
    )
    return pot


def run_pseudo(*args):
    cmd = frontend.PseudoLocalizeCatalog()
    cmd.initialize_options()
    for name, value in args:
        setattr(cmd, name, value)
    cmd.ensure_finalized()
    return cmd


def test_pseudo_command(pot_file, tmp_path):
    out = tmp_path / 'messages.pseudo.po'
    cmd = run_pseudo(('input_file', str(pot_file)), ('output_file', str(out)))
    assert cmd.run() == 0

    with open(out, 'rb') as infile:
        catalog = pofile.read_po(infile)
    hello = catalog['Hello {name}']
    assert hello.string.startswith(START_MARKER + 'Ĥéľľó {name}')
    assert hello.string.format(name='Li').endswith(END_MARKER)
    html = catalog["<a title='Keep'>Text</a>"]
    assert "title='Keep'" in html.string
    assert 'Text' not in html.string
    plural = catalog[('{count} file', '{count} files')]
    assert all(branch.startswith(START_MARKER) for branch in plural.string)
    assert plural.string[0] != plural.string[1]


def test_pseudo_command_idempotent(pot_file, tmp_path):
    first = tmp_path / 'first.po'
    second = tmp_path / 'second.po'
    run_pseudo(('input_file', str(pot_file)), ('output_file', str(first))).run()
    run_pseudo(('input_file', str(first)), ('output_file', str(second))).run()
    assert first.read_bytes() == second.read_bytes()


def test_pseudo_command_requires_input():
    cmd = frontend.PseudoLocalizeCatalog()
    cmd.initialize_options()
    with pytest.raises(OptionError):
        cmd.ensure_finalized()


def test_pseudo_command_invalid_options(pot_file):
    with pytest.raises(OptionError):
        run_pseudo(('input_file', str(pot_file)), ('expansion', 'wide'))
    with pytest.raises(OptionError):
        run_pseudo(('input_file', str(pot_file)), ('seed', 'not-an-int'))
