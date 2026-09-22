"""Tests for babel.messages.catalog.merge_catalogs."""

import io
import json

from babel.messages.catalog import Catalog, merge_catalogs
from babel.messages.pofile import read_po, write_po


def make_catalog(messages=None, locale='de', obsolete=None):
    catalog = Catalog(locale=locale)
    for spec in messages or []:
        catalog.add(
            spec['id'],
            spec.get('string', ''),
            locations=spec.get('locations', ()),
            flags=spec.get('flags', ()),
            auto_comments=spec.get('auto_comments', ()),
            user_comments=spec.get('user_comments', ()),
            context=spec.get('context'),
        )
    for spec in obsolete or []:
        message = catalog.add(
            spec['id'],
            spec.get('string', ''),
            context=spec.get('context'),
        )
        catalog.obsolete[catalog._key_for(message.id, message.context)] = message
        del catalog[message.id]
    return catalog


def merge(base, local, incoming):
    return merge_catalogs(base, local, incoming)


def test_empty_catalogs():
    merged, conflicts = merge(Catalog(), Catalog(), Catalog())
    assert conflicts == []
    assert len(merged) == 0
    assert len(merged.obsolete) == 0


def test_unmodified_message_kept():
    base = make_catalog([{'id': 'a', 'string': 'A'}])
    local = make_catalog([{'id': 'a', 'string': 'A'}])
    incoming = make_catalog([{'id': 'a', 'string': 'A'}])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    assert merged.get('a').string == 'A'


def test_one_side_change_wins():
    base = make_catalog([{'id': 'a', 'string': 'A'}])
    local = make_catalog([{'id': 'a', 'string': 'A-local'}])
    incoming = make_catalog([{'id': 'a', 'string': 'A'}])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    assert merged.get('a').string == 'A-local'

    merged, conflicts = merge(base, incoming, local)
    assert conflicts == []
    assert merged.get('a').string == 'A-local'


def test_identical_change_on_both_sides():
    base = make_catalog([{'id': 'a', 'string': 'A'}])
    local = make_catalog([{'id': 'a', 'string': 'same'}])
    incoming = make_catalog([{'id': 'a', 'string': 'same'}])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    assert merged.get('a').string == 'same'


def test_context_distinguishes_same_msgid():
    base = make_catalog([
        {'id': 'Open', 'string': 'O1', 'context': 'button'},
        {'id': 'Open', 'string': 'O2', 'context': 'menu'},
    ])
    local = make_catalog([
        {'id': 'Open', 'string': 'O1-local', 'context': 'button'},
        {'id': 'Open', 'string': 'O2', 'context': 'menu'},
    ])
    incoming = make_catalog([
        {'id': 'Open', 'string': 'O1', 'context': 'button'},
        {'id': 'Open', 'string': 'O2-incoming', 'context': 'menu'},
    ])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    assert merged.get('Open', context='button').string == 'O1-local'
    assert merged.get('Open', context='menu').string == 'O2-incoming'


def test_singular_and_plural_not_merged():
    base = make_catalog([{'id': 'foo', 'string': 'FOO'}])
    local = make_catalog([{'id': 'foo', 'string': 'FOO'}])
    incoming = make_catalog([
        {'id': ('foo', 'foos'), 'string': ('FOO1', 'FOO2')},
    ])
    merged, conflicts = merge(base, local, incoming)
    # The singular message was replaced by a plural message on the incoming
    # side; the two must not be merged into a single item.
    # Local singular wins and the collision is reported explicitly.
    singular = merged.get('foo')
    assert singular is not None and not singular.pluralizable
    assert singular.string == 'FOO'
    assert len(conflicts) == 1
    assert conflicts[0]['reason'] == 'msgid-collision'


def test_plural_changed_to_singular_keeps_local():
    base = make_catalog([{'id': ('foo', 'foos'), 'string': ('B0', 'B1')}])
    local = make_catalog([{'id': 'foo', 'string': 'singular-local'}])
    incoming = make_catalog([
        {'id': ('foo', 'foos'), 'string': ('I0', 'I1')},
    ])
    merged, conflicts = merge(base, local, incoming)
    message = merged.get('foo')
    assert message is not None and not message.pluralizable
    assert message.string == 'singular-local'
    assert len(conflicts) == 1
    assert conflicts[0]['reason'] == 'msgid-collision'


