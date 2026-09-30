#
# Copyright (C) 2026 the Babel team
# All rights reserved.
#
# This software is licensed as described in the file LICENSE, which
# you should have received as part of this distribution.
#

import pytest

from babel.messages import Catalog
from babel.messages.pofile import read_po, write_po
from babel.messages.splitmerge import (
    MergeConflictError,
    SplitMergeError,
    merge_catalogs,
    split_catalog,
)


def _base_catalog():
    catalog = Catalog(locale='de_DE', domain='messages', project='Proj', version='1.0')
    catalog.add(
        'App title',
        'App-Titel',
        locations=[
            ('src/app/views.py', 1),
            ('src/apple/fruit.py', 2),
        ],
    )
    catalog.add(
        'Shared string',
        'Geteilt',
        locations=[
            ('src/app/shared.py', 3),
            ('src/apple/shared.py', 4),
        ],
    )
    catalog.add('Ungrouped', 'Au\xdferhalb', locations=[('tools/helper.py', 5)])
    return catalog


def _ids(catalog):
    return {message.id for message in catalog if message.id}


def test_split_groups_by_path_components():
    catalog = _base_catalog()
    parts = split_catalog(catalog, {'app': 'src/app', 'apple': 'src/apple'})

    assert list(parts) == ['app', 'apple', 'remainder']
    assert _ids(parts['app']) == {'App title', 'Shared string'}
    assert _ids(parts['apple']) == {'App title', 'Shared string'}
    assert _ids(parts['remainder']) == {'Ungrouped'}


def test_split_matches_path_component_boundaries():
    catalog = Catalog()
    catalog.add('in-app', locations=[('src/app/views.py', 1)])
    catalog.add('in-apple', locations=[('src/apple/fruit.py', 2)])
    catalog.add('in-application', locations=[('src/application/main.py', 3)])
    catalog.add('dot-prefix', locations=[('./src/app/relative.py', 4)])
    catalog.add('backslash', locations=[('src\\app\\other.py', 5)])

    parts = split_catalog(catalog, {'app': 'src/app'})

    assert _ids(parts['app']) == {'in-app', 'dot-prefix', 'backslash'}
    assert _ids(parts['remainder']) == {'in-apple', 'in-application'}


def test_split_message_in_several_groups_is_cloned():
    catalog = _base_catalog()
    parts = split_catalog(catalog, {'app': 'src/app', 'apple': 'src/apple'})

    app_message = parts['app']['Shared string']
    apple_message = parts['apple']['Shared string']
    assert app_message is not apple_message
    assert app_message.is_identical(catalog['Shared string'])
    assert apple_message.is_identical(catalog['Shared string'])

    app_message.string = 'changed'
    assert parts['apple']['Shared string'].string == 'Geteilt'
    assert catalog['Shared string'].string == 'Geteilt'


def test_split_accepts_several_prefixes_per_group():
    catalog = Catalog()
    catalog.add('one', locations=[('src/app/a.py', 1)])
    catalog.add('two', locations=[('pkg/apple/b.py', 2)])

    parts = split_catalog(catalog, {'team': ['src/app', 'pkg/apple']})

    assert _ids(parts['team']) == {'one', 'two'}
    assert _ids(parts['remainder']) == set()


def test_split_rejects_remainder_name_clash():
    catalog = Catalog()
    with pytest.raises(SplitMergeError):
        split_catalog(catalog, {'leftovers': 'src'}, remainder_name='leftovers')


def test_split_rejects_invalid_prefix():
    catalog = Catalog()
    with pytest.raises(SplitMergeError):
        split_catalog(catalog, {'bad': 'src/../app'})
    with pytest.raises(SplitMergeError):
        split_catalog(catalog, {'bad': '/'})


def test_merge_identical_translations_roundtrips():
    catalog = _base_catalog()
    parts = split_catalog(catalog, {'app': 'src/app', 'apple': 'src/apple'})

    merged = merge_catalogs(parts)

    for message in catalog:
        if not message.id:
            continue
        merged_message = merged[message.id]
        assert merged_message.is_identical(message)


def test_merge_accepts_single_translation_for_duplicated_message():
    catalog = _base_catalog()
    parts = split_catalog(catalog, {'app': 'src/app', 'apple': 'src/apple'})
    parts['apple']['Shared string'].string = ''

    merged = merge_catalogs(parts)

    assert merged['Shared string'].string == 'Geteilt'

    # The translation may also live in a later catalog, regardless of order.
    parts['apple']['Shared string'].string = 'Geteilt'
    parts['app']['Shared string'].string = ''
    merged = merge_catalogs(list(parts.values()))
    assert merged['Shared string'].string == 'Geteilt'


def test_merge_raises_on_conflicting_translations():
    catalog = _base_catalog()
    parts = split_catalog(catalog, {'app': 'src/app', 'apple': 'src/apple'})
    parts['apple']['Shared string'].string = 'Anders'
    parts['app']['App title'].string = 'A-Titel'
    parts['apple']['App title'].string = 'B-Titel'

    with pytest.raises(MergeConflictError) as exc_info:
        merge_catalogs(parts)

    conflicts = {conflict.key: conflict for conflict in exc_info.value.conflicts}
    assert set(conflicts) == {'Shared string', 'App title'}
    assert conflicts['Shared string'].translations == ['Geteilt', 'Anders']
    assert conflicts['Shared string'].sources == ['app', 'apple']
    assert parts['app']['Shared string'].string == 'Geteilt'


