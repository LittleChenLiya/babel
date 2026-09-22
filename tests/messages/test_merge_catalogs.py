import io
import json

from babel.messages import Catalog, pofile
from babel.messages.catalog import CatalogMergeResult, Message, merge_catalogs


def test_returns_named_result():
    result = merge_catalogs(Catalog(locale='de'), Catalog(locale='de'), Catalog(locale='de'))
    assert isinstance(result, CatalogMergeResult)
    assert result.catalog is result[0]
    assert result.conflicts is result[1]


def _conflicts_for(conflicts, msgid, field=None, context=None):
    result = [c for c in conflicts if c['msgid'] == msgid and c['context'] == context]
    if field is not None:
        result = [c for c in result if c['field'] == field]
    return result


def test_unchanged_messages_keep_base():
    base = Catalog(locale='de')
    base.add('green', 'gruen', locations=[('a.py', 1)], user_comments=['hello'])
    local = Catalog(locale='de')
    local.add('green', 'gruen', locations=[('a.py', 1)], user_comments=['hello'])
    incoming = Catalog(locale='de')
    incoming.add('green', 'gruen', locations=[('a.py', 1)], user_comments=['hello'])

    result, conflicts = merge_catalogs(base, local, incoming)
    assert result['green'].string == 'gruen'
    assert conflicts == []


def test_only_one_side_modifies():
    base = Catalog(locale='de')
    base.add('green', '')
    local = Catalog(locale='de')
    local.add('green', 'gruen')
    incoming = Catalog(locale='de')
    incoming.add('green', '')

    result, conflicts = merge_catalogs(base, local, incoming)
    assert result['green'].string == 'gruen'
    assert conflicts == []

    result, conflicts = merge_catalogs(base, incoming, local)
    assert result['green'].string == 'gruen'
    assert conflicts == []


def test_both_sides_same_change_merges():
    base = Catalog(locale='de')
    base.add('green', 'alt')
    local = Catalog(locale='de')
    local.add('green', 'gruen')
    incoming = Catalog(locale='de')
    incoming.add('green', 'gruen')

    result, conflicts = merge_catalogs(base, local, incoming)
    assert result['green'].string == 'gruen'
    assert conflicts == []


def test_different_translations_conflict_keeps_local():
    base = Catalog(locale='de')
    base.add('green', 'base')
    local = Catalog(locale='de')
    local.add('green', 'lokal')
    incoming = Catalog(locale='de')
    incoming.add('green', 'extern')

    result, conflicts = merge_catalogs(base, local, incoming)
    assert result['green'].string == 'lokal'
    (conflict,) = _conflicts_for(conflicts, 'green')
    assert conflict['field'] == 'translation'
    assert (conflict['base'], conflict['local'], conflict['incoming']) == (
        'base',
        'lokal',
        'extern',
    )
    json.dumps(conflicts)


def test_plural_slots_merge_independently():
    base = Catalog(locale='de')
    base.add(('apple', 'apples'), ('a-base', 'b-base'))
    local = Catalog(locale='de')
    local.add(('apple', 'apples'), ('a-local', 'b-base'))
    incoming = Catalog(locale='de')
    incoming.add(('apple', 'apples'), ('a-base', 'b-incoming'))

    result, conflicts = merge_catalogs(base, local, incoming)
    assert result[('apple', 'apples')].string == ('a-local', 'b-incoming')
    assert conflicts == []


def test_conflicting_plural_slot_is_reported_with_index():
    base = Catalog(locale='de')
    base.add(('apple', 'apples'), ('base0', 'base1'))
    local = Catalog(locale='de')
    local.add(('apple', 'apples'), ('local0', 'base1'))
    incoming = Catalog(locale='de')
    incoming.add(('apple', 'apples'), ('incoming0', 'base1'))

    result, conflicts = merge_catalogs(base, local, incoming)
    assert result[('apple', 'apples')].string == ('local0', 'base1')
    (conflict,) = _conflicts_for(conflicts, ('apple', 'apples'))
    assert conflict['plural_index'] == 0
    assert conflict['local'] == 'local0'
    assert conflict['incoming'] == 'incoming0'


def test_context_distinguishes_messages():
    base = Catalog(locale='de')
    base.add('read', 'base-noctx')
    base.add('read', 'base-ctx', context='verb')
    local = Catalog(locale='de')
    local.add('read', 'local-noctx')
    local.add('read', 'base-ctx', context='verb')
    incoming = Catalog(locale='de')
    incoming.add('read', 'base-noctx')
    incoming.add('read', 'incoming-ctx', context='verb')

    result, conflicts = merge_catalogs(base, local, incoming)
    assert result.get('read').string == 'local-noctx'
    assert result.get('read', context='verb').string == 'incoming-ctx'
    assert conflicts == []


