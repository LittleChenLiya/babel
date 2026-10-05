"""Tests for ``Catalog.fallback_report``.

Run only these tests (plus the doctests of the touched module) with:

    python -m pytest tests/messages/test_fallback.py babel/messages/catalog.py -q
"""

from gettext import GNUTranslations
from io import BytesIO

import pytest

from babel.messages.catalog import Catalog, FallbackReason, Message
from babel.messages.mofile import write_mo

# The Russian plural rule, with three slots; set via the Plural-Forms
# header so the tests do not need the compiled locale data files.
RU_PLURAL_FORMS = (
    'nplurals=3; plural=n%10==1 && n%100!=11 ? 0 : '
    'n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2;'
)


def make_catalog():
    """A catalog with four messages exercising every fallback category."""
    catalog = Catalog()
    catalog.mime_headers = [('Plural-Forms', RU_PLURAL_FORMS)]  # nplurals=3
    catalog.add('foo', '')  # explicitly empty translation
    catalog.add('bar', 'Bar!', flags=['fuzzy'])  # fuzzy translation
    catalog.add(('apple', 'apples'), ('yabloko', '', 'yabloki'))  # slot 1 empty
    catalog.add('foo', context='menu')  # untranslated; same msgid, other context
    return catalog


@pytest.fixture
def stub_header_datetime(monkeypatch):
    # This source checkout has no compiled CLDR data files, so formatting
    # the header's POT-Creation-Date would fail; the header timestamp is
    # irrelevant for the message acceptance rules being cross-checked.
    monkeypatch.setattr(
        'babel.messages.catalog.format_datetime',
        lambda *args, **kwargs: 'YEAR-MO-DA HO:MI+ZONE',
    )


def compile_translations(catalog, use_fuzzy=False):
    buf = BytesIO()
    write_mo(buf, catalog, use_fuzzy=use_fuzzy)
    buf.seek(0)
    return GNUTranslations(fp=buf)


def test_reasons_are_classified_separately():
    report = make_catalog().fallback_report()
    by_identity = {(entry.id, entry.context): entry for entry in report}
    assert by_identity[('foo', None)].reasons == (FallbackReason.EMPTY,)
    assert by_identity[('bar', None)].reasons == (FallbackReason.FUZZY,)
    assert by_identity[(('apple', 'apples'), None)].reasons == (
        FallbackReason.MISSING_PLURAL_SLOT,
    )
    assert by_identity[('foo', 'menu')].reasons == (FallbackReason.UNTRANSLATED,)


def test_missing_plural_slots_are_reported_by_slot_number():
    catalog = Catalog()
    catalog.mime_headers = [('Plural-Forms', RU_PLURAL_FORMS)]  # nplurals=3
    catalog.add(('a', 'b'), ('x', '', 'y'))  # second slot (msgstr[1]) empty
    catalog.add(('c', 'd'), ('x', 'y'))  # third slot (msgstr[2]) missing
    report = catalog.fallback_report()
    assert report.entries[0].missing_slots == (1,)
    assert report.entries[1].missing_slots == (2,)


def test_same_msgid_with_different_context_stays_two_entries():
    report = make_catalog().fallback_report()
    foo_entries = [entry for entry in report if entry.id == 'foo']
    assert len(foo_entries) == 2
    assert {entry.context for entry in foo_entries} == {None, 'menu'}


def test_entries_follow_catalog_order():
    catalog = Catalog()
    catalog.add('zeta')
    catalog.add('alpha', '')
    catalog.add('mid', flags=['fuzzy'])
    report = catalog.fallback_report()
    assert [entry.id for entry in report] == ['zeta', 'alpha', 'mid']


def test_finished_translations_are_not_listed():
    catalog = Catalog()
    catalog.add('ok', 'OK!')
    catalog.add(('one', 'many'), ('one!', 'many!'))
    report = catalog.fallback_report()
    assert list(report) == []
    assert report.obsolete == []
    assert not report


def test_use_fuzzy_policy_marks_which_entries_fall_back():
    catalog = make_catalog()
    strict = catalog.fallback_report(use_fuzzy=False)
    assert next(e for e in strict if e.id == 'bar').falls_back
    lenient = catalog.fallback_report(use_fuzzy=True)
    fuzzy_entry = next(e for e in lenient if e.id == 'bar')
    assert not fuzzy_entry.falls_back
    # ...but a fuzzy translation is never treated as a usable finished
    # translation: it stays listed with the fuzzy reason either way.
    assert fuzzy_entry.reasons == (FallbackReason.FUZZY,)


def test_fuzzy_empty_message_still_falls_back_with_use_fuzzy():
    catalog = Catalog()
    catalog.add('bar', '', flags=['fuzzy'])
    (entry,) = catalog.fallback_report(use_fuzzy=True)
    assert entry.reasons == (FallbackReason.EMPTY, FallbackReason.FUZZY)
    assert entry.falls_back


def test_obsolete_messages_are_listed_separately():
    catalog = make_catalog()
    catalog.obsolete['old'] = Message('old', None)  # never translated
    report = catalog.fallback_report()
    assert all(entry.id != 'old' for entry in report.entries)
    assert not any(entry.obsolete for entry in report.entries)
    (obsolete_entry,) = report.obsolete
    assert obsolete_entry.id == 'old'
    assert obsolete_entry.obsolete
    assert obsolete_entry.reasons == (FallbackReason.UNTRANSLATED,)


def test_report_is_read_only():
    catalog = make_catalog()

    def snapshot():
        return [
            (m.id, m.context, m.string, set(m.flags))
            for m in (
                catalog.get('foo'),
                catalog.get('bar'),
                catalog.get(('apple', 'apples')),
                catalog.get('foo', context='menu'),
            )
        ]

    before = snapshot()
    catalog.fallback_report(use_fuzzy=True)
    assert snapshot() == before  # no translations invented, nothing mutated
    assert len(catalog) == 4


def test_falls_back_matches_actual_compilation(stub_header_datetime):
    catalog = make_catalog()
    catalog.add('ok', 'OK!')

    report = catalog.fallback_report(use_fuzzy=False)
    translations = compile_translations(catalog, use_fuzzy=False)
    # Entries flagged as falling back resolve to the message ID:
    assert translations.gettext('foo') == 'foo'  # empty translation not compiled
    assert translations.gettext('bar') == 'bar'  # fuzzy not compiled by default
    assert translations.pgettext('menu', 'foo') == 'foo'  # untranslated
    # Missing plural slots fall back individually, by slot:
    assert translations.ngettext('apple', 'apples', 1) == 'yabloko'  # slot 0
    assert translations.ngettext('apple', 'apples', 2) == 'apples'  # slot 1 empty
    assert translations.ngettext('apple', 'apples', 5) == 'yabloki'  # slot 2
    # Finished translations are used as-is and are not listed:
    assert translations.gettext('ok') == 'OK!'
    assert all(entry.id != 'ok' for entry in report)
    assert {entry.id for entry in report.fallback_entries} == {
        'foo', 'bar', ('apple', 'apples'),
    }

    # With use_fuzzy=True the fuzzy message is compiled...
    translations = compile_translations(catalog, use_fuzzy=True)
    assert translations.gettext('bar') == 'Bar!'
    # ...matching a report computed with the same caller policy.
    report = catalog.fallback_report(use_fuzzy=True)
    assert not next(e for e in report if e.id == 'bar').falls_back
