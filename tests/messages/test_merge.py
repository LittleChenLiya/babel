"""
Tests for the explicit translator-comment merge plan
(:mod:`babel.messages.merge`).
"""

from io import BytesIO

import pytest

from babel.messages import catalog as catalog_module
from babel.messages import pofile
from babel.messages.catalog import Catalog
from babel.messages.merge import (
    CONFLICT,
    MISSING_TARGET,
    BaselineChangedError,
    TranslatorCommentMergeError,
    TranslatorCommentMergePlan,
)


@pytest.fixture
def stable_headers(monkeypatch):
    """Make catalog header generation independent of CLDR data files."""
    monkeypatch.setattr(
        catalog_module,
        'format_datetime',
        lambda *args, **kwargs: '2026-01-01 00:00+0000',
    )


def po_round_trip(catalog):
    """Write *catalog* to a PO buffer and read it back."""
    buf = BytesIO()
    pofile.write_po(buf, catalog)
    buf.seek(0)
    return pofile.read_po(buf)


def test_identical_translator_comments_merged_only_once():
    target = Catalog()
    target.add('hello', 'hola', user_comments=['existing note'])
    source1 = Catalog()
    source1.add('hello', user_comments=['shared note', 'from source 1'])
    source2 = Catalog()
    source2.add('hello', user_comments=['shared note', 'from source 2'])

    plan = TranslatorCommentMergePlan(target, [source1, source2])
    assert plan.issues == ()
    assert plan.entries[0].comments == (
        'existing note',
        'shared note',
        'from source 1',
        'from source 2',
    )

    assert plan.apply() == 1
    comments = target['hello'].user_comments
    assert comments.count('shared note') == 1
    assert comments == ['existing note', 'shared note', 'from source 1', 'from source 2']
    # Applying the same plan again is a no-op.
    assert plan.apply() == 0
    assert target['hello'].user_comments == comments


def test_stable_order_follows_source_order():
    target = Catalog()
    target.add('hello', user_comments=['t0'])
    source1 = Catalog()
    source1.add('hello', user_comments=['s1a', 's1b'])
    source2 = Catalog()
    source2.add('hello', user_comments=['s2a', 's1a'])

    plan = TranslatorCommentMergePlan(target)
    plan.add_source(source1)
    plan.add_source(source2)
    plan.apply()
    assert target['hello'].user_comments == ['t0', 's1a', 's1b', 's2a']


def test_auto_comment_with_same_text_stays_independent():
    target = Catalog()
    target.add('hello', 'hola', auto_comments=['kept automatic'], user_comments=['same text'])
    source = Catalog()
    source.add(
        'hello', auto_comments=['same text', 'source automatic'], user_comments=['same text'],
    )

    plan = TranslatorCommentMergePlan(target, [source])
    plan.apply()

    message = target['hello']
    # The translator comment appears exactly once ...
    assert message.user_comments == ['same text']
    # ... and automatic comments were neither merged into translator
    # comments nor modified themselves.
    assert message.auto_comments == ['kept automatic']
    assert 'source automatic' not in message.user_comments


def test_locations_and_flags_are_not_merged():
    target = Catalog()
    target.add('hello', 'hola', locations=[('target.py', 1)], flags=['fuzzy'])
    source = Catalog()
    source.add(
        'hello',
        locations=[('source.py', 42)],
        flags=['python-format'],
        user_comments=['a note'],
    )

    plan = TranslatorCommentMergePlan(target, [source])
    plan.apply()

    message = target['hello']
    assert message.user_comments == ['a note']
    assert message.locations == [('target.py', 1)]
    assert message.flags == {'fuzzy'}


def test_plural_and_context_locate_the_correct_message():
    target = Catalog()
    target.add(('apple', 'apples'), ('pomme', 'pommes'), context='food')
    target.add('apple', 'Apple Inc.', context='company')
    target.add('apple', 'manzana')

    source = Catalog()
    source.add(('apple', 'apples'), context='food', user_comments=['plural with context'])
    source.add('apple', context='company', user_comments=['context only'])
    source.add('apple', user_comments=['plain singular'])

    plan = TranslatorCommentMergePlan(target, [source])
    assert plan.issues == ()
    assert plan.planned_comments(('apple', 'apples'), context='food') == (
        'plural with context',
    )
    assert plan.planned_comments('apple', context='company') == ('context only',)
    assert plan.planned_comments('apple') == ('plain singular',)

    plan.apply()
    assert target.get(('apple', 'apples'), context='food').user_comments == [
        'plural with context',
    ]
    assert target.get('apple', context='company').user_comments == ['context only']
    assert target.get('apple').user_comments == ['plain singular']


def test_apply_does_not_change_translations_or_ids():
    target = Catalog()
    target.add('hello', 'hola')
    target.add(('apple', 'apples'), ('pomme', 'pommes'), context='food')
    before = {
        key: (message.id, message.string, message.context)
        for key, message in target._messages.items()
    }

    source = Catalog()
    source.add('hello', 'IGNORED TRANSLATION', user_comments=['note'])
    source.add(('apple', 'apples'), context='food', user_comments=['pnote'])

    plan = TranslatorCommentMergePlan(target, [source])
    plan.apply()

    after = {
        key: (message.id, message.string, message.context)
        for key, message in target._messages.items()
    }
    assert before == after
    assert target['hello'].string == 'hola'
    assert target.get(('apple', 'apples'), context='food').string == ('pomme', 'pommes')


