Splitting and Merging Catalogs
==============================

.. module:: babel.messages.splitmerge

This module splits a catalog into per-area catalogs based on the source file
prefixes in message locations, and merges translated per-area catalogs back
into a single catalog.  A message referenced from several areas is present
in every matching catalog; messages without a matching prefix go to a
separate remainder catalog.

Functions
---------

.. autofunction:: split_catalog

.. autofunction:: merge_catalogs

Exceptions
----------

.. autoexception:: SplitMergeError

.. autoexception:: MergeConflictError
   :members:

.. autoclass:: MergeConflict
   :members:
