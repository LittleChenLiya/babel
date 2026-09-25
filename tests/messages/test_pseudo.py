#
# Copyright (C) 2013-2025 the Babel team
# All rights reserved.
#
# This software is licensed as described in the file LICENSE, which
# you should have received as part of this distribution. The terms
# are also available at https://github.com/python-babel/babel/blob/master/LICENSE.
from __future__ import annotations

import io

import pytest

from babel.messages import Catalog, pofile
from babel.messages.pseudo import (
    MARKER_END,
    MARKER_START,
    PseudoTransformError,
    interpolate_sample,
    is_marked,
    pseudo_localize_catalog,
    pseudo_transform,
    pseudo_transform_string,
)


def test_brace_placeholder_preserved_and_formattable():
    result = pseudo_transform("Hello {name}")
    assert result.startswith(MARKER_START)
    assert result.endswith(MARKER_END)
    assert "{name}" in result
    formatted = result.format(name="Li")
    assert "Li" in formatted
    assert formatted != result


def test_python_format_placeholder_preserved():
    result = pseudo_transform("Hello %(name)s, you have %(count)d messages")
    assert "%(name)s" in result
    assert "%(count)d" in result
    formatted = result % {"name": "Li", "count": 3}
    assert "Li" in formatted
    assert "3" in formatted


def test_percent_escape_preserved():
    result = pseudo_transform("Progress: %(count)d%%")
    assert "%%" in result
    formatted = result % {"count": 50}
    assert "50%" in formatted
    assert "%%" not in formatted


def test_positional_percent_placeholder_preserved():
    result = pseudo_transform("Hello %s")
    assert "%s" in result
    assert "Li" in (result % "Li")


def test_nested_width_field_preserved():
    result = pseudo_transform("{name:{width}}")
    assert "{name:{width}}" in result
    assert result.format(name="Li", width=6) == f"{MARKER_START}Li    {MARKER_END}"


def test_escaped_braces_preserved():
    result = pseudo_transform("Use {{braces}} here")
    assert "{{" in result
    assert "}}" in result
    # the escaped braces survive .format() as literal braces
    formatted = result.format()
    assert "{" in formatted
    assert "}" in formatted


def test_html_only_text_nodes_transformed():
    result = pseudo_transform("<a title='Keep'>Text</a>")
    assert "<a title='Keep'>" in result
    assert "</a>" in result
    assert "Text" not in result  # the text node was transformed
    assert "Keep" in result  # the attribute value was kept


def test_html_entities_preserved():
    result = pseudo_transform("<p>Fish &amp; Chips &#169;</p>")
    assert "&amp;" in result
    assert "&#169;" in result
    assert "Fish" not in result


def test_html_forced_and_disabled():
    text = "<b>Hi</b>"
    assert "<b>" in pseudo_transform(text, html=True)
    assert "<b>" not in pseudo_transform(text, html=False)


def test_bad_html_raises():
    with pytest.raises(PseudoTransformError):
        pseudo_transform("<b>oops</i>")
    with pytest.raises(PseudoTransformError):
        pseudo_transform("<div>never closed")


def test_idempotent_single_message():
    for text in (
        "Hello {name}",
        "<a title='Keep'>Text</a>",
        "Progress: %(count)d%%",
        "{name:{width}}",
        "你好世界",
    ):
        once = pseudo_transform(text)
        twice = pseudo_transform(once)
        assert twice == once
        assert is_marked(once)


def test_idempotent_catalog():
    catalog = Catalog()
    catalog.add("Hello {name}")
    catalog.add("<a title='Keep'>Text</a>")
    catalog.add(("One file", "{count} files"))
    pseudo_localize_catalog(catalog)
    snapshot = {message.id: message.string for message in catalog if message.id}
    pseudo_localize_catalog(catalog)
    for message in catalog:
        if message.id:
            assert message.string == snapshot[message.id]


def test_plurals_transformed_independently():
    singular, plural = pseudo_transform_string(("One file", "{count} files"))
    assert is_marked(singular)
    assert is_marked(plural)
    assert singular != plural
    assert "{count}" in plural
    assert "3" in plural.format(count=3)


def test_non_latin_text_passthrough():
    result = pseudo_transform("你好世界")
    assert "你好世界" in result
    assert is_marked(result)


