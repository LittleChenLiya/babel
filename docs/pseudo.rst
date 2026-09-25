.. -*- mode: rst; encoding: utf-8 -*-

.. _pseudo-localization:

=====================
Pseudo-Localization
=====================

Babel can pseudo-localize message catalogs: it transforms messages into
deterministic "fake translations" so that user interfaces can be checked
for length problems and interpolation errors before (or without) real
translations being available.

Transformation Rules
====================

The transformation applied to every message follows these rules:

1. **Accent mapping.** Latin letters (``a``-``z``, ``A``-``Z``) are replaced
   with accented look-alikes using a fixed, deterministic mapping table
   (for example ``a`` becomes ``\u00e0``, ``H`` becomes ``\u0124``).
   Digits, punctuation and non-Latin scripts (CJK, Cyrillic, Arabic, ...)
   pass through unchanged.

2. **Expansion.** To simulate languages that need more space than English,
   the text is padded with wide filler characters.  The number of filler
   characters is ``round(length * expansion)`` where ``length`` is the
   length of the plain text (placeholders excluded) and ``expansion``
   defaults to ``0.3`` (30%).  The filler characters are chosen from a
   fixed set based on a SHA-256 digest of the seed and the message, so
   identical input, expansion ratio and seed always produce identical
   output.  The default seed is a fixed built-in value.

3. **Boundary markers.** Every message is wrapped in the markers ``\u27e6``
   and ``\u27e7`` so that truncated or accidentally concatenated messages
   are easy to spot in the UI.

4. **Placeholders and escapes.** ``python-format`` conversions
   (``%(name)s``, ``%05.2f``, ...) and ``python-brace-format`` replacement
   fields (``{name}``, ``{0!r:>10}``, ...) are kept verbatim, including
   nested replacement fields in the format spec such as nested width
   fields (``{value:{width}.{precision}f}``).  The escapes ``%%``, ``{{``
   and ``}}`` are likewise preserved, so pseudo-localized messages remain
   parseable and can still be interpolated.

5. **HTML.** Messages flagged ``html`` or ``html-format`` (or all messages,
   when the ``--html`` option is used) keep their tags, entities, comments
   and attribute values untouched; only text nodes are transformed.
   For example ``<a title='Keep'>Text</a>`` keeps ``title='Keep'`` and
   only ``Text`` is pseudo-localized.

6. **Plurals.** Every plural branch of a message is transformed
   separately, so each branch gets its own markers and expansion.

7. **Idempotency.** Messages that already carry the boundary markers are
   returned unchanged, so running the transformation repeatedly is safe
   and does not grow the text.

8. **Error isolation.** Messages that cannot be transformed are reported
   individually and keep their original text; all other messages in the
   catalog are still processed.

Untranslated messages (empty ``msgstr``) are pseudo-localized from their
``msgid``, so the transformation works on POT files and untranslated PO
files alike.

Command-Line Usage
==================

The ``pybabel pseudo`` command reads a PO or POT file and writes a
pseudo-localized PO file::

    $ pybabel pseudo --input-file=messages.pot --output-file=messages.pseudo.po
    $ pybabel pseudo -i messages.po -o messages.pseudo.po --expansion=0.5 --seed=1234
    $ pybabel pseudo -i messages.po --html   # writes to standard output

Messages that fail to transform are logged as errors with their message
id; the remaining messages are still written to the output file.

Comparing Source, Pseudo-Translation and Interpolation
======================================================

The ``babel.messages.pseudo`` module doubles as a small demo command that
prints the source message, its pseudo-localization and the interpolated
result side by side (it runs in well under 90 seconds)::

    $ python -m babel.messages.pseudo "Hello {name}" name=Li
    source:        Hello {name}
    pseudo:        \u27e6\u0124\u00e9\u013e\u013c\u00f3 {name}\u7684\u662f\u27e7
    interpolated:  \u27e6\u0124\u00e9\u013e\u013c\u00f3 Li\u7684\u662f\u27e7

    $ python -m babel.messages.pseudo --html "<a title='Keep'>Text</a>"
    source:        <a title='Keep'>Text</a>
    pseudo:        \u27e6<a title='Keep'>\u0162\u00e9\u1e8b\u0163</a>\u4eba\u27e7
    interpolated:  \u27e6<a title='Keep'>\u0162\u00e9\u1e8b\u0163</a>\u4eba\u27e7

Python API
==========

.. module:: babel.messages.pseudo

The transformation is implemented by the
:class:`~babel.messages.pseudo.PseudoLocalizer` class::

    >>> from babel.messages.pseudo import PseudoLocalizer
    >>> localizer = PseudoLocalizer(expansion=0.3, seed=42)
    >>> pseudo = localizer.localize("Hello {name}")
    >>> pseudo.format(name="Li")  # placeholders stay interpolatable

``localize_catalog(catalog)`` transforms every message of a catalog in
place and returns a list of ``(message, error)`` pairs for the messages
that failed, leaving their original text untouched.