def test_plural_slots_merged_independently():
    base = make_catalog([{'id': ('f', 'fs'), 'string': ('B0', 'B1')}])
    local = make_catalog([{'id': ('f', 'fs'), 'string': ('L0', 'B1')}])
    incoming = make_catalog([{'id': ('f', 'fs'), 'string': ('B0', 'I1')}])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    assert merged.get(('f', 'fs')).string == ('L0', 'I1')


def test_plural_slot_conflict_keeps_local():
    base = make_catalog([{'id': ('f', 'fs'), 'string': ('B0', 'B1')}])
    local = make_catalog([{'id': ('f', 'fs'), 'string': ('L0', 'L1')}])
    incoming = make_catalog([{'id': ('f', 'fs'), 'string': ('I0', 'I1')}])
    merged, conflicts = merge(base, local, incoming)
    assert merged.get(('f', 'fs')).string == ('L0', 'L1')
    assert [c['field'] for c in conflicts] == ['string[0]', 'string[1]']
    assert conflicts[0]['base'] == 'B0'
    assert conflicts[0]['local'] == 'L0'
    assert conflicts[0]['incoming'] == 'I0'


def test_conflicting_translation_keeps_local_and_records():
    base = make_catalog([{'id': 'a', 'string': 'A'}])
    local = make_catalog([{'id': 'a', 'string': 'A-local'}])
    incoming = make_catalog([{'id': 'a', 'string': 'A-incoming'}])
    merged, conflicts = merge(base, local, incoming)
    assert merged.get('a').string == 'A-local'
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict['type'] == 'message'
    assert conflict['reason'] == 'translation'
    assert conflict['msgid'] == 'a'
    assert conflict['context'] is None
    assert conflict['base'] == 'A'
    assert conflict['local'] == 'A-local'
    assert conflict['incoming'] == 'A-incoming'
    # Conflict records must be JSON-serializable.
    json.dumps(conflicts)


def test_single_side_delete():
    base = make_catalog([{'id': 'a', 'string': 'A'}, {'id': 'b', 'string': 'B'}])
    local = make_catalog([{'id': 'a', 'string': 'A'}])
    incoming = make_catalog([{'id': 'a', 'string': 'A'}, {'id': 'b', 'string': 'B'}])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    assert merged.get('b') is None
    assert merged.get('a').string == 'A'


def test_delete_vs_modify_conflict():
    base = make_catalog([{'id': 'a', 'string': 'A'}])
    local = make_catalog()
    incoming = make_catalog([{'id': 'a', 'string': 'A-incoming'}])
    merged, conflicts = merge(base, local, incoming)
    # Local deletion wins, but the conflict is recorded.
    assert merged.get('a') is None
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict['reason'] == 'deleted-vs-modified'
    assert conflict['base']['msgstr'] == 'A'
    assert conflict['local'] is None
    assert conflict['incoming']['msgstr'] == 'A-incoming'
    json.dumps(conflicts)


def test_modify_vs_delete_conflict_keeps_local():
    base = make_catalog([{'id': 'a', 'string': 'A'}])
    local = make_catalog([{'id': 'a', 'string': 'A-local'}])
    incoming = make_catalog()
    merged, conflicts = merge(base, local, incoming)
    assert merged.get('a').string == 'A-local'
    assert len(conflicts) == 1
    assert conflicts[0]['reason'] == 'deleted-vs-modified'
    assert conflicts[0]['incoming'] is None


def test_added_on_one_side():
    base = make_catalog([{'id': 'a', 'string': 'A'}])
    local = make_catalog([{'id': 'a', 'string': 'A'}, {'id': 'new', 'string': 'N'}])
    incoming = make_catalog([{'id': 'a', 'string': 'A'}])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    assert merged.get('new').string == 'N'


