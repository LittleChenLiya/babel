Messages and Catalogs
=====================

.. module:: babel.messages.catalog

This module provides a basic interface to hold catalog and message
information.  It's generally used to modify a gettext catalog but it is
not being used to actually use the translations.

Catalogs
--------

.. autoclass:: Catalog
   :members:
   :special-members: __iter__

Messages
--------

.. autoclass:: Message
   :members:

Renaming messages
-----------------

Translation maintenance often requires adjusting many message IDs at once.
The :class:`RenamePlan` interface is a two-phase, plan-then-apply operation:
:meth:`Catalog.plan_renames` validates every rename and checks for
collisions, and :meth:`RenamePlan.apply` produces a new catalog without
modifying the catalog the plan was created from.

A message's identity is its ``(msgid, context)`` pair, where the msgid is
the full ``(singular, plural)`` tuple for pluralizable messages.  Two
messages with the same msgid but different contexts are distinct identities
and never conflict with each other.

.. autoclass:: RenamePlan
   :members:

.. autoclass:: RenameEntry
   :members:

.. autoclass:: RenameConflictInfo
   :members:

Exceptions
----------

.. autoexception:: TranslationError

.. autoexception:: RenameError

.. autoexception:: RenameConflict

