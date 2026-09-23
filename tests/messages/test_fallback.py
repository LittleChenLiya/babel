"""Tests for babel.messages.fallback."""

import pytest

from babel.messages.catalog import Catalog
from babel.messages.fallback import (
    FallbackCycleError,
    FallbackResolver,
    MissingCatalogError,
)

FRUIT = ("apple", "apples")


def make_catalog(locale=None, plural_forms=None):
    catalog = Catalog(locale=locale)
    if plural_forms is not None:
        catalog.mime_headers = [("Plural-Forms", plural_forms)]
    return catalog


def make_fr_chain():
    """fr_CA -> fr -> en, using the classic two-slot French/English rules."""
    two_slots = "nplurals=2; plural=(n > 1);"
    fr_ca = make_catalog("fr_CA", two_slots)
    # Contextual plural message with one of the two slots missing.
    fr_ca.add(FRUIT, ("pomme",), context="fruit")
    fr = make_catalog("fr", two_slots)
    fr.add(FRUIT, ("pomme", "pommes"), context="fruit")
    en = make_catalog("en")
    en.add(FRUIT, ("apple", "apples"), context="fruit")
    catalogs = {"fr_CA": fr_ca, "fr": fr, "en": en}
    fallbacks = {"fr_CA": ["fr"], "fr": ["en"]}
    return catalogs, fallbacks


def test_incomplete_plural_slots_fall_back_wholesale():
    catalogs, fallbacks = make_fr_chain()
    resolver = FallbackResolver(catalogs, fallbacks)
    for n, expected in ((1, "pomme"), (2, "pommes")):
        res = resolver.resolve("fr_CA", FRUIT, context="fruit", n=n)
        assert res.found
        assert res.source_locale == "fr"
        assert res.text == expected
        assert res.visited == ("fr_CA", "fr")
        assert len(res.skipped) == 1
        assert res.skipped[0].locale == "fr_CA"
        assert "incomplete plural slots (1 of 2 provided)" in res.skipped[0].reason
        assert res.diagnostics


def test_fuzzy_message_is_skipped():
    catalogs, fallbacks = make_fr_chain()
    fr_message = catalogs["fr"].get(FRUIT, context="fruit")
    fr_message.flags.add("fuzzy")
    resolver = FallbackResolver(catalogs, fallbacks)
    for n, expected in ((1, "apple"), (2, "apples")):
        res = resolver.resolve("fr_CA", FRUIT, context="fruit", n=n)
        assert res.found
        assert res.source_locale == "en"
        assert res.text == expected
        assert res.visited == ("fr_CA", "fr", "en")
        reasons = {skip.locale: skip.reason for skip in res.skipped}
        assert "fuzzy" in reasons["fr"]
    # The catalogs and message flags were not mutated by resolving.
    assert catalogs["fr"].get(FRUIT, context="fruit").fuzzy
    assert not catalogs["en"].get(FRUIT, context="fruit").fuzzy


def test_context_is_part_of_message_identity():
    en = make_catalog("en")
    en.add(FRUIT, ("apple", "apples"), context="menu")
    resolver = FallbackResolver({"en": en}, {})
    miss = resolver.resolve("en", FRUIT, context="fruit", n=1)
    assert not miss.found
    assert miss.source_locale is None
    assert miss.text is None
    assert miss.message is None
    hit = resolver.resolve("en", FRUIT, context="menu", n=2)
    assert hit.found
    assert hit.source_locale == "en"
    assert hit.text == "apples"


def test_diamond_graph_visits_each_locale_once():
    catalogs = {name: make_catalog() for name in "abcd"}
    catalogs["c"].add("hello", "bonjour")
    fallbacks = {"a": ["b", "c"], "b": ["d"], "c": ["d"]}
    resolver = FallbackResolver(catalogs, fallbacks)
    res = resolver.resolve("a", "hello")
    assert res.found
    assert res.source_locale == "c"
    assert res.visited == ("a", "b", "d", "c")
    assert list(res.visited).count("d") == 1


def test_cycle_is_rejected_before_any_lookup():
    catalogs = {name: make_catalog() for name in "ab"}
    catalogs["a"].add("hello", "bonjour")
    with pytest.raises(FallbackCycleError, match="a -> b -> a"):
        FallbackResolver(catalogs, {"a": ["b"], "b": ["a"]})
    with pytest.raises(FallbackCycleError, match="a -> a"):
        FallbackResolver(catalogs, {"a": ["a"]})


def test_missing_catalog_reference_is_rejected():
    catalogs = {"a": make_catalog()}
    with pytest.raises(MissingCatalogError, match="zzz"):
        FallbackResolver(catalogs, {"a": ["zzz"]})
    with pytest.raises(MissingCatalogError, match="ghost"):
        FallbackResolver(catalogs, {"ghost": ["a"]})


