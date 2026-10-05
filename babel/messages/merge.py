"""
babel.messages.merge
~~~~~~~~~~~~~~~~~~~~

Explicit merge planning for translator (user) comments across catalogs.

This module implements :class:`TranslatorCommentMergePlan`, an explicit,
inspectable plan that merges *translator comments* (``# `` comments, stored
as ``Message.user_comments``) from one or more source catalogs into a target
catalog.

The plan has the following guarantees:

* Messages are matched by their *full message identity*: the complete
  message ID (including the plural form for pluralizable messages) plus the
  message context (``msgctxt``).
* Only translator comments are merged.  Automatic comments (``#.``), source
  locations (``#:``) and flags (``#,``) are never mixed into translator
  comments; a comment text that exists both as an automatic comment and as
  a translator comment stays independent in each category.
* Duplicate translator comments are removed with stable ordering: the
  target's existing comments keep their order, then comments from the
  source catalogs are appended in the order the sources were added, keeping
  only the first occurrence of each distinct text.
* The plan is bound to a baseline fingerprint of the target catalog taken
  when the plan is built.  If the target catalog changes before the plan is
  applied, application is refused with :exc:`BaselineChangedError`.
* Applying a plan never changes translations (``msgstr``) or message IDs
  (``msgid``/``msgctxt``); only ``Message.user_comments`` is updated.
* Conflicting message identities and source messages without a target are
  collected centrally in :attr:`TranslatorCommentMergePlan.issues` and are
  reported together before anything is applied; :meth:`apply` refuses to
  run while issues are pending.

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

    from babel.messages.catalog import Catalog, Message, _MessageID

__all__ = [
    "BaselineChangedError",
    "MergeIssue",
    "PlannedCommentMerge",
    "TranslatorCommentMergeError",
    "TranslatorCommentMergePlan",
]

#: Issue kind: a source message identity conflicts with the target identity.
CONFLICT = 'conflict'
#: Issue kind: a source message has no matching message in the target catalog.
MISSING_TARGET = 'missing-target'


def _normalize_id(id):
    """Normalize a message ID to a tuple for identity comparison.

    A plain string becomes a 1-tuple; a ``(singular, plural)`` tuple stays
    as-is.  This makes a singular message and a pluralizable message with
    the same singular form compare as *different* identities.
    """
    if isinstance(id, str):
        return (id,)
    return tuple(id)


def _message_identity(message):
    """The full identity of a message: (normalized ID, context)."""
    return (_normalize_id(message.id), message.context)


def _catalog_fingerprint(catalog):
    """Compute a fingerprint of the target catalog's merge-relevant state.

    The fingerprint covers the message keys, full message IDs, contexts,
    translations and existing translator comments, so that any change to
    the target catalog between planning and applying invalidates the plan.
    """
    digest = hashlib.sha256()
    digest.update(repr(catalog.header_comment).encode('utf-8'))
    for key, message in catalog._messages.items():
        digest.update(
            repr(
                (
                    key,
                    _normalize_id(message.id),
                    message.string,
                    message.context,
                    tuple(message.user_comments),
                ),
            ).encode('utf-8'),
        )
        digest.update(b'\x00')
    return digest.hexdigest()


@dataclass(frozen=True)
class MergeIssue:
    """A single problem found while building a merge plan.

    Issues are collected centrally in
    :attr:`TranslatorCommentMergePlan.issues` and reported before anything
    is applied.
    """

    #: ``'conflict'`` or ``'missing-target'``
    kind: Literal['conflict', 'missing-target']
    #: the message ID of the offending source message
    id: _MessageID
    #: the message context of the offending source message (or ``None``)
    context: str | None
    #: index of the source catalog (in add order) the message came from
    source_index: int
    #: human-readable explanation
    detail: str

    def __str__(self) -> str:
        return (
            f"[{self.kind}] {self.id!r} "
            f"(context={self.context!r}, source #{self.source_index}): {self.detail}"
        )


@dataclass(frozen=True)
class PlannedCommentMerge:
    """The planned translator-comment merge for a single target message."""

    #: the full message ID (string or ``(singular, plural)`` tuple)
    id: _MessageID
    #: the message context (or ``None``)
    context: str | None
    #: the merged translator comments, in stable order, already deduplicated
    comments: tuple[str, ...]


class TranslatorCommentMergeError(Exception):
    """Raised when a merge plan cannot be applied.

    Carries the centrally collected :attr:`issues` that prevented
    application, if any.
    """

    def __init__(self, message: str, issues: Iterable[MergeIssue] = ()) -> None:
        self.issues: tuple[MergeIssue, ...] = tuple(issues)
        if self.issues:
            report = '\n'.join(f"  - {issue}" for issue in self.issues)
            message = f"{message}\n{report}"
        super().__init__(message)


class BaselineChangedError(TranslatorCommentMergeError):
    """Raised when the target catalog changed after the plan was built."""


class TranslatorCommentMergePlan:
    """An explicit plan to merge translator comments into a target catalog.

    The plan is built from a *target* catalog and any number of *source*
    catalogs.  Building the plan does not modify anything; call
    :meth:`apply` to execute it.

    >>> from babel.messages.catalog import Catalog
    >>> target = Catalog()
    >>> target.add('hello', 'hola', user_comments=['greeting'])
    <Message 'hello' (flags: [])>
    >>> source = Catalog()
    >>> source.add('hello', user_comments=['greeting', 'from source'])
    <Message 'hello' (flags: [])>
    >>> plan = TranslatorCommentMergePlan(target, [source])
    >>> plan.entries[0].comments
    ('greeting', 'from source')
    >>> plan.apply()
    1
    >>> target['hello'].user_comments
    ['greeting', 'from source']
    """

    def __init__(self, target: Catalog, sources: Iterable[Catalog] = ()) -> None:
        """Build a merge plan.

        :param target: the catalog that will receive the merged translator
                       comments; a baseline fingerprint of it is taken now
        :param sources: catalogs to harvest translator comments from, in
                        the order they should be merged
        """
        self.target = target
        self._baseline = _catalog_fingerprint(target)
        self._issues: list[MergeIssue] = []
        self._entries: list[PlannedCommentMerge] = []
        # key -> [index into _entries, list of comment texts being built]
        self._by_key: dict[str | tuple[str, str], list] = {}
        # key -> full identity seen in the sources, for conflict detection
        self._source_identities: dict[
            str | tuple[str, str],
            tuple[tuple[str, ...], str | None],
        ] = {}
        self._source_count = 0
        for source in sources:
            self.add_source(source)

    def add_source(self, source: Catalog) -> None:
        """Add a source catalog to the plan.

        Must be called before :meth:`apply`.  Source messages are matched
        against the target by full message identity; translator comments
        are appended in source order with stable deduplication.

        :param source: the catalog to harvest translator comments from
        """
        source_index = self._source_count
        self._source_count += 1
        # Iterate the message storage directly: ``Catalog.__iter__`` would
        # materialize the header message, which is not a merge source.
        for message in source._messages.values():
            self._plan_message(message, source_index)

    def _plan_message(self, message: Message, source_index: int) -> None:
        key = self.target._key_for(message.id, message.context)
        identity = _message_identity(message)
        target_message = self.target._messages.get(key)

        if target_message is None:
            self._issues.append(
                MergeIssue(
                    kind=MISSING_TARGET,
                    id=message.id,
                    context=message.context,
                    source_index=source_index,
                    detail='no message with this identity exists in the target catalog',
                ),
            )
            return

        target_identity = _message_identity(target_message)
        if target_identity != identity:
            self._issues.append(
                MergeIssue(
                    kind=CONFLICT,
                    id=message.id,
                    context=message.context,
                    source_index=source_index,
                    detail=(
                        f'source identity {identity!r} conflicts with target '
                        f'identity {target_identity!r}'
                    ),
                ),
            )
            return

        seen_identity = self._source_identities.setdefault(key, identity)
        if seen_identity != identity:
            self._issues.append(
                MergeIssue(
                    kind=CONFLICT,
                    id=message.id,
                    context=message.context,
                    source_index=source_index,
                    detail=(
                        f'source identity {identity!r} conflicts with identity '
                        f'{seen_identity!r} seen in an earlier source catalog'
                    ),
                ),
            )
            return

        if not message.user_comments:
            return

        slot = self._by_key.get(key)
        if slot is None:
            # Seed with the target's existing translator comments, in order.
            comments = list(target_message.user_comments)
            entry = PlannedCommentMerge(
                id=target_message.id,
                context=target_message.context,
                comments=(),  # finalized when the plan is inspected/applied
            )
            self._entries.append(entry)
            slot = [len(self._entries) - 1, comments]
            self._by_key[key] = slot
        comments = slot[1]
        for comment in message.user_comments:
            if comment not in comments:
                comments.append(comment)

    def _finalize(self) -> None:
        """Freeze the accumulated comment lists into the planned entries."""
        for index, comments in self._by_key.values():
            entry = self._entries[index]
            self._entries[index] = PlannedCommentMerge(
                id=entry.id,
                context=entry.context,
                comments=tuple(comments),
            )
        self._by_key = {}

    @property
    def issues(self) -> tuple[MergeIssue, ...]:
        """All conflicts and missing targets found while building the plan."""
        return tuple(self._issues)

    @property
    def conflicts(self) -> tuple[MergeIssue, ...]:
        """The issues of kind ``'conflict'``."""
        return tuple(issue for issue in self._issues if issue.kind == CONFLICT)

    @property
    def missing_targets(self) -> tuple[MergeIssue, ...]:
        """The issues of kind ``'missing-target'``."""
        return tuple(issue for issue in self._issues if issue.kind == MISSING_TARGET)

    @property
    def entries(self) -> tuple[PlannedCommentMerge, ...]:
        """The planned per-message comment merges, in target order."""
        if self._by_key:
            self._finalize()
        return tuple(self._entries)

    def planned_comments(
        self,
        id: _MessageID,
        context: str | None = None,
    ) -> tuple[str, ...] | None:
        """Return the merged translator comments planned for a message.

        :param id: the message ID
        :param context: the message context, or ``None`` for no context
        :return: the planned comments, or ``None`` if nothing is planned
                 for this message
        """
        key = self.target._key_for(id, context)
        if self._by_key:
            self._finalize()
        for entry in self._entries:
            if self.target._key_for(entry.id, entry.context) == key:
                return entry.comments
        return None

    def check_baseline(self) -> None:
        """Verify the target catalog still matches the plan's baseline.

        :raise BaselineChangedError: if the target catalog changed since
                                     the plan was built
        """
        if _catalog_fingerprint(self.target) != self._baseline:
            raise BaselineChangedError(
                'the target catalog changed after this merge plan was built; '
                'build a new plan instead of applying this one',
            )

    def apply(self) -> int:
        """Apply the plan to the target catalog.

        Only ``Message.user_comments`` is modified; translations, message
        IDs, contexts, automatic comments, locations and flags are left
        untouched.

        :raise BaselineChangedError: if the target catalog changed since
                                     the plan was built
        :raise TranslatorCommentMergeError: if conflicting identities or
                                            missing targets were found
        :return: the number of messages whose comments were updated
        """
        self.check_baseline()
        if self._issues:
            raise TranslatorCommentMergeError(
                f'refusing to apply merge plan with {len(self._issues)} unresolved issue(s)',
                issues=self._issues,
            )
        if self._by_key:
            self._finalize()
        updated = 0
        for entry in self._entries:
            key = self.target._key_for(entry.id, entry.context)
            message = self.target._messages[key]
            comments = list(entry.comments)
            if message.user_comments != comments:
                message.user_comments = comments
                updated += 1
        # Re-bind to the post-merge state so a second apply() is a no-op
        # rather than a baseline failure.
        self._baseline = _catalog_fingerprint(self.target)
        return updated
