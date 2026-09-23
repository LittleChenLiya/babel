.. _message-fallback:

Message Fallback Resolution
===========================

.. module:: `babel.messages.fallback`

The :mod:`babel.messages.fallback` module resolves which catalog supplies
the translation of a single message when locales fall back to one another,
and records why the earlier locales in the chain were not selected.

The resolver is built from a mapping of locale names to
:class:`~babel.messages.catalog.Catalog` instances plus an explicit,
directed fallback table.  The graph is validated up front — missing
catalog references raise :class:`MissingCatalogError` and cycles raise
:class:`FallbackCycleError`, both before any message is looked up.  Each
lookup then walks the chain in depth-first declaration order, visiting
every locale at most once (diamond-shaped graphs are de-duplicated).

A message is identified by its context and its full id (the complete
``(singular, plural)`` tuple for pluralizable messages).  Messages that
are fuzzy, obsolete, empty, or that fail the catalog's placeholder checks
are not usable.  Plural translations are never spliced together from two
locales: the selected catalog must provide every plural slot its own
locale requires, all slots are checked first, and the winning text is
then picked with the *source* locale's plural rules — never with the
requested locale's rules.

Every lookup returns a :class:`Resolution` describing the source locale,
the visited path, and the per-locale skip reasons.  If no locale in the
chain can supply the message, the result is an explicit miss with
diagnostics; no silent default (such as the English singular) is
substituted.  The passed-in catalogs and message flags are never mutated.

Caching and snapshots
---------------------

The resolver holds an immutable snapshot of the catalog *mapping* and the
fallback table (both are copied at construction time) and memoizes
lookups per resolver instance.  The catalog and message objects
themselves are shared by reference and are never mutated.  If a catalog
is updated in place, already-cached lookups keep reflecting the old
state; build a new ``FallbackResolver`` (a new snapshot) to pick up the
changes::

    resolver = FallbackResolver(catalogs, fallbacks)
    resolver.resolve("fr_CA", ("apple", "apples"), context="fruit", n=1)

    catalogs["fr"].update(other_catalog)      # catalogs change ...
    resolver = FallbackResolver(catalogs, fallbacks)  # ... new snapshot

Demo script
-----------

The following script (also shipped as ``scripts/fallback_demo.py`` in the
source tree) prints the selected source locale and the skip reasons for a
normal fr_CA → fr → en fallback, an explicit miss, and a cyclic graph
rejection.  It runs in well under 90 seconds::

    python scripts/fallback_demo.py

.. literalinclude:: ../scripts/fallback_demo.py
   :language: python

API
---

.. autoclass:: FallbackResolver
   :members:

.. autoclass:: Resolution
   :members:

.. autoclass:: LocaleSkip
   :members:

.. autoexception:: FallbackError

.. autoexception:: MissingCatalogError

.. autoexception:: FallbackCycleError