def test_both_added_differently_conflicts():
    base = make_catalog()
    local = make_catalog([{'id': 'a', 'string': 'L'}])
    incoming = make_catalog([{'id': 'a', 'string': 'I'}])
    merged, conflicts = merge(base, local, incoming)
    assert merged.get('a').string == 'L'
    assert len(conflicts) == 1
    assert conflicts[0]['reason'] == 'both-added'


def test_unicode_roundtrip():
    base = make_catalog([{'id': 'grüße', 'string': 'Grüße'}])
    local = make_catalog([{'id': 'grüße', 'string': 'Grüße ☃'}])
    incoming = make_catalog([{'id': 'grüße', 'string': 'Grüße'}])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    assert merged.get('grüße').string == 'Grüße ☃'


def test_obsolete_message_resurrected_on_one_side():
    base = make_catalog(obsolete=[{'id': 'old', 'string': 'OLD'}])
    local = make_catalog([{'id': 'old', 'string': 'OLD'}])
    incoming = make_catalog(obsolete=[{'id': 'old', 'string': 'OLD'}])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    assert merged.get('old') is not None
    assert merged.get('old').string == 'OLD'
    assert len(merged.obsolete) == 0


def test_obsolete_made_on_one_side():
    base = make_catalog([{'id': 'old', 'string': 'OLD'}])
    local = make_catalog(obsolete=[{'id': 'old', 'string': 'OLD'}])
    incoming = make_catalog([{'id': 'old', 'string': 'OLD'}])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    assert merged.get('old') is None
    assert len(merged.obsolete) == 1


def test_obsolete_kept_when_untouched():
    base = make_catalog(obsolete=[{'id': 'old', 'string': 'OLD'}])
    local = make_catalog(obsolete=[{'id': 'old', 'string': 'OLD'}])
    incoming = make_catalog(obsolete=[{'id': 'old', 'string': 'OLD'}])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    assert len(merged.obsolete) == 1


def test_locations_deduplicated():
    base = make_catalog([{'id': 'a', 'string': 'A', 'locations': [('f.py', 1)]}])
    local = make_catalog([
        {'id': 'a', 'string': 'A', 'locations': [('f.py', 1), ('g.py', 2)]},
    ])
    incoming = make_catalog([
        {'id': 'a', 'string': 'A', 'locations': [('f.py', 1), ('h.py', 3)]},
    ])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    assert merged.get('a').locations == [('f.py', 1), ('g.py', 2), ('h.py', 3)]


def test_fuzzy_flag_never_removed():
    base = make_catalog([{'id': 'a', 'string': 'A', 'flags': {'fuzzy'}}])
    local = make_catalog([{'id': 'a', 'string': 'A-local', 'flags': {'fuzzy'}}])
    incoming = make_catalog([{'id': 'a', 'string': 'A', 'flags': set()}])
    merged, conflicts = merge(base, local, incoming)
    assert merged.get('a').fuzzy


def test_user_comments_merged_in_order():
    base = make_catalog([{'id': 'a', 'string': 'A', 'user_comments': ['base note']}])
    local = make_catalog([
        {'id': 'a', 'string': 'A', 'user_comments': ['base note', 'local note']},
    ])
    incoming = make_catalog([
        {'id': 'a', 'string': 'A', 'user_comments': ['base note', 'incoming note']},
    ])
    merged, conflicts = merge(base, local, incoming)
    assert merged.get('a').user_comments == ['base note', 'local note', 'incoming note']


def test_auto_comments_three_way():
    base = make_catalog([{'id': 'a', 'string': 'A', 'auto_comments': ['dev']}])
    local = make_catalog([{'id': 'a', 'string': 'A', 'auto_comments': ['dev', 'more']}])
    incoming = make_catalog([{'id': 'a', 'string': 'A', 'auto_comments': ['dev']}])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    assert merged.get('a').auto_comments == ['dev', 'more']