def test_source_locale_plural_rules_select_the_slot():
    # Russian has three plural forms; English has two.  The source
    # locale's rules must pick the slot, not the requested locale's.
    en = make_catalog("en")
    ru = make_catalog("ru")
    assert ru.num_plurals == 3
    ru.add(FRUIT, ("jabloko", "jabloka", "jablok"))
    resolver = FallbackResolver({"en": en, "ru": ru}, {"en": ["ru"]})
    expectations = {1: "jabloko", 2: "jabloka", 5: "jablok", 21: "jabloko"}
    for n, expected in expectations.items():
        res = resolver.resolve("en", FRUIT, n=n)
        assert res.found
        assert res.source_locale == "ru"
        assert res.text == expected
    # With English rules, n=5 would select slot 1; Russian selects slot 2.
    assert resolver.resolve("en", FRUIT, n=5).text == "jablok"


def test_placeholder_errors_make_message_unusable():
    fr = make_catalog("fr")
    fr.add("Hello %(name)s", "Bonjour %(nom)s")
    en = make_catalog("en")
    en.add("Hello %(name)s", "Hello %(name)s")
    resolver = FallbackResolver({"fr": fr, "en": en}, {"fr": ["en"]})
    res = resolver.resolve("fr", "Hello %(name)s")
    assert res.found
    assert res.source_locale == "en"
    assert res.skipped[0].locale == "fr"
    assert "failed checks" in res.skipped[0].reason
    assert "nom" in res.skipped[0].reason


def test_empty_and_obsolete_messages_are_unusable():
    fr = make_catalog("fr")
    fr.add("hello", "")
    fr.add("bye", "au revoir")
    bye = fr.get("bye")
    del fr["bye"]
    fr.obsolete["bye"] = bye
    en = make_catalog("en")
    en.add("hello", "hello")
    en.add("bye", "bye")
    resolver = FallbackResolver({"fr": fr, "en": en}, {"fr": ["en"]})
    res = resolver.resolve("fr", "hello")
    assert res.source_locale == "en"
    assert "empty translation" in res.skipped[0].reason
    res = resolver.resolve("fr", "bye")
    assert res.source_locale == "en"
    assert "obsolete" in res.skipped[0].reason


def test_empty_plural_slot_is_unusable():
    two_slots = "nplurals=2; plural=(n > 1);"
    fr = make_catalog("fr", two_slots)
    fr.add(FRUIT, ("pomme", ""))
    en = make_catalog("en")
    en.add(FRUIT, ("apple", "apples"))
    resolver = FallbackResolver({"fr": fr, "en": en}, {"fr": ["en"]})
    res = resolver.resolve("fr", FRUIT, n=2)
    assert res.source_locale == "en"
    assert "empty plural slot(s): 1" in res.skipped[0].reason


def test_empty_catalogs_yield_explicit_miss_with_diagnostics():
    catalogs = {"fr": make_catalog("fr"), "en": make_catalog("en")}
    resolver = FallbackResolver(catalogs, {"fr": ["en"]})
    res = resolver.resolve("fr", "hello", context="greeting")
    assert not res.found
    assert res.source_locale is None
    assert res.text is None
    assert res.message is None
    assert res.visited == ("fr", "en")
    assert len(res.skipped) == 2
    assert len(res.diagnostics) == 3
    assert res.diagnostics[-1].startswith("no usable translation")
    assert "greeting" in res.diagnostics[-1]
    assert "fr -> en" in res.diagnostics[-1]
    # Diagnostics are descriptive sentences, not a lone failure keyword.
    assert all(len(line.split()) > 1 for line in res.diagnostics)


def test_plural_resolution_requires_n():
    catalogs, fallbacks = make_fr_chain()
    resolver = FallbackResolver(catalogs, fallbacks)
    with pytest.raises(ValueError, match="n is required"):
        resolver.resolve("fr_CA", FRUIT, context="fruit")


def test_results_are_cached_per_resolver_snapshot():
    catalogs, fallbacks = make_fr_chain()
    resolver = FallbackResolver(catalogs, fallbacks)
    first = resolver.resolve("fr_CA", FRUIT, context="fruit", n=1)
    second = resolver.resolve("fr_CA", FRUIT, context="fruit", n=1)
    assert first is second
    # A lookup cached before a catalog update keeps reflecting the old
    # state; a new resolver (a new snapshot) picks the change up.
    miss = resolver.resolve("fr_CA", "hello")
    assert not miss.found
    catalogs["fr_CA"].add("hello", "bonjour")
    stale = resolver.resolve("fr_CA", "hello")
    assert stale is miss
    fresh = FallbackResolver(catalogs, fallbacks)
    res = fresh.resolve("fr_CA", "hello")
    assert res.found
    assert res.source_locale == "fr_CA"
    assert res.text == "bonjour"


def test_full_plural_id_is_part_of_message_identity():
    en = make_catalog("en")
    en.add(("apple", "apples"), ("apple", "apples"))
    resolver = FallbackResolver({"en": en}, {})
    miss = resolver.resolve("en", ("apple", "apples!!!"), n=1)
    assert not miss.found
    assert "id mismatch" in miss.skipped[0].reason
    hit = resolver.resolve("en", ("apple", "apples"), n=1)
    assert hit.found