def test_expansion_ratio_changes_length():
    text = "This is a fairly long message that should be expanded visibly."
    small = pseudo_transform(text, expansion=0.1)
    large = pseudo_transform(text, expansion=0.5)
    assert len(large) > len(small) > len(text)


def test_fixed_seed_is_deterministic():
    text = "A long enough message to get padding characters appended."
    assert pseudo_transform(text, seed=42) == pseudo_transform(text, seed=42)
    assert pseudo_transform(text, seed=1) != pseudo_transform(text, seed=2)


def test_error_reported_independently_per_message():
    catalog = Catalog()
    catalog.add("Good message", string="Good message")
    catalog.add("<b>broken</i>", string="<b>broken</i>")
    catalog.add("Another good one", string="Another good one")
    errors = pseudo_localize_catalog(catalog)
    assert len(errors) == 1
    assert errors[0][0] == "<b>broken</i>"
    # the broken message is left unchanged, the rest of the catalog is fine
    assert catalog["<b>broken</i>"].string == "<b>broken</i>"
    assert is_marked(catalog["Good message"].string)
    assert is_marked(catalog["Another good one"].string)


def test_po_roundtrip():
    catalog = Catalog(project="TestProject", version="1.0")
    catalog.add("Hello {name}")
    catalog.add("<a title='Keep'>Text</a>")
    catalog.add(("One file", "{count} files"))
    catalog.add("Progress: %(count)d%%")
    errors = pseudo_localize_catalog(catalog, expansion=0.4, seed=7)
    assert errors == []

    buf = io.BytesIO()
    pofile.write_po(buf, catalog)
    buf.seek(0)
    roundtripped = pofile.read_po(buf)

    for message in roundtripped:
        if not message.id:
            continue
        original = catalog[message.id]
        assert message.string == original.string

    hello = roundtripped["Hello {name}"].string
    assert "Li" in hello.format(name="Li")
    html = roundtripped["<a title='Keep'>Text</a>"].string
    assert "title='Keep'" in html
    plural = roundtripped[("One file", "{count} files")].string
    assert len(plural) == 2
    assert "3" in plural[1].format(count=3)


def test_interpolate_sample():
    assert "Li" in interpolate_sample(pseudo_transform("Hello {name}"))
    assert "Li " in interpolate_sample(pseudo_transform("{name:{width}}"))
    assert "3%" in interpolate_sample(pseudo_transform("Progress: %(count)d%%"))

def _write_pot(path):
    catalog = Catalog(project="TestProject", version="1.0")
    catalog.add("Hello {name}")
    catalog.add("<a title='Keep'>Text</a>")
    catalog.add(("One file", "{count} files"))
    with open(path, "wb") as fileobj:
        pofile.write_po(fileobj, catalog)


def test_cli_pseudo_command(tmp_path):
    from babel.messages import frontend

    pot = tmp_path / "messages.pot"
    _write_pot(pot)
    out = tmp_path / "messages-pseudo.po"

    cli = frontend.CommandLineInterface()
    cli.run(["pybabel", "pseudo", "-i", str(pot), "-o", str(out)])

    with open(out, "rb") as fileobj:
        catalog = pofile.read_po(fileobj)
    assert is_marked(catalog["Hello {name}"].string)
    assert "Li" in catalog["Hello {name}"].string.format(name="Li")
    html = catalog["<a title='Keep'>Text</a>"].string
    assert "title='Keep'" in html
    assert "Text" not in html
    plural = catalog[("One file", "{count} files")].string
    assert all(is_marked(branch) for branch in plural)

    # running the command again on its own output is idempotent
    out2 = tmp_path / "messages-pseudo-2.po"
    cli.run(["pybabel", "pseudo", "-i", str(out), "-o", str(out2)])
    with open(out2, "rb") as fileobj:
        catalog2 = pofile.read_po(fileobj)
    for message in catalog2._messages.values():
        if message.id:
            assert message.string == catalog[message.id].string


def test_cli_pseudo_compare(tmp_path, capsys):
    from babel.messages import frontend

    pot = tmp_path / "messages.pot"
    _write_pot(pot)

    cli = frontend.CommandLineInterface()
    cli.run(["pybabel", "pseudo", "-i", str(pot), "--compare"])
    captured = capsys.readouterr()
    assert "msgid: 'Hello {name}'" in captured.out
    assert "pseudo:" in captured.out
    assert "sample:" in captured.out
    assert MARKER_START in captured.out
