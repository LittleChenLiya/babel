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

"""
Tests for `babel.messages.fallback`.

Run locally with::

    pytest tests/messages/test_fallback.py -v

"""

from babel.messages import Catalog, Message, list_fallbacks


def _make_catalog(num_plurals=3):
    """Build a catalog without locale data, with a fixed plural count."""
    catalog = Catalog()
    catalog._num_plurals = num_plurals
    return catalog


def test_four_message_example():
    """Four messages, one per fallback category, are classified separately."""
    catalog = _make_catalog(num_plurals=3)

    # 1. Singular empty translation -> 'untranslated'
    catalog.add('hello', '')

    # 2. Plural with all slots empty -> 'explicit_empty'
    catalog.add(('apple', 'apples'), ('', '', ''))

    # 3. Fuzzy message -> 'fuzzy'
    catalog.add('world', 'monde', flags=['fuzzy'])

    # 4. Plural with the second slot missing -> 'plural_missing'
    catalog.add(('book', 'books'), ('livre', '', 'livres'))

    entries, obsolete = list_fallbacks(catalog)

    assert len(entries) == 4
    assert [e.category for e in entries] == [
        'untranslated',
        'explicit_empty',
        'fuzzy',
        'plural_missing',
    ]

    # Singular empty: falls back
    assert entries[0].will_fallback is True
    assert entries[0].missing_slots == []

    # Explicit empty: all three slots missing, falls back
    assert entries[1].will_fallback is True
    assert entries[1].missing_slots == [0, 1, 2]

    # Fuzzy: falls back only when use_fuzzy is False
    assert entries[2].will_fallback is True
    assert entries[2].missing_slots == []

    # Plural missing: the second slot (index 1) is missing
    assert entries[3].will_fallback is True
    assert entries[3].missing_slots == [1]

    assert obsolete == []


def test_fuzzy_respects_use_fuzzy_strategy():
    """A fuzzy message is usable only when the caller opts in."""
    catalog = _make_catalog()
    catalog.add('fuz', 'Futz', flags=['fuzzy'])

    entries, _ = list_fallbacks(catalog, use_fuzzy=False)
    assert len(entries) == 1
    assert entries[0].category == 'fuzzy'
    assert entries[0].will_fallback is True

    entries, _ = list_fallbacks(catalog, use_fuzzy=True)
    assert len(entries) == 1
    assert entries[0].category == 'fuzzy'
    assert entries[0].will_fallback is False


def test_same_msgid_different_context_keeps_two_entries():
    """Message identity includes context; same msgid with different context
    stays two separate entries."""
    catalog = _make_catalog()
    catalog.add('open', '', context='verb')
    catalog.add('open', '', context='adjective')
    catalog.add('open', '')  # no context

    entries, _ = list_fallbacks(catalog)
    assert len(entries) == 3
    contexts = [e.message.context for e in entries]
    assert contexts == ['verb', 'adjective', None]


def test_missing_slots_shown_by_slot_number():
    """Missing plural slots are reported by their zero-based slot index."""
    catalog = _make_catalog(num_plurals=3)
    catalog.add(('one', 'other'), ('un', '', ''))

    entries, _ = list_fallbacks(catalog)
    assert len(entries) == 1
    assert entries[0].category == 'plural_missing'
    assert entries[0].missing_slots == [1, 2]


def test_all_slots_filled_is_not_a_fallback():
    """A plural message with every slot translated does not fall back."""
    catalog = _make_catalog(num_plurals=2)
    catalog.add(('one', 'other'), ('un', 'autre'))

    entries, _ = list_fallbacks(catalog)
    assert entries == []


def test_translated_singular_is_not_a_fallback():
    """A singular message with a translation does not fall back."""
    catalog = _make_catalog()
    catalog.add('hello', 'bonjour')

    entries, _ = list_fallbacks(catalog)
    assert entries == []


def test_obsolete_listed_separately():
    """Obsolete messages are listed separately and not classified."""
    catalog = _make_catalog()
    catalog.add('active', '')
    catalog.obsolete['old'] = Message('old', 'vieux')

    entries, obsolete = list_fallbacks(catalog)
    assert len(entries) == 1
    assert entries[0].category == 'untranslated'

    assert len(obsolete) == 1
    assert obsolete[0].category == 'obsolete'
    assert obsolete[0].will_fallback is True
    assert obsolete[0].message.id == 'old'


def test_order_follows_catalog_insertion_order():
    """Entries are yielded in the order messages were added to the catalog."""
    catalog = _make_catalog()
    catalog.add('zebra', '')
    catalog.add('apple', '')
    catalog.add('mango', '')

    entries, _ = list_fallbacks(catalog)
    assert [e.message.id for e in entries] == ['zebra', 'apple', 'mango']


def test_matches_mo_compilation():
    """The fallback list agrees with the filter write_mo uses to decide
    which messages are compiled into the MO file.

    ``write_mo`` keeps a message iff ``m.string and (use_fuzzy or not m.fuzzy)``.
    This test checks the fallback list against that exact condition, without
    needing to serialize a MO file (which requires locale data).
    """
    catalog = _make_catalog(num_plurals=3)
    catalog.add('translated', 'traduit')  # kept in MO
    catalog.add('empty', '')  # dropped from MO
    catalog.add(('one', 'other'), ('un', ''))  # kept, slot 1 falls back
    catalog.add('fuzzy', 'flou', flags=['fuzzy'])  # dropped unless use_fuzzy

    def mo_kept(message, use_fuzzy):
        """Mirror the write_mo filter: m.string and (use_fuzzy or not m.fuzzy)."""
        return bool(message.string) and (use_fuzzy or not message.fuzzy)

    for use_fuzzy in (False, True):
        entries, _ = list_fallbacks(catalog, use_fuzzy=use_fuzzy)
        # Only entries that will actually fall back matter for MO compilation.
        will_fallback_ids = {e.message.id for e in entries if e.will_fallback}

        for message in catalog._messages.values():
            kept = mo_kept(message, use_fuzzy)
            if kept:
                # A kept message may still have plural slots that fall back.
                if message.pluralizable:
                    missing = [
                        i
                        for i, s in enumerate(message.string)
                        if i >= catalog.num_plurals or not s
                    ]
                    if missing:
                        assert message.id in will_fallback_ids
                    else:
                        assert message.id not in will_fallback_ids
                else:
                    assert message.id not in will_fallback_ids
            else:
                # A dropped message must appear in the fallback list.
                assert message.id in will_fallback_ids

    # With use_fuzzy=False the fuzzy message is dropped and reported.
    entries, _ = list_fallbacks(catalog, use_fuzzy=False)
    categories = {e.message.id: e.category for e in entries if e.will_fallback}
    assert categories == {
        'empty': 'untranslated',
        ('one', 'other'): 'plural_missing',
        'fuzzy': 'fuzzy',
    }

    # With use_fuzzy=True the fuzzy message is kept and no longer reported
    # as a fallback (it is still listed, but will_fallback is False).
    entries, _ = list_fallbacks(catalog, use_fuzzy=True)
    categories = {e.message.id: e.category for e in entries if e.will_fallback}
    assert 'fuzzy' not in categories
    assert categories == {
        'empty': 'untranslated',
        ('one', 'other'): 'plural_missing',
    }


def test_catalog_method():
    """Catalog.list_fallbacks() is a convenience wrapper."""
    catalog = _make_catalog()
    catalog.add('hello', '')

    entries, obsolete = catalog.list_fallbacks()
    assert len(entries) == 1
    assert entries[0].category == 'untranslated'
