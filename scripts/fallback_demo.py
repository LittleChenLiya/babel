"""Demo: print the translation source and skip reasons for a message.

Run from the repository root (after ``python setup.py import_cldr``)::

    python scripts/fallback_demo.py

It resolves a contextual plural message along the chain fr_CA -> fr -> en,
shows which locale supplied each text and why the earlier locales were
skipped, shows an explicit miss with diagnostics, and finally shows how a
cyclic fallback graph is rejected before any message is looked up.
The whole run takes well under 90 seconds.
"""

import sys
from pathlib import Path

# Allow running directly from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from babel.messages.catalog import Catalog
from babel.messages.fallback import (
    FallbackCycleError,
    FallbackResolver,
)

TWO_SLOTS = "nplurals=2; plural=(n > 1);"
APPLE = ("apple", "apples")


def build_catalogs():
    fr_ca = Catalog(locale="fr_CA")
    fr_ca.mime_headers = [("Plural-Forms", TWO_SLOTS)]
    # One of the two plural slots is missing, so fr_CA cannot be used.
    fr_ca.add(APPLE, ("pomme",), context="fruit")

    fr = Catalog(locale="fr")
    fr.mime_headers = [("Plural-Forms", TWO_SLOTS)]
    fr.add(APPLE, ("pomme", "pommes"), context="fruit")

    en = Catalog(locale="en")
    en.add(APPLE, ("apple", "apples"), context="fruit")

    return {"fr_CA": fr_ca, "fr": fr, "en": en}


def show(resolution):
    if resolution.found:
        print(f"  text:         {resolution.text!r}")
        print(f"  source:       {resolution.source_locale}")
    else:
        print("  miss:         no usable translation found")
    print(f"  visited:      {' -> '.join(resolution.visited)}")
    for skip in resolution.skipped:
        print(f"  skipped {skip.locale}: {skip.reason}")
    for line in resolution.diagnostics:
        print(f"  diagnostic:   {line}")


def main():
    catalogs = build_catalogs()
    fallbacks = {"fr_CA": ["fr"], "fr": ["en"]}
    resolver = FallbackResolver(catalogs, fallbacks)

    print("== normal fallback: fr_CA -> fr -> en ==")
    for n in (1, 2):
        print(f"n={n}:")
        show(resolver.resolve("fr_CA", APPLE, context="fruit", n=n))

    print()
    print("== explicit miss: unknown message ==")
    show(resolver.resolve("fr_CA", "no such message", context="fruit"))

    print()
    print("== cyclic fallback graph ==")
    try:
        FallbackResolver(catalogs, {"fr": ["en"], "en": ["fr"]})
    except FallbackCycleError as exc:
        print(f"  rejected before any lookup: {exc}")


if __name__ == "__main__":
    main()
