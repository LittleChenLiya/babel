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
from babel.messages.split import (
    CatalogSplitError,
    MergeConflictError,
    merge_catalogs,
    split_catalog,
)

__all__ = [
    "Catalog",
    "CatalogSplitError",
    "MergeConflictError",
    "Message",
    "TranslationError",
    "merge_catalogs",
    "split_catalog",
]
