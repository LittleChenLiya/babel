Locale Fallback Resolution
==========================

.. module:: babel.messages.fallback

This module resolves messages across several catalogs using an explicit,
directed fallback table, and reports which locale provided each translation
and why the locales before it were skipped.

.. autoclass:: FallbackResolver
   :members:

.. autoclass:: CatalogSnapshot
   :members:

.. autoclass:: Resolution
   :members:

.. autoclass:: SkipRecord
   :members:

.. autoexception:: FallbackGraphError
