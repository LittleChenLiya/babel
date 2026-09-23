from __future__ import annotations

import pytest

from babel.messages import Catalog, Message
from babel.messages.fallback import (
    CatalogSnapshot,
    FallbackGraphError,
    FallbackResolver,
)

PLURAL_2 = "nplurals=2; plural=(n != 1);"
PLURAL_3 = "nplurals=3; plural=(n==1 ? 0 : n==2 ? 1 : 2);"

FILE_ID = ("%(count)s file", "%(count)s files")


def make_catalog(plural_forms: str = PLURAL_2) -> Catalog:
    catalog = Catalog()
    catalog.mime_headers = [
        ("Content-Type", "text/plain; charset=utf-8"),
        ("Plural-Forms", plural_forms),
    ]
    return catalog


def make_fr_chain():
    fr_ca = make_catalog()
    fr = make_catalog()
    en = make_catalog()
    # fr_CA only provides one of the two required plural slots.
    fr_ca[FILE_ID] = Message(FILE_ID, ("%(count)s fichier",), context="menu")
    fr[FILE_ID] = Message(
        FILE_ID,
        ("%(count)s fichier", "%(count)s fichiers"),
        context="menu",
    )
    en[FILE_ID] = Message(
        FILE_ID,
        ("%(count)s file", "%(count)s files"),
        context="menu",
    )
    catalogs = {"fr_CA": fr_ca, "fr": fr, "en": en}
    fallbacks = {"fr_CA": ["fr"], "fr": ["en"]}
    return catalogs, fallbacks


def reasons_for(resolution, locale):
    return [
        reason
        for record in resolution.skipped
        if record.locale == locale
        for reason in record.reasons
    ]


def test_incomplete_plural_slots_fall_back_wholesale():
    catalogs, fallbacks = make_fr_chain()
    resolver = FallbackResolver(catalogs, fallbacks)

    for n, expected in ((1, "%(count)s fichier"), (2, "%(count)s fichiers")):
        result = resolver.resolve("fr_CA", FILE_ID, context="menu", n=n)
        assert result.found
        assert result.source_locale == "fr"
        assert result.text == expected
        assert result.visited == ("fr_CA", "fr")
        fr_ca_reasons = reasons_for(result, "fr_CA")
        assert any("plural" in reason for reason in fr_ca_reasons)


def test_plural_forms_are_never_spliced_across_locales():
    catalogs, fallbacks = make_fr_chain()
    resolver = FallbackResolver(catalogs, fallbacks)
    result = resolver.resolve("fr_CA", FILE_ID, context="menu", n=1)
    # The single fr_CA slot must not be combined with the fr slots.
    assert result.text == "%(count)s fichier"
    assert result.plural_index == 0


def test_fuzzy_message_falls_through_to_next_locale():
    catalogs, fallbacks = make_fr_chain()
    fuzzy_message = catalogs["fr"].get(FILE_ID[0], context="menu")
    fuzzy_message.flags.add("fuzzy")
    resolver = FallbackResolver(catalogs, fallbacks)

    result = resolver.resolve("fr_CA", FILE_ID, context="menu", n=2)
    assert result.found
    assert result.source_locale == "en"
    assert result.text == "%(count)s files"
    assert result.visited == ("fr_CA", "fr", "en")
    assert any("fuzzy" in reason for reason in reasons_for(result, "fr"))


def test_context_is_part_of_message_identity():
    en = make_catalog()
    en[FILE_ID] = Message(
        FILE_ID,
        ("%(count)s file", "%(count)s files"),
        context="button",
    )
    resolver = FallbackResolver({"en": en}, {})

    # Same id, different context: must not be used.
    result = resolver.resolve("en", FILE_ID, context="menu", n=1)
    assert not result.found
    assert result.text is None

    # Same id, no context: must not be used either.
    result = resolver.resolve("en", FILE_ID, n=1)
    assert not result.found

    # The exact context resolves.
    result = resolver.resolve("en", FILE_ID, context="button", n=1)
    assert result.found
    assert result.text == "%(count)s file"


def test_full_plural_id_is_part_of_message_identity():
    en = make_catalog()
    en["apple"] = Message("apple", "pomme")
    resolver = FallbackResolver({"en": en}, {})

    # A plural request must not match a singular-only message.
    result = resolver.resolve("en", ("apple", "apples"), n=2)
    assert not result.found
    assert any("full id" in reason for reason in reasons_for(result, "en"))


def test_diamond_fallback_graph_visits_each_locale_once():
    catalogs = {name: make_catalog() for name in ("a", "b", "c", "d")}
    fallbacks = {"a": ["b", "c"], "b": ["d"], "c": ["d"]}
    resolver = FallbackResolver(catalogs, fallbacks)

    result = resolver.resolve("a", "missing")
    assert not result.found
    assert result.visited == ("a", "b", "d", "c")
    assert len(set(result.visited)) == len(result.visited)