def test_auto_comments_conflict():
    base = make_catalog([{'id': 'a', 'string': 'A', 'auto_comments': ['dev']}])
    local = make_catalog([{'id': 'a', 'string': 'A', 'auto_comments': ['dev-l']}])
    incoming = make_catalog([{'id': 'a', 'string': 'A', 'auto_comments': ['dev-i']}])
    merged, conflicts = merge(base, local, incoming)
    assert merged.get('a').auto_comments == ['dev-l']
    assert len(conflicts) == 1
    assert conflicts[0]['reason'] == 'auto-comments'
    assert conflicts[0]['base'] == ['dev']


def test_locale_mismatch_is_catalog_conflict():
    base = make_catalog(locale='de')
    local = make_catalog(locale='de')
    incoming = make_catalog(locale='fr')
    merged, conflicts = merge(base, local, incoming)
    assert any(c['type'] == 'catalog' and c['reason'] == 'locale-mismatch' for c in conflicts)


def test_plural_forms_mismatch_no_slot_splicing():
    def cat(string, num_plurals, expr):
        catalog = make_catalog([{'id': ('f', 'fs'), 'string': string}])
        catalog._num_plurals = num_plurals
        catalog._plural_expr = expr
        return catalog

    base = cat(('B0', 'B1'), 2, '(n != 1)')
    local = cat(('L0', 'B1'), 2, '(n != 1)')
    incoming = cat(('B0', 'I1', 'I2'), 3, '(n != 1 ? 0 : 1)')
    merged, conflicts = merge(base, local, incoming)
    assert any(
        c['type'] == 'catalog' and c['reason'] == 'plural-forms-mismatch' for c in conflicts
    )
    # Plural slots must not be spliced across different plural rules:
    # the local translation is kept whole.
    assert merged.get(('f', 'fs')).string == ('L0', 'B1')


def test_inputs_are_not_modified():
    base = make_catalog([{'id': 'a', 'string': 'A'}])
    local = make_catalog([{'id': 'a', 'string': 'L'}, {'id': 'b', 'string': 'B'}])
    incoming = make_catalog([{'id': 'a', 'string': 'I'}])
    base_before = sorted(base._messages)
    local_before = sorted(local._messages)
    incoming_before = sorted(incoming._messages)
    local_string_before = local.get('a').string
    merge(base, local, incoming)
    assert sorted(base._messages) == base_before
    assert sorted(local._messages) == local_before
    assert sorted(incoming._messages) == incoming_before
    assert local.get('a').string == local_string_before


def test_merged_catalog_roundtrips_through_po():
    base = make_catalog([
        {'id': 'a', 'string': 'A'},
        {'id': ('f', 'fs'), 'string': ('B0', 'B1')},
    ])
    local = make_catalog([
        {'id': 'a', 'string': 'A-local'},
        {'id': ('f', 'fs'), 'string': ('L0', 'B1')},
    ])
    incoming = make_catalog([
        {'id': 'a', 'string': 'A-local'},
        {'id': ('f', 'fs'), 'string': ('B0', 'I1')},
    ])
    merged, conflicts = merge(base, local, incoming)
    assert conflicts == []
    buf = io.BytesIO()
    write_po(buf, merged)
    buf.seek(0)
    reread = read_po(buf, locale='de')
    assert reread.get('a').string == 'A-local'
    assert reread.get(('f', 'fs')).string == ('L0', 'I1')


def test_conflicting_merge_roundtrips_through_po():
    base = make_catalog([
        {'id': 'a', 'string': 'A'},
        {'id': 'b', 'string': 'B'},
    ])
    local = make_catalog([
        {'id': 'a', 'string': 'A-local'},
        {'id': 'b', 'string': 'B'},
    ])
    incoming = make_catalog([
        {'id': 'a', 'string': 'A-incoming'},
        {'id': 'b', 'string': 'B'},
    ])
    merged, conflicts = merge(base, local, incoming)
    assert len(conflicts) == 1
    # The conflict list must survive a JSON round-trip.
    reloaded_conflicts = json.loads(json.dumps(conflicts, ensure_ascii=False))
    assert reloaded_conflicts == conflicts
    # The merged catalog (local value kept) must write and re-read cleanly.
    buf = io.BytesIO()
    write_po(buf, merged)
    buf.seek(0)
    reread = read_po(buf, locale='de')
    assert reread.get('a').string == 'A-local'
