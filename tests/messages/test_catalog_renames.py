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

"""Tests for the plan-then-apply message renaming interface of
`babel.messages.catalog.Catalog`.

Run the directed demo entry with::

    pytest tests/messages/test_catalog_renames.py -k demo -s
"""

import pytest

from babel.messages.catalog import (
    Catalog,
    RenameConflict,
    RenameError,
)


def _make_catalog():
    """A small catalog with two ``Open`` messages in different contexts."""
    cat = Catalog()
    cat.add(
        'Open', 'Offnen', context='menu',
        locations=[('menu.py', 3), ('menu.py', 12)],
        flags=['fuzzy', 'python-format'],
        auto_comments=['Translators: menu entry'],
        user_comments=['Used in the File menu'],
    )
    cat.add(
        'Open', 'aufschlagen', context='verb',
        locations=[('verb.py', 7)],
        auto_comments=['Translators: verb'],
    )
    return cat


def test_rename_demo():
    """Directed demo: rename the ``menu`` context ``Open`` to ``Launch``,
    keep the ``verb`` context ``Open``, and print translations and source
    locations of both.

    Run with ``pytest -k demo -s`` to see the output.
    """
    cat = _make_catalog()
    plan = cat.plan_renames({('Open', 'menu'): 'Launch'})
    renamed = plan.apply()

    for context in ('menu', 'verb'):
        if context == 'menu':
            message = renamed.get('Launch', context)
        else:
            message = renamed.get('Open', context)
        print(f'context={context!r}: msgid={message.id!r}, '
              f'msgstr={message.string!r}, locations={message.locations!r}')
        assert message.string
        assert message.locations

    # The renamed message kept its translation and source locations.
    menu = renamed.get('Launch', 'menu')
    assert menu.string == 'Offnen'
    assert menu.locations == [('menu.py', 3), ('menu.py', 12)]
    # The other context's ``Open`` is untouched.
    verb = renamed.get('Open', 'verb')
    assert verb.string == 'aufschlagen'
    assert verb.locations == [('verb.py', 7)]


def test_rename_changes_msgid_keeps_context():
    cat = _make_catalog()
    plan = cat.plan_renames({('Open', 'menu'): 'Launch'})
    renamed = plan.apply()

    assert renamed.get('Launch', 'menu').id == 'Launch'
    assert renamed.get('Launch', 'menu').context == 'menu'
    # The other context's ``Open`` is still there.
    assert renamed.get('Open', 'verb').id == 'Open'
    assert renamed.get('Open', 'verb').context == 'verb'
    # The source catalog is unchanged.
    assert cat.get('Open', 'menu').id == 'Open'
    assert cat.get('Open', 'verb').id == 'Open'
    assert 'Launch' not in cat


def test_rename_preserves_translation_locations_flags_comments():
    cat = _make_catalog()
    plan = cat.plan_renames({('Open', 'menu'): 'Launch'})
    renamed = plan.apply()

    message = renamed.get('Launch', 'menu')
    assert message.string == 'Offnen'
    assert message.locations == [('menu.py', 3), ('menu.py', 12)]
    # ``python-format`` is auto-detected and stripped for msgids without a
    # format specifier; ``fuzzy`` is preserved.
    assert message.flags == {'fuzzy'}
    assert message.auto_comments == ['Translators: menu entry']
    assert message.user_comments == ['Used in the File menu']


def test_rename_preserves_python_format_flag():
    cat = Catalog()
    cat.add('Open %s', 'Offnen %s', context='menu', flags=['python-format'])
    renamed = cat.plan_renames({('Open %s', 'menu'): 'Launch %s'}).apply()
    assert renamed.get('Launch %s', 'menu').flags == {'python-format'}


def test_rename_same_name_different_context_no_conflict():
    cat = Catalog()
    cat.add('Open', 'a', context='menu')
    cat.add('Open', 'b', context='verb')
    plan = cat.plan_renames({('Open', 'menu'): 'Launch'})
    renamed = plan.apply()
    assert renamed.get('Launch', 'menu').string == 'a'
    assert renamed.get('Open', 'verb').string == 'b'


def test_rename_conflict_reports_both_entries():
    cat = Catalog()
    cat.add('Open', 'a', context='menu')
    cat.add('Close', 'b', context='menu')
    with pytest.raises(RenameConflict) as exc_info:
        cat.plan_renames({
            ('Open', 'menu'): 'Launch',
            ('Close', 'menu'): 'Launch',
        })
    conflict = exc_info.value
    assert len(conflict.conflicts) == 1
    entries = conflict.conflicts[0].entries
    # Both colliding renames are reported, not just one.
    assert len(entries) == 2
    assert {(e.source_id, e.source_context, e.target_id) for e in entries} == {
        ('Open', 'menu', 'Launch'),
        ('Close', 'menu', 'Launch'),
    }


