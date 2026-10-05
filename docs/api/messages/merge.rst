Translator Comment Merging
==========================

.. module:: babel.messages.merge

This module provides an explicit, inspectable plan for merging translator
comments from multiple catalogs into a target catalog.  See
:ref:`merging translator comments` for an overview.

Merge Plans
-----------

.. autoclass:: TranslatorCommentMergePlan
   :members:

.. autoclass:: PlannedCommentMerge
   :members:

.. autoclass:: MergeIssue
   :members:

Exceptions
----------

.. autoexception:: TranslatorCommentMergeError

.. autoexception:: BaselineChangedError
