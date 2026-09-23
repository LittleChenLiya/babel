Message Fallback
================

.. module:: `babel.messages.fallback`

This module resolves per-message translation sources along an explicit
fallback graph.  See :ref:`message-fallback` for a narrative introduction.

.. autoclass:: FallbackResolver
   :members:

.. autoclass:: Resolution
   :members:

.. autoclass:: LocaleSkip
   :members:

.. autoexception:: FallbackError

.. autoexception:: MissingCatalogError

.. autoexception:: FallbackCycleError
