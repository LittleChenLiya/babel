.. -*- mode: rst; encoding: utf-8 -*-

.. _pseudo-localization:

Pseudo-localization
===================

Babel can pseudo-localize message catalogs: it transforms source messages
into deterministic "fake translations" that make it possible to check user
interfaces for length/expansion problems and interpolation errors before
real translations are available.

The functionality lives in the `babel.messages.pseudo` module and is
exposed through the `pybabel pseudo` command (see :doc:`cmdline`).

Transformation rules
--------------------

1. **Character mapping.** Latin letters (a-z, A-Z) are mapped to accented
   look-alikes using a fixed, deterministic table (for example `a` → `à`,
   `N` → `Ñ`, `s` → `ŝ`). Non-Latin text (CJK, Cyrillic, Arabic, digits,
   punctuation) is passed through unchanged.

2. **Expansion.** Plain text is expanded by a configurable ratio
   (`--expansion`, default 0.3 = 30%). Padding characters are chosen
   deterministically from a fixed seed (`--seed`, default 0), so repeated
   runs produce identical output.

3. **Boundary markers.** Every transformed message is wrapped in the
   markers `⟦` (U+27E6) and `⟧` (U+27E7) so truncated or missing
   translations are easy to spot in the UI.

4. **Placeholder protection.** Format placeholders stay intact and
   parseable:

   * python-format: `%s`, `%(name)s`, `%05.2f` and the escaped percent
     `%%`;
   * brace-format: `{name}`, `{0}`, `{name!r:>10}`, escaped braces
     `{{` / `}}` and nested fields such as `{name:{width}}`.

5. **HTML handling.** Messages that look like HTML (auto-detected, or
   forced with `--html=always`) keep their tags, attributes and entities
   untouched; only text nodes are transformed. For example::

       <a title='Keep'>Text</a>

   becomes `⟦<a title='Keep'>Ţèẋţ …</a>⟧` — the `title` attribute is
   preserved verbatim while `Text` is transformed. Malformed HTML
   (mismatched or unclosed tags) raises `PseudoTransformError`.

6. **Plurals.** Each plural branch is transformed independently and gets
   its own boundary markers.

7. **Idempotency.** Messages that already carry boundary markers are
   returned unchanged, so running the transformation repeatedly is safe.

8. **Error isolation.** Each message is processed independently. A message
   that fails to transform is left unchanged and reported; the rest of the
   catalog is not affected.

Command line usage
------------------

Generate a pseudo-localized PO file::

    $ pybabel pseudo --input-file=messages.pot --output-file=messages-pseudo.po

Print a side-by-side comparison of the source text, the pseudo-localized
text and a sample interpolation (runs in well under 90 seconds for typical
catalogs)::

    $ pybabel pseudo --input-file=messages.pot --compare

    msgid: 'Hello {name}'
    pseudo: '⟦Ĥèļļö  àê{name}⟧'
    sample: '⟦Ĥèļļö  àêLi⟧'

Python API
----------

.. code-block:: python

    from babel.messages import pofile
    from babel.messages.pseudo import pseudo_localize_catalog, pseudo_transform

    pseudo_transform("Hello {name}")          # '⟦Ĥèļļö  àê{name}⟧'

    with open("messages.pot") as infile:
        catalog = pofile.read_po(infile)
    errors = pseudo_localize_catalog(catalog, expansion=0.3, seed=0)
    for msgid, error in errors:
        print("failed:", msgid, error)