def test_rename_conflict_reports_all_three_entries():
    cat = Catalog()
    for name in ('Open', 'Close', 'Shut'):
        cat.add(name, 'x', context='menu')
    with pytest.raises(RenameConflict) as exc_info:
        cat.plan_renames({
            ('Open', 'menu'): 'Launch',
            ('Close', 'menu'): 'Launch',
            ('Shut', 'menu'): 'Launch',
        })
    entries = exc_info.value.conflicts[0].entries
    assert len(entries) == 3


def test_rename_overwrite_existing_message_conflict():
    cat = Catalog()
    cat.add('Open', 'a', context='menu')
    cat.add('Launch', 'c', context='menu')
    with pytest.raises(RenameConflict) as exc_info:
        cat.plan_renames({('Open', 'menu'): 'Launch'})
    conflict = exc_info.value.conflicts[0]
    assert len(conflict.entries) == 1
    assert conflict.entries[0].source_id == 'Open'
    assert conflict.entries[0].target_id == 'Launch'
    # The existing message that would be overwritten is also reported.
    assert len(conflict.existing) == 1
    assert conflict.existing[0].id == 'Launch'


def test_rename_plural_message():
    cat = Catalog()
    cat.add(
        ('Open', 'Opens'), ('Offnen', 'Offnen'), context='menu',
        locations=[('menu.py', 3)],
    )
    plan = cat.plan_renames({
        (('Open', 'Opens'), 'menu'): ('Launch', 'Launches'),
    })
    renamed = plan.apply()

    message = renamed.get(('Launch', 'Launches'), 'menu')
    assert message.id == ('Launch', 'Launches')
    assert message.string == ('Offnen', 'Offnen')
    assert message.locations == [('menu.py', 3)]
    # The source catalog is unchanged.
    assert cat.get(('Open', 'Opens'), 'menu').id == ('Open', 'Opens')


def test_rename_plural_form_count_mismatch():
    cat = Catalog()
    cat.add(('Open', 'Opens'), ('a', 'b'))
    with pytest.raises(RenameError):
        cat.plan_renames({(('Open', 'Opens'), None): ('Launch', 'Launches', 'More')})


def test_rename_plural_to_singular_mismatch():
    cat = Catalog()
    cat.add(('Open', 'Opens'), ('a', 'b'))
    with pytest.raises(RenameError):
        cat.plan_renames({(('Open', 'Opens'), None): 'Launch'})


def test_rename_singular_to_plural_mismatch():
    cat = Catalog()
    cat.add('Open', 'a')
    with pytest.raises(RenameError):
        cat.plan_renames({'Open': ('Launch', 'Launches')})


def test_rename_plan_then_modify_string():
    cat = Catalog()
    message = cat.add('Open', 'a', context='menu')
    plan = cat.plan_renames({('Open', 'menu'): 'Launch'})
    message.string = 'changed'
    with pytest.raises(RenameError):
        plan.apply()


def test_rename_plan_then_modify_locations():
    cat = Catalog()
    message = cat.add('Open', 'a', context='menu', locations=[('a.py', 1)])
    plan = cat.plan_renames({('Open', 'menu'): 'Launch'})
    message.locations.append(('b.py', 2))
    with pytest.raises(RenameError):
        plan.apply()


def test_rename_plan_then_modify_flags():
    cat = Catalog()
    message = cat.add('Open', 'a', context='menu', flags=['fuzzy'])
    plan = cat.plan_renames({('Open', 'menu'): 'Launch'})
    message.flags.add('python-format')
    with pytest.raises(RenameError):
        plan.apply()


def test_rename_plan_then_delete():
    cat = Catalog()
    cat.add('Open', 'a', context='menu')
    plan = cat.plan_renames({('Open', 'menu'): 'Launch'})
    cat.delete('Open', 'menu')
    with pytest.raises(RenameError):
        plan.apply()


def test_rename_result_flags_independent():
    cat = Catalog()
    message = cat.add('Open', 'a', context='menu', flags=['fuzzy'])
    renamed = cat.plan_renames({('Open', 'menu'): 'Launch'}).apply()

    renamed.get('Launch', 'menu').flags.add('python-format')
    assert renamed.get('Launch', 'menu').flags == {'fuzzy', 'python-format'}
    # The source message's flags are untouched.
    assert message.flags == {'fuzzy'}


def test_rename_result_locations_independent():
    cat = Catalog()
    message = cat.add('Open', 'a', context='menu', locations=[('a.py', 1)])
    renamed = cat.plan_renames({('Open', 'menu'): 'Launch'}).apply()

    renamed.get('Launch', 'menu').locations.append(('b.py', 2))
    assert renamed.get('Launch', 'menu').locations == [('a.py', 1), ('b.py', 2)]
    # The source message's locations are untouched.
    assert message.locations == [('a.py', 1)]


