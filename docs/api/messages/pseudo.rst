Pseudo-Localization
===================

.. module:: babel.messages.pseudo

The pseudo-localization support transforms message catalogs into
deterministic pseudo-translations.  See :doc:`/pseudo` for the
transformation rules and command-line usage.

.. autoclass:: PseudoLocalizer
   :members: localize, localize_message, localize_catalog, is_marked

.. autofunction:: interpolate

.. autoexception:: PseudoLocalizationError
