"""Tests for babel.messages.pseudo."""

from io import BytesIO

import pytest

from babel.messages.catalog import Catalog, Message
from babel.messages.pofile import read_po, write_po
from babel.messages.pseudo import (
    END_MARKER,
    START_MARKER,
    PseudoLocalizationError,
    PseudoLocalizer,
    interpolate,
)


@pytest.fixture
def localizer():
    return PseudoLocalizer()


def unwrap(pseudo):
    assert pseudo.startswith(START_MARKER)
    assert pseudo.endswith(END_MARKER)
    return pseudo[len(START_MARKER) : -len(END_MARKER)]


def test_markers_and_accents(localizer):
    pseudo = localizer.localize('Hello')
    inner = unwrap(pseudo)
    assert inner.startswith('Ĥéľľó')
    assert len(inner) == len('Hello') + round(len('Hello') * 0.3)


def test_brace_placeholder_still_formats(localizer):
    pseudo = localizer.localize('Hello {name}')
    assert '{name}' in pseudo
    assert pseudo.format(name='Li') == pseudo.replace('{name}', 'Li')
    assert unwrap(pseudo.format(name='Li')).startswith('Ĥéľľó Li')


def test_python_format_placeholder_and_percent_escape(localizer):
    pseudo = localizer.localize('100%% done for %(name)s')
    assert '%%' in pseudo
    assert '%(name)s' in pseudo
    result = pseudo % {'name': 'Li'}
    assert '%%' not in result  # %% collapsed to a single percent
    assert '%' in result
    assert 'Li' in result


def test_percent_sign_without_conversion_is_literal(localizer):
    pseudo = localizer.localize('50% off today')
    assert '50% ' in unwrap(pseudo)


def test_nested_width_fields(localizer):
    pseudo = localizer.localize('{value:{width}.{precision}f}')
    assert '{value:{width}.{precision}f}' in pseudo
    result = pseudo.format(value=3.14159, width=8, precision=2)
    assert unwrap(result).strip() == '3.14'


def test_brace_escapes(localizer):
    pseudo = localizer.localize('{{literal}} braces')
    assert '{{' in pseudo and '}}' in pseudo  # escapes stay parseable
    assert pseudo.format() == pseudo.replace('{{', '{').replace('}}', '}')


def test_html_only_text_nodes_transformed(localizer):
    pseudo = localizer.localize("<a title='Keep'>Text</a>", html=True)
    inner = unwrap(pseudo)
    assert "title='Keep'" in inner
    assert '<a ' in inner and '</a>' in inner
    assert 'Text' not in inner
    assert 'Ţéẋţ' in inner


def test_html_entities_and_attributes_preserved(localizer):
    pseudo = localizer.localize('Fish &amp; <b class="x">Chips</b> &#169;', html=True)
    inner = unwrap(pseudo)
    assert '&amp;' in inner
    assert '&#169;' in inner
    assert 'class="x"' in inner
    assert 'Fish' not in inner and 'Chips' not in inner


def test_bad_html_does_not_crash(localizer):
    pseudo = localizer.localize('<div><span>oops', html=True)
    inner = unwrap(pseudo)
    assert '<div>' in inner and '<span>' in inner
    assert 'oops' not in inner


def test_non_latin_text_passes_through(localizer):
    pseudo = localizer.localize('你好世界')
    inner = unwrap(pseudo)
    assert inner.startswith('你好世界')
    assert len(inner) == 4 + round(4 * 0.3)


def test_idempotent(localizer):
    once = localizer.localize('Hello {name}')
    assert localizer.localize(once) == once
    html_once = localizer.localize("<a title='Keep'>Text</a>", html=True)
    assert localizer.localize(html_once, html=True) == html_once


def test_deterministic_seed():
    first = PseudoLocalizer(seed=42).localize('Hello brave new world')
    second = PseudoLocalizer(seed=42).localize('Hello brave new world')
    other = PseudoLocalizer(seed=43).localize('Hello brave new world')
    assert first == second
    assert first != other


def test_expansion_ratio():
    text = 'a' * 100
    assert len(unwrap(PseudoLocalizer(expansion=0).localize(text))) == 100
    assert len(unwrap(PseudoLocalizer(expansion=0.5).localize(text))) == 150
    with pytest.raises(ValueError):
        PseudoLocalizer(expansion=-1)


def test_plural_branches_transformed_separately(localizer):
    message = Message(('{count} file', '{count} files'), string=('', ''))
    localizer.localize_message(message)
    singular, plural = message.string
    assert unwrap(singular).startswith('{count} ')
    assert unwrap(plural).startswith('{count} ')
    assert singular != plural
    # Repeating the transformation changes nothing.
    localizer.localize_message(message)
    assert message.string == (singular, plural)


def test_untranslated_message_uses_msgid(localizer):
    message = Message('Hello {name}', string='')
    localizer.localize_message(message)
    assert message.string.format(name='Li').startswith(START_MARKER + 'Ĥéľľó Li')


def test_html_flag_detected_from_message(localizer):
    message = Message("<a title='Keep'>Text</a>", string='', flags=('html-format',))
    localizer.localize_message(message)
    assert "title='Keep'" in message.string
    assert 'Text' not in message.string


def test_errors_reported_independently(localizer):
    catalog = Catalog()
    catalog.add('good', string='good')
    broken = Message('broken', string=object())
    catalog['broken'] = broken
    catalog.add('also good', string='also good')
    errors = localizer.localize_catalog(catalog)
    assert len(errors) == 1
    assert errors[0][0] is broken
    assert isinstance(errors[0][1], PseudoLocalizationError)
    assert catalog['broken'].string is broken.string  # left untouched
    assert catalog['good'].string.startswith(START_MARKER)
    assert catalog['also good'].string.startswith(START_MARKER)


def test_catalog_idempotent(localizer):
    catalog = Catalog()
    catalog.add('Hello {name}', string='')
    catalog.add(('one thing', 'many things'), string=('', ''))
    assert localizer.localize_catalog(catalog) == []
    snapshot = {message.id: message.string for message in catalog if message.id}
    assert localizer.localize_catalog(catalog) == []
    assert {message.id: message.string for message in catalog if message.id} == snapshot


def test_po_roundtrip(localizer):
    catalog = Catalog()
    catalog.add('Hello {name}', string='')
    catalog.add('100%% done %(name)s', string='')
    catalog.add("<a title='Keep'>Text</a>", string='', flags=('html-format',))
    catalog.add(('{count} file', '{count} files'), string=('', ''))
    catalog.add('你好世界', string='')
    assert localizer.localize_catalog(catalog) == []

    buf = BytesIO()
    write_po(buf, catalog, omit_header=True)
    buf.seek(0)
    roundtripped = read_po(buf)

    for message in catalog:
        if not message.id:
            continue
        other = roundtripped[message.id]
        assert other is not None
        assert other.string == message.string
        assert other.flags == message.flags

    # The round-tripped pseudo translations still interpolate.
    assert roundtripped['Hello {name}'].string.format(name='Li')
    assert 'Li' in roundtripped['100%% done %(name)s'].string % {'name': 'Li'}


def test_interpolate():
    assert interpolate('⟦Ĥéľľó {name}⟧', {'name': 'Li'}) == '⟦Ĥéľľó Li⟧'
    assert interpolate('⟦%(name)s⟧', {'name': 'Li'}) == '⟦Li⟧'
    assert interpolate('⟦plain⟧', {}) == '⟦plain⟧'
