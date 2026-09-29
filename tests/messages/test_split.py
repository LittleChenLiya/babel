#
# Copyright (C) 2013-2026 the Babel team
# All rights reserved.
#
# This software is licensed as described in the file LICENSE, which
# you should have received as part of this distribution. The terms
# are also available at https://github.com/python-babel/babel/blob/master/LICENSE.
#

import pytest

from babel.messages import Catalog, pofile
from babel.messages.split import (
    CatalogSplitError,
    MergeConflictError,
    merge_catalogs,
    path_matches_prefix,
    split_catalog,
)

GROUPS = {
    'app': 'src/app',
    'apple': 'src/apple',
}


def _base_catalog():
    catalog = Catalog(locale='de', domain='testproject')
    catalog.add('App view', 'App-Ansicht', locations=[('src/app/views.py', 10)])
    catalog.add(
        'Shared header',
        'Gemeinsamer Kopf',
        locations=[
            ('src/app/views.py', 20),
            ('src/apple/fruit.py', 30),
        ],
    )
    catalog.add('Apple fruit', 'Apfel Frucht', locations=[('src/apple/fruit.py', 40)])
    catalog.add('Lookalike', 'Verwechslung', locations=[('src/application/x.py', 1)])
    catalog.add('Nowhere', 'Nirgendwo', locations=[('other/place.py', 2)])
    catalog.add('No locations', 'Keine Fundorte')
    return catalog


def test_path_matches_prefix_is_component_wise():
    assert path_matches_prefix('src/app/views.py', 'src/app')
    assert path_matches_prefix('src/app', 'src/app')
    assert not path_matches_prefix('src/apple/fruit.py', 'src/app')
    assert not path_matches_prefix('src/app.py', 'src/app')
    assert path_matches_prefix('src\\app\\views.py', 'src/app')
    with pytest.raises(CatalogSplitError):
        path_matches_prefix('src/app', '')


def test_split_grouping_and_overlap():
    parts = split_catalog(_base_catalog(), GROUPS)

    assert set(parts) == {'app', 'apple', 'remainder'}
    assert set(parts['app']._messages) == {'App view', 'Shared header'}
    assert set(parts['apple']._messages) == {'Shared header', 'Apple fruit'}
    assert set(parts['remainder']._messages) == {
        'Lookalike',
        'Nowhere',
        'No locations',
    }

    # Messages matching several groups end up in all of them.
    assert parts['app']['Shared header'].is_identical(
        parts['apple']['Shared header'],
    )
    # The copies keep every location, nothing is lost in the split.
    assert parts['app']['Shared header'].locations == [
        ('src/app/views.py', 20),
        ('src/apple/fruit.py', 30),
    ]
    # Metadata is inherited by all parts.
    assert parts['app'].locale_identifier == 'de'
    assert parts['app'].domain == 'testproject'


def test_split_accepts_several_prefixes_and_custom_remainder():
    catalog = Catalog()
    catalog.add('A', locations=[('src/apple/fruit.py', 1)])
    catalog.add('B', locations=[('lib/app.py', 2)])
    parts = split_catalog(
        catalog,
        {'fruit': ['src/apple', 'lib']},
        remainder_name='other',
    )
    assert set(parts['fruit']._messages) == {'A', 'B'}
    assert set(parts['other']._messages) == set()
    assert 'other' in parts  # empty remainder is included by default


def test_split_validates_group_names():
    with pytest.raises(CatalogSplitError):
        split_catalog(Catalog(), {'remainder': 'src/app'})
    with pytest.raises(CatalogSplitError):
        split_catalog(Catalog(), {'app': ''})


def test_merge_identical_translations_round_trips():
    catalog = _base_catalog()
    parts = split_catalog(catalog, GROUPS)
    merged = merge_catalogs(
        {'app': parts['app'], 'apple': parts['apple'], 'rest': parts['remainder']},
    )

    assert len(merged) == len(catalog)
    for message in catalog:
        if not message.id:
            continue
        assert message.is_identical(merged[message.id])


def test_merge_round_trips_through_po_files(tmp_path):
    catalog = _base_catalog()
    parts = split_catalog(catalog, GROUPS)
    reread = {}
    for name, part in parts.items():
        path = tmp_path / f'{name}.po'
        with open(path, 'wb') as out:
            pofile.write_po(out, part)
        with open(path, 'rb') as source:
            reread[name] = pofile.read_po(source)

    merged = merge_catalogs(reread)
    assert merged['Shared header'].string == 'Gemeinsamer Kopf'
    for message in catalog:
        if not message.id:
            continue
        assert merged[message.id].string == message.string


