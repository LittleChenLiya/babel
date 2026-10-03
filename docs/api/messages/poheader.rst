PO File Header Editing
======================

.. module:: babel.messages.poheader

This module edits the header metadata of an existing PO file **in place**:
only the byte range of the header ``msgstr`` is rewritten, while message
entries, comments, unknown header fields and the file's newline style are
preserved byte for byte.  The header message and its line range are located
with the same structural rules the regular PO parser uses, and string
literals are decoded and re-encoded with the parser's own
:func:`~babel.messages.pofile.unescape` and
:func:`~babel.messages.pofile.escape`, so the result can always be read
back with :func:`~babel.messages.pofile.read_po`.

The edit is refused with :class:`PoHeaderError` (leaving the input
untouched) when the file has no uniquely identifiable header message or
the header contains a duplicate field.

.. code-block:: python

    from babel.messages.poheader import replace_po_header_fields
    new_data = replace_po_header_fields(data, {"Language": "fr"})

A small command line demo shows the modified line range (a dry run unless
``--in-place`` is given)::

    python -m babel.messages.poheader locale/fr/LC_MESSAGES/app.po Language=fr

.. autoclass:: PoHeaderError

.. autofunction:: edit_po_header

.. autofunction:: replace_po_header_fields

.. autofunction:: edit_po_file

.. autoclass:: HeaderEdit