def test_merge_conflict_does_not_mutate_inputs_or_return_partial_catalog():
    catalog = _base_catalog()
    parts = split_catalog(catalog, {'app': 'src/app', 'apple': 'src/apple'})
    before = {name: list(catalog_) for name, catalog_ in parts.items()}
    parts['apple']['Shared string'].string = 'Anders'

    with pytest.raises(MergeConflictError) as exc_info:
        merge_catalogs(parts)

    assert not hasattr(exc_info.value, 'partial')
    for name, catalog_ in parts.items():
        assert [message.id for message in catalog_ if message.id] == [
            message.id for message in before[name] if message.id
        ]


def test_merge_with_stale_baseline_updates_locations_and_obsoletes_messages():
    catalog = _base_catalog()
    parts = split_catalog(catalog, {'app': 'src/app', 'apple': 'src/apple'})

    baseline = Catalog(locale='de_DE', domain='messages', project='Proj', version='1.1')
    baseline.add('App title', locations=[('src/app/views.py', 10)])
    baseline.add(
        'Shared string',
        locations=[
            ('src/app/shared.py', 30),
            ('src/apple/shared.py', 40),
        ],
    )
    baseline.add('Fresh message', locations=[('src/app/new.py', 1)])

    merged = merge_catalogs(parts, baseline=baseline)

    assert merged['App title'].locations == [('src/app/views.py', 10)]
    assert merged['Shared string'].locations == [
        ('src/app/shared.py', 30),
        ('src/apple/shared.py', 40),
    ]
    assert merged['App title'].string == 'App-Titel'
    assert merged['Shared string'].string == 'Geteilt'
    assert not merged['Fresh message'].string
    assert set(merged.obsolete) == {'Ungrouped'}


def test_merge_with_renamed_message_follows_fuzzy_match():
    catalog = _base_catalog()
    parts = split_catalog(catalog, {'app': 'src/app', 'apple': 'src/apple'})

    baseline = Catalog(locale='de_DE', domain='messages', project='Proj', version='1.1')
    baseline.add(
        'Shared string (renamed)',
        locations=[
            ('src/app/shared.py', 3),
            ('src/apple/shared.py', 4),
        ],
    )

    merged = merge_catalogs(parts, baseline=baseline)

    renamed = merged['Shared string (renamed)']
    assert renamed.string == 'Geteilt'
    assert renamed.fuzzy
    assert renamed.previous_id == ['Shared string']
    assert 'Shared string' not in merged


def test_merge_conflicts_checked_against_baseline_before_update():
    catalog = _base_catalog()
    parts = split_catalog(catalog, {'app': 'src/app', 'apple': 'src/apple'})
    parts['apple']['Shared string'].string = 'Anders'

    baseline = Catalog(locale='de_DE', domain='messages', project='Proj', version='1.1')
    baseline.add('Completely different', locations=[('elsewhere/x.py', 1)])

    with pytest.raises(MergeConflictError):
        merge_catalogs(parts, baseline=baseline)


def test_merge_plural_conflict():
    first = Catalog(locale='de_DE')
    first.add(('One thing', '%(count)d things'), ('Ein Ding', '%(count)d Dinge'))
    second = Catalog(locale='de_DE')
    second.add(('One thing', '%(count)d things'), ('Ein Ding', '%(count)d Sachen'))

    with pytest.raises(MergeConflictError) as exc_info:
        merge_catalogs({'first': first, 'second': second})

    (conflict,) = exc_info.value.conflicts
    assert conflict.translations == [
        ('Ein Ding', '%(count)d Dinge'),
        ('Ein Ding', '%(count)d Sachen'),
    ]


def test_merge_contextual_messages_conflict_by_id_and_context():
    first = Catalog(locale='de_DE')
    first.add('Same id', 'Erstens', context='one')
    first.add('Same id', 'Zweitens', context='two')
    second = Catalog(locale='de_DE')
    second.add('Same id', 'Erstens anders', context='one')
    second.add('Same id', 'Zweitens', context='two')

    with pytest.raises(MergeConflictError) as exc_info:
        merge_catalogs({'first': first, 'second': second})

    (conflict,) = exc_info.value.conflicts
    assert conflict.key == ('Same id', 'one')


def test_merge_requires_at_least_one_catalog():
    with pytest.raises(SplitMergeError):
        merge_catalogs([])


def test_merge_accepts_iterable_of_catalogs():
    catalog = _base_catalog()
    parts = split_catalog(catalog, {'app': 'src/app', 'apple': 'src/apple'})

    merged = merge_catalogs(list(parts.values()))

    assert merged['Shared string'].string == 'Geteilt'


def test_po_roundtrip_and_conflict_writes_no_partial_output(tmp_path):
    catalog = _base_catalog()
    parts = split_catalog(catalog, {'app': 'src/app', 'apple': 'src/apple'})

    part_paths = []
    for name, part in parts.items():
        path = tmp_path / f'{name}.po'
        with open(path, 'wb') as outfile:
            write_po(outfile, part)
        part_paths.append((name, path))

    loaded = {}
    for name, path in part_paths:
        with open(path, encoding='utf-8') as infile:
            loaded[name] = read_po(infile)
    merged = merge_catalogs(loaded)

    output_path = tmp_path / 'merged.po'
    with open(output_path, 'wb') as outfile:
        write_po(outfile, merged)
    with open(output_path, encoding='utf-8') as infile:
        on_disk = read_po(infile)
    assert on_disk['Shared string'].string == 'Geteilt'

    loaded['apple']['Shared string'].string = 'Anders'
    conflict_path = tmp_path / 'conflict.po'
    with pytest.raises(MergeConflictError):
        merge_catalogs(loaded)
    assert not conflict_path.exists()

    with open(conflict_path, 'wb') as outfile:
        with pytest.raises(MergeConflictError):
            write_po(outfile, merge_catalogs(loaded))
    assert conflict_path.stat().st_size == 0
