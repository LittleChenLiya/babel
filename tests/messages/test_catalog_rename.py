"""Targeted tests (and runnable demo) for the plan-then-apply catalog
rename API: ``Catalog.plan_renames`` / ``Catalog.apply_renames``.

Run just this demo with:

    python -m pytest tests/messages/test_catalog_rename.py -v
"""

import pytest

from babel.messages.catalog import (
    Catalog,
    RenameConflictError,
    RenamePlan,
    RenameSpec,
    StaleRenamePlanError,
)


@pytest.fixture
def catalog():
    """A catalog with two context-disambiguated "Open" messages, a plural
    message, and a message that will serve as a collision target."""
    catalog = Catalog()
    catalog.add(
        'Open', 'Öffnen',
        locations=[('app/menu.py', 10)],
        flags=['fuzzy'],
        auto_comments=['menu entry'],
        user_comments=['Shown in the main menu'],
        context='menu',
    )
    catalog.add(
        'Open', 'Öffnen (Aktion)',
        locations=[('app/actions.py', 42)],
        context='verb',
    )
    catalog.add(
        ('file', 'files'), ('Datei', 'Dateien'),
        locations=[('app/files.py', 7)],
        flags=['python-format'],
    )
    catalog.add('Close', 'Schließen', locations=[('app/menu.py', 11)], context='menu')
    return catalog


def test_rename_only_selected_context(catalog, capsys):
    """Acceptance: rename context=menu "Open" to "Launch"; the context=verb
    "Open" must stay, and translations plus source locations survive."""
    plan = catalog.plan_renames([('Open', 'Launch', 'menu')])
    assert isinstance(plan, RenamePlan)

    renamed = catalog.apply_renames(plan)

    menu = renamed.get('Launch', context='menu')
    verb = renamed.get('Open', context='verb')
    print(f"\nmenu: {menu.id!r} -> {menu.string!r} @ {menu.locations}")
    print(f"verb: {verb.id!r} -> {verb.string!r} @ {verb.locations}")
    out, _ = capsys.readouterr()
    assert 'Öffnen' in out and 'app/menu.py' in out

    # The menu message was renamed, translation and locations kept.
    assert menu is not None
    assert menu.string == 'Öffnen'
    assert menu.locations == [('app/menu.py', 10)]
    assert menu.user_comments == ['Shown in the main menu']
    assert menu.auto_comments == ['menu entry']
    assert 'fuzzy' in menu.flags
    # The verb message with the same msgid is untouched.
    assert verb is not None
    assert verb.string == 'Öffnen (Aktion)'
    assert verb.locations == [('app/actions.py', 42)]
    assert renamed.get('Open', context='menu') is None
    # The source catalog was not modified in place.
    assert catalog.get('Open', context='menu') is not None
    assert catalog.get('Launch', context='menu') is None


def test_conflicting_targets_report_all_sources(catalog):
    """Acceptance: two identities renamed to the same target reject the
    whole batch, and the error reports both conflicting renames."""
    plan = catalog.plan_renames([
        ('Open', 'Launch', 'menu'),
        ('Close', 'Launch', 'menu'),
    ])
    with pytest.raises(RenameConflictError) as excinfo:
        catalog.apply_renames(plan)
    message = str(excinfo.value)
    # Not just one of the colliding renames is reported.
    assert "'Open'" in message and "'Close'" in message
    assert "'Launch'" in message
    (conflict,) = excinfo.value.conflicts
    assert conflict.target_id == 'Launch'
    assert conflict.target_context == 'menu'
    assert {spec.old_id for spec in conflict.sources} == {'Open', 'Close'}
    # Nothing was applied: the source catalog is unchanged.
    assert catalog.get('Launch', context='menu') is None
    assert catalog.get('Close', context='menu') is not None


def test_rename_onto_existing_message_conflicts(catalog):
    """A rename target occupied by an unrenamed message is a conflict too;
    the existing translation must not be silently overwritten."""
    plan = catalog.plan_renames([('Open', 'Close', 'menu')])
    with pytest.raises(RenameConflictError) as excinfo:
        catalog.apply_renames(plan)
    (conflict,) = excinfo.value.conflicts
    assert conflict.existing is not None
    assert conflict.existing.string == 'Schließen'
    assert 'would overwrite' in str(excinfo.value)


def test_plural_message_rename(catalog):
    """Plural messages are renamed by their full (singular, plural) identity."""
    plan = catalog.plan_renames([
        RenameSpec(old_id=('file', 'files'), new_id=('document', 'documents')),
    ])
    renamed = catalog.apply_renames(plan)
    message = renamed.get(('document', 'documents'))
    assert message is not None
    assert message.id == ('document', 'documents')
    assert message.string == ('Datei', 'Dateien')
    assert message.locations == [('app/files.py', 7)]
    assert renamed.get(('file', 'files')) is None
    # Source catalog still has the original plural message.
    assert catalog.get(('file', 'files')) is not None


def test_plural_identity_must_match_exactly(catalog):
    """A plural message is not found by a mismatched plural form."""
    with pytest.raises(KeyError):
        catalog.plan_renames([(('file', 'filez'), ('document', 'documents'))])


