"""
babel.messages
~~~~~~~~~~~~~~

Support for ``gettext`` message catalogs.

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from babel.messages.catalog import (
    Catalog,
    DuplicateTranslationUpdateError,
    Message,
    MessageNotFoundError,
    PluralFormsMismatchError,
    StaleTranslationError,
    TranslationError,
    TranslationUpdate,
    TranslationUpdateError,
)

__all__ = [
    "Catalog",
    "DuplicateTranslationUpdateError",
    "Message",
    "MessageNotFoundError",
    "PluralFormsMismatchError",
    "StaleTranslationError",
    "TranslationError",
    "TranslationUpdate",
    "TranslationUpdateError",
]