def test_singular_and_plural_same_singular_stay_separate():
    base = Catalog(locale='de')
    base.add('file', 'base-singular')
    base.add(('folder', 'folders'), ('base-one', 'base-other'))
    local = Catalog(locale='de')
    local.add('file', 'local-singular')
    local.add(('folder', 'folders'), ('base-one', 'base-other'))
    incoming = Catalog(locale='de')
    incoming.add('file', 'base-singular')
    incoming.add(('folder', 'folders'), ('base-one', 'incoming-other'))

    result, conflicts = merge_catalogs(base, local, incoming)
    assert result['file'].string == 'local-singular'
    assert result[('folder', 'folders')].string == ('base-one', 'incoming-other')
    assert conflicts == []


def test_delete_vs_modify_conflicts_keep_local():
    base = Catalog(locale='de')
    base.add('gone', 'base')
    local = Catalog(locale='de')
    local.add('gone', 'changed-locally')
    incoming = Catalog(locale='de')  # incoming deleted the message

    result, conflicts = merge_catalogs(base, local, incoming)
    assert result['gone'].string == 'changed-locally'
    (conflict,) = _conflicts_for(conflicts, 'gone', field='presence')
    assert conflict['kind'] == 'deleted_vs_modified'
    assert conflict['incoming'] is None
    assert conflict['local'] == 'changed-locally'


def test_modify_vs_delete_other_direction_records_conflict():
    base = Catalog(locale='de')
    base.add('gone', 'base')
    local = Catalog(locale='de')  # local deleted
    incoming = Catalog(locale='de')
    incoming.add('gone', 'changed-incoming')

    result, conflicts = merge_catalogs(base, local, incoming)
    # local did not modify, so its deletion is applied, but the divergent
    # change is still reported for review
    assert 'gone' not in result
    assert _conflicts_for(conflicts, 'gone', field='presence')


def test_one_sided_deletion_without_modification_drops_silently():
    base = Catalog(locale='de')
    base.add('gone', 'base')
    local = Catalog(locale='de')
    local.add('gone', 'base')
    incoming = Catalog(locale='de')  # deleted, untouched on local

    result, conflicts = merge_catalogs(base, local, incoming)
    assert 'gone' not in result
    assert conflicts == []


def test_new_message_on_one_branch_is_kept():
    base = Catalog(locale='de')
    local = Catalog(locale='de')
    incoming = Catalog(locale='de')
    incoming.add('brand-new', 'neu')

    result, conflicts = merge_catalogs(base, local, incoming)
    assert result['brand-new'].string == 'neu'
    assert conflicts == []


def test_auto_comments_three_way_and_conflict():
    def catalog(a, b):
        cat = Catalog(locale='de')
        cat.add('a', 'x', auto_comments=[a])
        cat.add('b', 'y', auto_comments=[b])
        return cat

    base = catalog('base-dev', 'base-dev')
    local = catalog('local-dev', 'local-dev-b')
    incoming = catalog('base-dev', 'incoming-dev')

    result, conflicts = merge_catalogs(base, local, incoming)
    assert result['a'].auto_comments == ['local-dev']
    assert result['b'].auto_comments == ['local-dev-b']
    assert _conflicts_for(conflicts, 'a') == []
    (conflict,) = _conflicts_for(conflicts, 'b', field='auto_comments')
    assert conflict['local'] == ['local-dev-b']
    assert conflict['incoming'] == ['incoming-dev']
    assert conflict['base'] == ['base-dev']


def test_user_comments_merged_in_order():
    base = Catalog(locale='de')
    base.add('m', 'x', user_comments=['base'])
    local = Catalog(locale='de')
    local.add('m', 'x', user_comments=['base', 'local'])
    incoming = Catalog(locale='de')
    incoming.add('m', 'x', user_comments=['incoming', 'base'])

    result, _ = merge_catalogs(base, local, incoming)
    assert result['m'].user_comments == ['base', 'local', 'incoming']


def test_locations_deduplicated_stably():
    base = Catalog(locale='de')
    base.add('m', 'x', locations=[('a.py', 1)])
    local = Catalog(locale='de')
    local.add('m', 'x', locations=[('b.py', 2), ('a.py', 1)])
    incoming = Catalog(locale='de')
    incoming.add('m', 'x', locations=[('a.py', 1), ('c.py', 3)])

    result, _ = merge_catalogs(base, local, incoming)
    assert result['m'].locations == [('a.py', 1), ('b.py', 2), ('c.py', 3)]