def test_cycle_is_rejected_before_any_lookup():
    catalogs = {"a": make_catalog(), "b": make_catalog()}
    with pytest.raises(FallbackGraphError) as excinfo:
        FallbackResolver(catalogs, {"a": ["b"], "b": ["a"]})
    message = str(excinfo.value)
    assert "cycle" in message
    assert "a" in message and "b" in message
    assert excinfo.value.cycles


def test_missing_references_and_cycles_are_reported_together():
    catalogs = {"a": make_catalog(), "b": make_catalog()}
    fallbacks = {"a": ["b", "zz"], "b": ["a"], "yy": ["a"]}
    with pytest.raises(FallbackGraphError) as excinfo:
        FallbackResolver(catalogs, fallbacks)
    error = excinfo.value
    assert error.missing == ("yy", "zz")
    assert error.cycles
    text = str(error)
    assert "unknown locales" in text and "cycle" in text


def test_plural_form_selected_with_source_locale_rules():
    requester = make_catalog(PLURAL_2)
    source = make_catalog(PLURAL_3)
    source[FILE_ID] = Message(
        FILE_ID,
        ("un %(count)s", "deux %(count)s", "beaucoup %(count)s"),
    )
    resolver = FallbackResolver(
        {"requester": requester, "source": source},
        {"requester": ["source"]},
    )

    # n=5 maps to index 1 ("deux") under the requester's 2-form rules, but
    # the source locale's 3-form rules must be used instead.
    result = resolver.resolve("requester", FILE_ID, n=5)
    assert result.found
    assert result.source_locale == "source"
    assert result.plural_index == 2
    assert result.text == "beaucoup %(count)s"

    assert resolver.resolve("requester", FILE_ID, n=1).text == "un %(count)s"
    assert resolver.resolve("requester", FILE_ID, n=2).text == "deux %(count)s"


def test_placeholder_mismatch_makes_message_unusable():
    fr = make_catalog()
    en = make_catalog()
    fr[FILE_ID] = Message(
        FILE_ID,
        ("%(name)s fichier", "%(name)s fichiers"),
    )
    en[FILE_ID] = Message(
        FILE_ID,
        ("%(count)s file", "%(count)s files"),
    )
    resolver = FallbackResolver({"fr": fr, "en": en}, {"fr": ["en"]})

    result = resolver.resolve("fr", FILE_ID, n=1)
    assert result.found
    assert result.source_locale == "en"
    assert any("placeholder" in reason for reason in reasons_for(result, "fr"))


def test_empty_translation_and_obsolete_are_unusable():
    fr = make_catalog()
    en = make_catalog()
    fr["hello"] = Message("hello", "")
    fr.obsolete["bye"] = Message("bye", "au revoir")
    en["hello"] = Message("hello", "hello")
    en["bye"] = Message("bye", "goodbye")
    resolver = FallbackResolver({"fr": fr, "en": en}, {"fr": ["en"]})

    result = resolver.resolve("fr", "hello")
    assert result.source_locale == "en"
    assert any("empty" in reason for reason in reasons_for(result, "fr"))

    result = resolver.resolve("fr", "bye")
    assert result.source_locale == "en"
    assert any("obsolete" in reason for reason in reasons_for(result, "fr"))


def test_empty_catalogs_produce_an_explicit_miss():
    catalogs = {"fr": make_catalog(), "en": make_catalog()}
    resolver = FallbackResolver(catalogs, {"fr": ["en"]})

    result = resolver.resolve("fr", "hello")
    assert not result.found
    assert result.text is None
    assert result.source_locale is None
    assert result.visited == ("fr", "en")
    explanation = result.explain()
    assert "No usable translation" in explanation
    assert "fr" in explanation and "en" in explanation
    # A miss must not silently return the (English) msgid as the translation.
    assert result.text != "hello"


def test_snapshot_is_immutable_and_inputs_are_not_mutated():
    fr = make_catalog()
    message = Message("hello", "bonjour")
    fr["hello"] = message
    flags_before = set(message.flags)
    resolver = FallbackResolver({"fr": fr}, {})

    assert resolver.resolve("fr", "hello").found

    # Later catalog updates are invisible to the existing resolver...
    fr["new"] = Message("new", "nouveau")
    assert not resolver.resolve("fr", "new").found

    # ...but a fresh snapshot picks them up.
    snapshot = CatalogSnapshot({"fr": fr})
    resolver = FallbackResolver(snapshot, {})
    assert resolver.resolve("fr", "new").found

    # The input catalog and message flags were never modified.
    assert message.flags == flags_before
    assert fr["hello"].string == "bonjour"


def test_plural_resolution_requires_n():
    en = make_catalog()
    en[FILE_ID] = Message(FILE_ID, ("one file", "many files"))
    resolver = FallbackResolver({"en": en}, {})
    with pytest.raises(ValueError, match="n is required"):
        resolver.resolve("en", FILE_ID)


def test_unknown_start_locale_is_rejected():
    resolver = FallbackResolver({"en": make_catalog()}, {})
    with pytest.raises(ValueError, match="unknown start locale"):
        resolver.resolve("de", "hello")
