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
from babel.messages.fallback import (
    FallbackEntry,
    list_fallbacks,
)

__all__ = [
    "Catalog",
    "FallbackEntry",
    "Message",
    "TranslationError",
    "list_fallbacks",
]