def test_fuzzy_flag_is_never_removed():
    base = Catalog(locale='de')
    base.add('m', 'x', flags=['fuzzy'])
    local = Catalog(locale='de')
    local.add('m', 'y', flags=['fuzzy'])
    incoming = Catalog(locale='de')
    incoming.add('m', 'y')

    result, _ = merge_catalogs(base, local, incoming)
    assert result['m'].fuzzy
    result, _ = merge_catalogs(base, incoming, local)
    assert result['m'].fuzzy


def test_inputs_are_not_modified():
    base = Catalog(locale='de')
    base.add('m', 'x', locations=[('a.py', 1)], user_comments=['b'])
    local = Catalog(locale='de')
    local.add('m', 'y', locations=[('a.py', 1), ('b.py', 2)], user_comments=['b', 'l'])
    incoming = Catalog(locale='de')
    incoming.add('m', 'z')

    merge_catalogs(base, local, incoming)
    assert list(base['m'].locations) == [('a.py', 1)]
    assert list(local['m'].locations) == [('a.py', 1), ('b.py', 2)]
    assert list(incoming['m'].locations) == []
    assert local['m'].string == 'y'


def test_empty_catalogs():
    result, conflicts = merge_catalogs(Catalog(), Catalog(), Catalog())
    assert len(result) == 0
    assert conflicts == []

    base = Catalog(locale='de')
    base.add('m', 'x')
    result, conflicts = merge_catalogs(base, Catalog(locale='de'), Catalog(locale='de'))
    assert 'm' not in result
    assert conflicts == []


def test_unicode_roundtrip():
    base = Catalog(locale='de')
    base.add('Hello {name}', 'Hallo {name}')
    local = Catalog(locale='de')
    local.add('Hello {name}', 'Hallo {name} ☺')
    incoming = Catalog(locale='de')
    incoming.add('Hello {name}', 'Moin {name} 你好')

    result, conflicts = merge_catalogs(base, local, incoming)
    buf = io.BytesIO()
    pofile.write_po(buf, result)
    reread = pofile.read_po(io.BytesIO(buf.getvalue()), locale='de')
    assert reread['Hello {name}'].string == 'Hallo {name} ☺'
    (conflict,) = _conflicts_for(conflicts, 'Hello {name}')
    assert conflict['incoming'] == 'Moin {name} 你好'


def test_obsolete_stays_obsolete_when_untouched():
    base = Catalog(locale='de')
    base.add('m', 'base')
    local = Catalog(locale='de')
    local.add('m', 'base')
    incoming = Catalog(locale='de')
    incoming.delete('m')
    incoming.obsolete[incoming._key_for('m')] = Message('m', 'base')

    result, conflicts = merge_catalogs(base, local, incoming)
    assert 'm' not in result
    assert 'm' in [message.id for message in result.obsolete.values()]
    assert conflicts == []


def test_obsolete_recovery_through_modification():
    base = Catalog(locale='de')
    base.add('m', 'base')
    local = Catalog(locale='de')
    local.delete('m')
    local.obsolete[local._key_for('m')] = Message('m', 'base')
    incoming = Catalog(locale='de')
    incoming.add('m', 'incoming-active')

    result, conflicts = merge_catalogs(base, local, incoming)
    # local merely obsoleted without modifying, incoming resurrected with a
    # change: the message becomes active with the incoming translation
    assert result['m'].string == 'incoming-active'
    assert not result.obsolete
    assert conflicts == []

    # ...and the reverse direction keeps the local active version but still
    # reports an obsolete-vs-modified conflict
    result, conflicts = merge_catalogs(base, incoming, local)
    assert result['m'].string == 'incoming-active'
    assert not result.obsolete
    (conflict,) = _conflicts_for(conflicts, 'm', field='presence')
    assert conflict['kind'] == 'obsolete_vs_modified'
    assert conflict['local'] == 'incoming-active'
    assert conflict['incoming'] == 'base'


def test_locale_conflict_is_catalog_level():
    base = Catalog(locale='de')
    local = Catalog(locale='de')
    local.add('m', 'x')
    incoming = Catalog(locale='en')
    incoming.add('m', 'x')

    _result, conflicts = merge_catalogs(base, local, incoming)
    catalog_conflicts = [
        c for c in conflicts if c['level'] == 'catalog' and c['field'] == 'locale'
    ]
    (conflict,) = catalog_conflicts
    assert conflict['field'] == 'locale'
    assert conflict['local'] == 'de'
    assert conflict['incoming'] == 'en'


