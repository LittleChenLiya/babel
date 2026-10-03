PO File Header Editor
=====================

.. module:: babel.messages.pofile_header

The PO file header editor preserves the body text of a PO file when
editing header fields.

When only a few metadata headers of a PO file need to change, re-writing
the whole catalog through :func:`~babel.messages.pofile.write_po` would
re-flow every message and destroy the original formatting of the body.
:func:`edit_po_header` uses the existing PO parsing rules to locate the
header message and its continuation lines, then replaces only the
specified header fields while leaving every other byte of the file
untouched.

Usage
-----

.. code-block:: python

   from babel.messages.pofile_header import edit_po_header

   # Edit the Language field of a PO file, preserving the body.
   with open('messages.po', 'rb') as f:
       data = f.read()
   result = edit_po_header(data, {'Language': 'fr'})
   with open('messages.po', 'wb') as f:
       f.write(result)

The function also accepts a path or file-like object as the source, and
can write the result directly to an output destination:

.. code-block:: python

   edit_po_header('messages.po', {'Language': 'fr'}, output='messages.po')

See ``scripts/demo_pofile_header.py`` in the source distribution for a
short demo that shows the byte-level modification range.

API
---

.. autofunction:: edit_po_header

.. autoclass:: HeaderEditError