def test_missing_target_is_reported_centrally_before_apply():
    target = Catalog()
    target.add('hello', 'hola')
    source = Catalog()
    source.add('hello', user_comments=['ok'])
    source.add('ghost', user_comments=['nowhere to go'])
    source.add('other ghost', context='ctx', user_comments=['also missing'])

    plan = TranslatorCommentMergePlan(target, [source])
    assert len(plan.missing_targets) == 2
    assert {issue.kind for issue in plan.issues} == {MISSING_TARGET}
    assert plan.issues[0].id == 'ghost'
    assert plan.issues[1].id == 'other ghost'
    assert plan.issues[1].context == 'ctx'

    with pytest.raises(TranslatorCommentMergeError) as excinfo:
        plan.apply()
    # All issues are reported together, before anything is applied.
    message = str(excinfo.value)
    assert 'ghost' in message and 'other ghost' in message
    assert len(excinfo.value.issues) == 2
    # Nothing was applied.
    assert target['hello'].user_comments == []


def test_conflicting_identity_is_reported_centrally_before_apply():
    # The target has a pluralizable message; the source only knows the
    # singular form: same key, different full identity -> conflict.
    target = Catalog()
    target.add(('apple', 'apples'), ('pomme', 'pommes'))
    source = Catalog()
    source.add('apple', user_comments=['singular only'])

    plan = TranslatorCommentMergePlan(target, [source])
    assert len(plan.conflicts) == 1
    issue = plan.conflicts[0]
    assert issue.kind == CONFLICT
    assert issue.id == 'apple'

    with pytest.raises(TranslatorCommentMergeError) as excinfo:
        plan.apply()
    assert 'apple' in str(excinfo.value)
    assert target.get(('apple', 'apples')).user_comments == []


def test_conflicting_identities_between_sources_are_reported():
    target = Catalog()
    target.add('apple', 'manzana')
    source1 = Catalog()
    source1.add('apple', user_comments=['singular'])
    source2 = Catalog()
    source2.add(('apple', 'apples'), user_comments=['plural'])

    plan = TranslatorCommentMergePlan(target, [source1, source2])
    # The plural source message conflicts with the singular target identity.
    assert len(plan.conflicts) == 1
    with pytest.raises(TranslatorCommentMergeError):
        plan.apply()
    assert target['apple'].user_comments == []


def test_baseline_change_refuses_application():
    target = Catalog()
    target.add('hello', 'hola')
    source = Catalog()
    source.add('hello', user_comments=['note'])

    plan = TranslatorCommentMergePlan(target, [source])

    target.add('unrelated', 'sin relacion')  # baseline changes

    with pytest.raises(BaselineChangedError):
        plan.check_baseline()
    with pytest.raises(BaselineChangedError):
        plan.apply()
    assert target['hello'].user_comments == []


def test_baseline_change_by_translation_edit_refuses_application():
    target = Catalog()
    target.add('hello', 'hola')
    source = Catalog()
    source.add('hello', user_comments=['note'])

    plan = TranslatorCommentMergePlan(target, [source])
    target['hello'].string = 'bonjour'

    with pytest.raises(BaselineChangedError):
        plan.apply()
    assert target['hello'].string == 'bonjour'
    assert target['hello'].user_comments == []


def test_po_round_trip(stable_headers):
    target = Catalog()
    target.add(
        'hello',
        'hola',
        auto_comments=['shared text'],
        user_comments=['shared text', 'target note'],
        locations=[('main.py', 1)],
    )
    target.add(
        ('apple', 'apples'), ('pomme', 'pommes'), context='food', user_comments=['plural note'],
    )
    target.add('bye', 'adios')

    source = Catalog()
    source.add('hello', user_comments=['shared text', 'source note'])
    source.add(
        ('apple', 'apples'), context='food', user_comments=['plural note', 'extra plural note'],
    )
    source.add('bye', user_comments=['farewell note'])

    # Round-trip both catalogs through PO before planning.
    target = po_round_trip(target)
    source = po_round_trip(source)

    plan = TranslatorCommentMergePlan(target, [source])
    assert plan.issues == ()
    assert plan.apply() == 3

    # Round-trip the merged catalog through PO once more and verify.
    merged = po_round_trip(target)

    hello = merged['hello']
    assert hello.user_comments == ['shared text', 'target note', 'source note']
    assert hello.user_comments.count('shared text') == 1
    # Automatic comments stay independent from translator comments.
    assert hello.auto_comments == ['shared text']
    assert hello.locations == [('main.py', 1)]
    assert hello.string == 'hola'

    apples = merged.get(('apple', 'apples'), context='food')
    assert apples.context == 'food'
    assert apples.id == ('apple', 'apples')
    assert apples.user_comments == ['plural note', 'extra plural note']
    assert tuple(apples.string) == ('pomme', 'pommes')

    assert merged['bye'].user_comments == ['farewell note']
    assert merged['bye'].string == 'adios'