def test_plural_forms_conflict_is_catalog_level_and_slots_not_spliced():
    # de: nplurals=2; ru: nplurals=3
    base = Catalog(locale='de')
    base.add(('apple', 'apples'), ('b0', 'b1'))
    local = Catalog(locale='de')
    local.add(('apple', 'apples'), ('l0', 'l1'))
    incoming = Catalog(locale='ru')
    incoming.add(('apple', 'apples'), ('i0', 'i1', 'i2'))

    result, conflicts = merge_catalogs(base, local, incoming)
    fields = {c['field'] for c in conflicts if c['level'] == 'catalog'}
    assert 'plural_forms' in fields
    # local plural translation kept wholesale; no per-slot splice happened
    assert result[('apple', 'apples')].string == ('l0', 'l1')
    assert not [c for c in conflicts if c['level'] == 'message']


def test_merge_result_roundtrips_through_po_with_conflicts():
    base = Catalog(locale='de')
    base.add(('apple', 'apples'), ('a', 'b'), locations=[('x.py', 1)])
    base.add('gone', 'base')
    local = Catalog(locale='de')
    local.add(('apple', 'apples'), ('A', 'b'), locations=[('x.py', 1), ('y.py', 2)])
    local.add('gone', 'local')
    incoming = Catalog(locale='de')
    incoming.add(('apple', 'apples'), ('a', 'B'), locations=[('x.py', 1), ('z.py', 3)])
    incoming.delete('gone')

    result, conflicts = merge_catalogs(base, local, incoming)
    buf = io.BytesIO()
    pofile.write_po(buf, result)
    reread = pofile.read_po(io.BytesIO(buf.getvalue()), locale='de')
    assert reread[('apple', 'apples')].string == ('A', 'B')
    locations = reread[('apple', 'apples')].locations
    assert set(locations) == {('x.py', 1), ('y.py', 2), ('z.py', 3)}
    assert reread['gone'].string == 'local'
    assert {c['field'] for c in conflicts} == {'presence'}


def test_comments_and_flags_roundtrip_through_po():
    base = Catalog(locale='de')
    base.add('m', 'base', auto_comments=['base dev'], user_comments=['base user'])
    local = Catalog(locale='de')
    local.add('m', 'local', auto_comments=['local dev'], user_comments=['local user'])
    incoming = Catalog(locale='de')
    incoming.add(
        'm',
        'local',
        auto_comments=['local dev'],
        user_comments=['incoming user'],
    )

    result, conflicts = merge_catalogs(base, local, incoming)
    assert conflicts == []
    buf = io.BytesIO()
    pofile.write_po(buf, result)
    reread = pofile.read_po(io.BytesIO(buf.getvalue()), locale='de')
    assert reread['m'].string == 'local'
    assert reread['m'].auto_comments == ['local dev']
    assert reread['m'].user_comments == ['base user', 'local user', 'incoming user']


def test_message_obsolete_in_base_is_resurrected():
    base = Catalog(locale='de')
    base.obsolete[base._key_for('m')] = Message('m', 'old')
    local = Catalog(locale='de')  # stays absent on local
    incoming = Catalog(locale='de')
    incoming.add('m', 'new')

    result, conflicts = merge_catalogs(base, local, incoming)
    assert result['m'].string == 'new'
    assert not result.obsolete
    assert conflicts == []

    # both branches keep it obsolete
    local = Catalog(locale='de')
    local.obsolete[local._key_for('m')] = Message('m', 'old')
    incoming = Catalog(locale='de')
    incoming.obsolete[incoming._key_for('m')] = Message('m', 'old')
    result, conflicts = merge_catalogs(base, local, incoming)
    assert 'm' not in result
    assert list(result.obsolete.values())[0].id == 'm'
    assert conflicts == []


def test_plural_slot_conflict_values_are_complete():
    base = Catalog(locale='ru')
    base.add(('apple', 'apples'), ('b0', 'b1', 'b2'))
    local = Catalog(locale='ru')
    local.add(('apple', 'apples'), ('b0', 'l1', 'b2'))
    incoming = Catalog(locale='ru')
    incoming.add(('apple', 'apples'), ('b0', 'i1', 'b2'))

    _result, conflicts = merge_catalogs(base, local, incoming)
    (conflict,) = conflicts
    assert conflict['msgid'] == ('apple', 'apples')
    assert conflict['plural_index'] == 1
    assert conflict['base'] == 'b1'
    assert conflict['local'] == 'l1'
    assert conflict['incoming'] == 'i1'
