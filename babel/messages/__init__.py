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
from babel.messages.merge import (
    Conflict,
    Location,
    MergedMessage,
    MergeResult,
    SourceRecord,
    merge_extraction_results,
)

__all__ = [
    "Catalog",
    "Conflict",
    "Location",
    "MergeResult",
    "MergedMessage",
    "Message",
    "SourceRecord",
    "TranslationError",
    "merge_extraction_results",
]
