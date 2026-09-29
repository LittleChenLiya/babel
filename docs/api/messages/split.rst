Splitting and Merging Catalogs
==============================

.. module:: babel.messages.split

This module splits a message catalog into per-owner catalogs based on the
source path prefixes of message locations, and merges those catalogs back
into one.  Prefix matching is component-wise (``src/app`` does not match
``src/apple``); a message matching several groups is copied into all of
them, and messages matching no group end up in a remainder catalog.

Functions
---------

.. autofunction:: split_catalog
.. autofunction:: merge_catalogs
.. autofunction:: path_matches_prefix
.. autofunction:: split_path

Exceptions
----------

.. autoexception:: CatalogSplitError
.. autoexception:: MergeConflictError