def test_rename_result_comments_independent():
    cat = Catalog()
    message = cat.add('Open', 'a', context='menu', auto_comments=['a comment'])
    renamed = cat.plan_renames({('Open', 'menu'): 'Launch'}).apply()

    renamed.get('Launch', 'menu').auto_comments.append('another comment')
    assert renamed.get('Launch', 'menu').auto_comments == ['a comment', 'another comment']
    assert message.auto_comments == ['a comment']


def test_rename_source_catalog_unchanged():
    cat = _make_catalog()
    snapshot = {
        (message.id, message.context): message.clone()
        for message in cat._messages.values()
    }
    plan = cat.plan_renames({('Open', 'menu'): 'Launch'})
    plan.apply()

    for message in cat._messages.values():
        key = (message.id, message.context)
        assert message.is_identical(snapshot[key])


def test_rename_apply_renames_convenience():
    cat = Catalog()
    cat.add('Open', 'a', context='menu')
    plan = cat.plan_renames({('Open', 'menu'): 'Launch'})
    renamed = cat.apply_renames(plan)
    assert renamed.get('Launch', 'menu').id == 'Launch'


def test_rename_apply_renames_wrong_catalog():
    cat = Catalog()
    cat.add('Open', 'a', context='menu')
    plan = cat.plan_renames({('Open', 'menu'): 'Launch'})
    other = Catalog()
    with pytest.raises(RenameError):
        other.apply_renames(plan)


def test_rename_apply_renames_rejects_non_plan():
    cat = Catalog()
    with pytest.raises(TypeError):
        cat.apply_renames({})


def test_rename_invalid_key():
    cat = Catalog()
    cat.add('Open', 'a')
    with pytest.raises(RenameError):
        cat.plan_renames({123: 'Launch'})


def test_rename_missing_source():
    cat = Catalog()
    cat.add('Open', 'a')
    with pytest.raises(RenameError):
        cat.plan_renames({'Missing': 'Launch'})


def test_rename_with_message_key():
    cat = Catalog()
    message = cat.add('Open', 'a', context='menu')
    # Message objects are unhashable, so pass them as an iterable of pairs.
    plan = cat.plan_renames([(message, 'Launch')])
    renamed = plan.apply()
    assert renamed.get('Launch', 'menu').id == 'Launch'


def test_rename_with_iterable_of_pairs():
    cat = Catalog()
    cat.add('Open', 'a', context='menu')
    cat.add('Close', 'b', context='menu')
    plan = cat.plan_renames([
        (('Open', 'menu'), 'Launch'),
        (('Close', 'menu'), 'Shut'),
    ])
    renamed = plan.apply()
    assert renamed.get('Launch', 'menu').id == 'Launch'
    assert renamed.get('Shut', 'menu').id == 'Shut'


def test_rename_plan_len_and_iter():
    cat = Catalog()
    cat.add('Open', 'a', context='menu')
    cat.add('Close', 'b', context='menu')
    plan = cat.plan_renames({
        ('Open', 'menu'): 'Launch',
        ('Close', 'menu'): 'Shut',
    })
    assert len(plan) == 2
    assert {entry.source_id for entry in plan} == {'Open', 'Close'}


def test_rename_preserves_header():
    cat = Catalog(project='MyProject', version='1.0')
    cat.add('Open', 'a', context='menu')
    renamed = cat.plan_renames({('Open', 'menu'): 'Launch'}).apply()
    assert renamed.project == 'MyProject'
    assert renamed.version == '1.0'
    assert 'MyProject' in renamed.header_comment


def test_rename_chain_allowed():
    # A -> X and X -> A is a swap; both sources are also renamed, so it
    # must not be rejected as an overwrite.
    cat = Catalog()
    cat.add('Open', 'a', context='menu')
    cat.add('Close', 'b', context='menu')
    plan = cat.plan_renames({
        ('Open', 'menu'): 'Close',
        ('Close', 'menu'): 'Open',
    })
    renamed = plan.apply()
    assert renamed.get('Close', 'menu').string == 'a'
    assert renamed.get('Open', 'menu').string == 'b'


def test_rename_three_way_swap():
    cat = Catalog()
    cat.add('A', '1', context='menu')
    cat.add('B', '2', context='menu')
    cat.add('C', '3', context='menu')
    plan = cat.plan_renames({
        ('A', 'menu'): 'B',
        ('B', 'menu'): 'C',
        ('C', 'menu'): 'A',
    })
    renamed = plan.apply()
    assert renamed.get('B', 'menu').string == '1'
    assert renamed.get('C', 'menu').string == '2'
    assert renamed.get('A', 'menu').string == '3'