def test_merge_rejects_conflicting_translations_without_partial_catalog():
    parts = split_catalog(_base_catalog(), GROUPS)
    parts['app']['Shared header'].string = 'A completely different translation'
    app_before = parts['app']['Shared header'].clone()
    apple_before = parts['apple']['Shared header'].clone()

    with pytest.raises(MergeConflictError) as excinfo:
        merge_catalogs(parts)
    (conflict,) = excinfo.value.conflicts
    assert conflict['key'] == 'Shared header'
    assert set(conflict['sources']) == {'app', 'apple'}
    assert 'A completely different translation' in conflict['translations']

    # Inputs are not mutated and both translations are still present.
    assert parts['app']['Shared header'].is_identical(app_before)
    assert parts['apple']['Shared header'].is_identical(apple_before)
    assert parts['app']['Shared header'].string != parts['apple']['Shared header'].string


def test_merge_allows_empty_copy_beside_translation():
    parts = split_catalog(_base_catalog(), GROUPS)
    parts['app']['Shared header'].string = ''
    merged = merge_catalogs(parts)
    assert merged['Shared header'].string == 'Gemeinsamer Kopf'


def test_merge_against_newer_template_handles_stale_messages():
    parts = split_catalog(_base_catalog(), GROUPS)

    new_template = Catalog()
    new_template.add('App view', locations=[('src/app/views.py', 11)])
    new_template.add('Shared header', locations=[('src/app/views.py', 21)])
    new_template.add('Apple fruit', locations=[('src/apple/fruit.py', 41)])
    new_template.add('Brand new message', locations=[('src/app/new.py', 1)])

    merged = merge_catalogs(parts, template=new_template)

    # Current messages keep their translations and refresh locations.
    assert merged['App view'].string == 'App-Ansicht'
    assert merged['App view'].locations == [('src/app/views.py', 11)]
    assert not merged['Brand new message'].string
    # Messages gone from the template are obsolete, not active.
    assert 'Nowhere' not in merged
    assert 'Nowhere' in merged.obsolete
    assert 'No locations' in merged.obsolete


def test_merge_against_newer_template_tracks_renamed_messages():
    parts = split_catalog(_base_catalog(), GROUPS)

    new_template = Catalog()
    new_template.add('App view', locations=[('src/app/views.py', 11)])
    new_template.add('Shared header', locations=[('src/app/views.py', 21)])
    new_template.add('Apple fruit', locations=[('src/apple/fruit.py', 41)])
    new_template.add('Apple fruity', locations=[('src/apple/fruit.py', 42)])

    merged = merge_catalogs(parts, template=new_template)

    renamed = merged['Apple fruity']
    assert renamed.string == 'Apfel Frucht'
    assert renamed.fuzzy
    assert renamed.previous_id == ['Apple fruit']


def test_merge_renamed_message_without_fuzzy_matching_is_untranslated():
    parts = split_catalog(_base_catalog(), GROUPS)
    new_template = Catalog()
    new_template.add('Apple fruity', locations=[('src/apple/fruit.py', 42)])
    merged = merge_catalogs(parts, template=new_template, no_fuzzy_matching=True)
    assert not merged['Apple fruity'].string
    assert 'Apple fruit' in merged.obsolete


def test_merge_requires_unique_nonempty_input():
    catalog = _base_catalog()
    parts = split_catalog(catalog, GROUPS)
    with pytest.raises(CatalogSplitError):
        merge_catalogs([('app', parts['app']), ('app', parts['apple'])])
    with pytest.raises(CatalogSplitError):
        merge_catalogs({})


def test_split_messages_with_context_are_supported():
    catalog = Catalog()
    catalog.add('same', 'one', context='c1', locations=[('src/app/x.py', 1)])
    catalog.add('same', 'two', context='c2', locations=[('src/apple/y.py', 2)])
    parts = split_catalog(catalog, GROUPS)
    merged = merge_catalogs(parts)
    assert merged.get('same', context='c1').string == 'one'
    assert merged.get('same', context='c2').string == 'two'
