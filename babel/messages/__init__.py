"""
babel.messages
~~~~~~~~~~~~~~

Support for ``gettext`` message catalogs.

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from babel.messages.catalog import (
    Catalog,
    Message,
    TranslationError,
)
from babel.messages.commentmerge import (
    MergeConflict,
    MergePlanError,
    MissingTarget,
    TranslatorCommentMergePlan,
)

__all__ = [
    "Catalog",
    "MergeConflict",
    "MergePlanError",
    "Message",
    "MissingTarget",
    "TranslationError",
    "TranslatorCommentMergePlan",
]