def test_rename_may_not_change_pluralizability(catalog):
    with pytest.raises(ValueError, match='pluralizable'):
        catalog.plan_renames([(('file', 'files'), 'document')])
    with pytest.raises(ValueError, match='pluralizable'):
        catalog.plan_renames([('Close', ('document', 'documents'), 'menu')])


def test_stale_plan_is_rejected(catalog):
    """Acceptance: if a planned message is modified after planning, applying
    the plan fails instead of renaming stale data."""
    plan = catalog.plan_renames([('Open', 'Launch', 'menu')])
    # Someone edits the catalog after the plan was made.
    catalog.get('Open', context='menu').string = 'Geändert'
    with pytest.raises(StaleRenamePlanError) as excinfo:
        catalog.apply_renames(plan)
    assert excinfo.value.stale[0].reason == 'modified'
    assert excinfo.value.stale[0].snapshot.string == 'Öffnen'
    assert excinfo.value.stale[0].current.string == 'Geändert'
    assert catalog.get('Launch', context='menu') is None


def test_stale_plan_reports_removed_message(catalog):
    plan = catalog.plan_renames([('Open', 'Launch', 'menu')])
    catalog.delete('Open', context='menu')
    with pytest.raises(StaleRenamePlanError) as excinfo:
        catalog.apply_renames(plan)
    assert excinfo.value.stale[0].reason == 'missing'


def test_result_shares_no_mutable_state_with_source(catalog):
    """Acceptance: flags (and other mutable lists) of the result are
    independent of the source catalog."""
    renamed = catalog.apply_renames(catalog.plan_renames([('Open', 'Launch', 'menu')]))

    result_menu = renamed.get('Launch', context='menu')
    result_verb = renamed.get('Open', context='verb')
    source_menu = catalog.get('Open', context='menu')
    source_verb = catalog.get('Open', context='verb')

    assert result_menu.flags is not source_menu.flags
    assert result_menu.locations is not source_menu.locations
    assert result_menu.user_comments is not source_menu.user_comments

    # Mutating the result must not leak into the source catalog.
    result_menu.flags.add('fuzzy')
    result_menu.flags.discard('fuzzy')
    result_menu.flags.add('c-format')
    result_menu.locations.append(('elsewhere.py', 1))
    result_menu.user_comments.append('changed')
    result_verb.flags.add('fuzzy')
    assert source_menu.flags == {'fuzzy'}
    assert source_menu.locations == [('app/menu.py', 10)]
    assert source_menu.user_comments == ['Shown in the main menu']
    assert source_verb.flags == set()


def test_derived_format_flags_recomputed_for_new_id(catalog):
    catalog.add('Hello %(name)s', 'Hallo %(name)s', context='greeting')
    renamed = catalog.apply_renames(
        catalog.plan_renames([('Hello %(name)s', 'Hello you', 'greeting')]),
    )
    message = renamed.get('Hello you', context='greeting')
    assert 'python-format' not in message.flags
    assert catalog.get('Hello %(name)s', context='greeting').flags == {'python-format'}


def test_rename_to_new_context(catalog):
    renamed = catalog.apply_renames(
        catalog.plan_renames([('Open', 'Open up', 'menu', 'phrase')]),
    )
    assert renamed.get('Open up', context='phrase') is not None
    assert renamed.get('Open', context='menu') is None
    assert renamed.get('Open', context='verb') is not None


def test_swap_of_two_identities_is_allowed(catalog):
    """A target vacated by another rename in the same batch is no conflict."""
    renamed = catalog.apply_renames(catalog.plan_renames([
        ('Open', 'Close', 'menu'),
        ('Close', 'Open', 'menu'),
    ]))
    assert renamed.get('Close', context='menu').string == 'Öffnen'
    assert renamed.get('Open', context='menu').string == 'Schließen'


def test_planning_errors(catalog):
    with pytest.raises(KeyError):
        catalog.plan_renames([('Nonexistent', 'Launch')])
    with pytest.raises(KeyError):
        catalog.plan_renames([('Open', 'Launch')])  # wrong context
    with pytest.raises(ValueError, match='no-op'):
        catalog.plan_renames([('Open', 'Open', 'menu')])
    with pytest.raises(ValueError, match='duplicate'):
        catalog.plan_renames([('Open', 'A', 'menu'), ('Open', 'B', 'menu')])


def test_apply_accepts_specs_directly(catalog):
    renamed = catalog.apply_renames([('Open', 'Launch', 'menu')])
    assert renamed.get('Launch', context='menu') is not None


def test_headers_and_metadata_preserved(catalog):
    renamed = catalog.apply_renames(catalog.plan_renames([('Open', 'Launch', 'menu')]))
    for attr in (
        'domain', 'project', 'version', 'copyright_holder', 'msgid_bugs_address',
        'creation_date', 'revision_date', 'last_translator', 'language_team',
        'charset', 'fuzzy', 'locale_identifier', '_num_plurals', '_plural_expr',
    ):
        assert getattr(renamed, attr) == getattr(catalog, attr), attr
    assert renamed.header_comment == catalog.header_comment
