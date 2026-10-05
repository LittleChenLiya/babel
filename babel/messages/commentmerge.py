"""
babel.messages.commentmerge
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Explicit, baseline-bound plans for merging *translator comments* (``#`` user
comments) from a set of source PO directories into a target PO directory.

A merge plan is built once against a snapshot (baseline) of the target
directory and can then be inspected before it is applied.  Applying the plan
rewrites only the ``user_comments`` of the target messages; translations,
message ids, contexts, plural forms, automatic comments, source locations
and flags are never touched.  If the target directory changes between plan
creation and application, the plan is rejected and nothing is written.

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from babel.messages.catalog import Catalog, Message
from babel.messages.pofile import read_po, write_po

if TYPE_CHECKING:
    from _typeshed import StrPath

__all__ = [
    "MergeConflict",
    "MergePlanError",
    "MissingTarget",
    "TranslatorCommentMergePlan",
]

#: A complete message identity: the singular message id together with its
#: optional message context.  Pluralizable messages share their singular id,
#: so ``("foo", None)`` identifies both ``"foo"`` and ``("foo", "foos")``.
MessageIdentity = tuple[str, "str | None"]


class MergePlanError(Exception):
    """Raised when a translator comment merge plan cannot be applied."""


@dataclass(frozen=True)
class MergeConflict:
    """A complete message identity contributed by more than one source
    directory.

    The comments are still deduplicated and merged; the conflict is reported
    so that the overlap is visible before the plan is applied.
    """

    identity: MessageIdentity
    sources: tuple[tuple[str, str], ...]  # (source_dir, relative file path)


@dataclass(frozen=True)
class MissingTarget:
    """A complete message identity found in the sources but not present in
    the target directory.

    No comments are merged for these identities because there is no target
    message to attach them to.
    """

    identity: MessageIdentity
    sources: tuple[tuple[str, str], ...]  # (source_dir, relative file path)


def _message_identity(message: Message) -> MessageIdentity:
    """Return the complete identity of a message.

    The identity is the singular message id together with its context.  For
    pluralizable messages the singular id is used (matching gettext's
    ``msgid`` identity), so a plural message and its singular counterpart are
    treated as the same message.
    """
    msgid = message.id
    if isinstance(msgid, (list, tuple)):
        msgid = msgid[0]
    return (msgid, message.context)


def _po_files(directory: Path, domain: str | None) -> Iterator[Path]:
    """Yield the ``*.po`` files in *directory*, optionally restricted to a
    single *domain* (``<domain>.po``)."""
    for path in sorted(directory.glob("*.po")):
        if domain is not None and path.stem != domain:
            continue
        yield path


def _fingerprint(directory: Path, domain: str | None) -> dict[str, str]:
    """Compute a stable fingerprint of the PO files in *directory*.

    The fingerprint maps the POSIX-style relative path of each PO file to the
    SHA-256 hex digest of its bytes.
    """
    fingerprint: dict[str, str] = {}
    for path in _po_files(directory, domain):
        rel = path.relative_to(directory).as_posix()
        fingerprint[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return fingerprint


def _hash_fingerprint(fingerprint: dict[str, str]) -> str:
    """Combine a per-file fingerprint into a single digest."""
    digest = hashlib.sha256()
    for rel in sorted(fingerprint):
        digest.update(rel.encode("utf-8"))
        digest.update(fingerprint[rel].encode("ascii"))
    return digest.hexdigest()


def _dedupe(items: Iterable[str]) -> list[str]:
    """Return *items* with duplicates removed, preserving first-seen order."""
    return list(dict.fromkeys(items))


class TranslatorCommentMergePlan:
    """An explicit, baseline-bound plan for merging translator comments.

    The plan is created against a *target* directory and a set of *source*
    directories.  It collects the ``user_comments`` (translator comments) of
    every source message, groups them by complete message identity, and
    computes, for every target file, the merged translator comments for the
    messages present in that file.

    Only translator comments are ever read from the sources or written to the
    target.  Automatic comments (``#.``), source locations (``#:``) and flags
    (``#,``) are never merged.

    The plan is bound to a baseline fingerprint of the target directory.
    Applying the plan rewrites the target PO files; if the target directory
    has changed since the plan was created, :meth:`apply` raises
    :class:`MergePlanError` and nothing is written.

    :param target_dir: directory containing the target PO files
    :param source_dirs: directories containing the source PO files
    :param domain: optional domain; when given only ``<domain>.po`` files are
                    considered in both target and source directories
    :param charset: character set used to read the PO files (defaults to the
                    catalog charset, usually UTF-8)
    """

    def __init__(
        self,
        target_dir: StrPath,
        source_dirs: Iterable[StrPath],
        domain: str | None = None,
        charset: str | None = None,
    ) -> None:
        self.target_dir = Path(target_dir)
        self.source_dirs = [Path(directory) for directory in source_dirs]
        self.domain = domain
        self.charset = charset

        if not self.target_dir.is_dir():
            raise MergePlanError(
                f"target directory does not exist: {self.target_dir}",
            )
        for source_dir in self.source_dirs:
            if not source_dir.is_dir():
                raise MergePlanError(
                    f"source directory does not exist: {source_dir}",
                )

        #: Per-file baseline fingerprint of the target directory at plan time.
        self.baseline: dict[str, str] = _fingerprint(self.target_dir, self.domain)
        #: Combined digest of :attr:`baseline`.
        self.baseline_hash: str = _hash_fingerprint(self.baseline)

        #: Complete message identities contributed by more than one source
        #: directory (see :class:`MergeConflict`).
        self.conflicts: list[MergeConflict] = []
        #: Complete message identities found in the sources but not in the
        #: target directory (see :class:`MissingTarget`).
        self.missing_targets: list[MissingTarget] = []
        #: The computed changes: ``{relative_file_path: {identity: [merged
        #: translator comments]}}``.
        self.changes: dict[str, dict[MessageIdentity, list[str]]] = {}

        self._build()

    # ------------------------------------------------------------------
    # Plan construction
    # ------------------------------------------------------------------

    def _read_po(self, path: Path) -> Catalog:
        with open(path, "rb") as fileobj:
            return read_po(fileobj, charset=self.charset)

    def _build(self) -> None:
        # Collect the translator comments of every source message, grouped by
        # complete message identity.  The order of source directories, files
        # within a directory, messages within a file and comments within a
        # message is preserved so that merging is deterministic.
        source_comments: dict[
            MessageIdentity,
            list[tuple[str, str, list[str]]],
        ] = {}
        for source_dir in self.source_dirs:
            for path in _po_files(source_dir, self.domain):
                rel = path.relative_to(source_dir).as_posix()
                catalog = self._read_po(path)
                for message in catalog:
                    if not message.id or not message.user_comments:
                        continue
                    identity = _message_identity(message)
                    source_comments.setdefault(identity, []).append(
                        (source_dir.as_posix(), rel, list(message.user_comments)),
                    )

        # Conflicts: the same complete identity contributed by more than one
        # source directory.  The comments are still deduplicated and merged.
        for identity, entries in source_comments.items():
            contributing_dirs = _dedupe(entry[0] for entry in entries)
            if len(contributing_dirs) > 1:
                self.conflicts.append(
                    MergeConflict(
                        identity,
                        tuple((entry[0], entry[1]) for entry in entries),
                    ),
                )
        self.conflicts.sort(key=lambda conflict: conflict.identity)

        # Build the per-file changes and record the identities present in the
        # target directory.
        target_identities: set[MessageIdentity] = set()
        for path in _po_files(self.target_dir, self.domain):
            rel = path.relative_to(self.target_dir).as_posix()
            catalog = self._read_po(path)
            file_changes: dict[MessageIdentity, list[str]] = {}
            for message in catalog:
                if not message.id:
                    continue
                identity = _message_identity(message)
                target_identities.add(identity)
                entries = source_comments.get(identity, [])
                if not entries:
                    continue
                # Target comments come first (in their existing order), then
                # source comments in the order they were collected; duplicates
                # are removed preserving first-seen order.
                merged = _dedupe(
                    [
                        *message.user_comments,
                        *(comment for _, _, comments in entries for comment in comments),
                    ],
                )
                if merged != list(message.user_comments):
                    file_changes[identity] = merged
            if file_changes:
                self.changes[rel] = file_changes

        # Missing targets: source identities that do not exist in any target
        # file.  There is nowhere to attach these comments, so they are only
        # reported.
        for identity, entries in source_comments.items():
            if identity not in target_identities:
                self.missing_targets.append(
                    MissingTarget(
                        identity,
                        tuple((entry[0], entry[1]) for entry in entries),
                    ),
                )
        self.missing_targets.sort(key=lambda missing: missing.identity)

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------

    def apply(self) -> None:
        """Apply the plan to the target directory.

        The baseline fingerprint is recomputed and compared to the fingerprint
        captured when the plan was created.  If the target directory has
        changed, :class:`MergePlanError` is raised and no file is written.

        Only the ``user_comments`` of the target messages are rewritten;
        translations, message ids, contexts, plural forms, automatic comments,
        source locations and flags are left untouched.
        """
        current = _fingerprint(self.target_dir, self.domain)
        if current != self.baseline:
            raise MergePlanError(
                "target directory baseline has changed since the merge plan "
                "was created; refusing to apply",
            )

        for rel, file_changes in self.changes.items():
            path = self.target_dir / rel
            catalog = self._read_po(path)
            for message in catalog:
                if not message.id:
                    continue
                identity = _message_identity(message)
                if identity in file_changes:
                    message.user_comments = list(file_changes[identity])
            self._write_po(path, catalog)

    def _write_po(self, path: Path, catalog: Catalog) -> None:
        with open(path, "wb") as fileobj:
            write_po(fileobj, catalog)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def report(self) -> str:
        """Return a human-readable summary of the plan.

        The report lists the conflicts, missing targets and the per-file
        changes, so that the plan can be reviewed before it is applied.
        """
        lines: list[str] = []
        lines.append(f"Target directory: {self.target_dir}")
        lines.append(f"Source directories: {', '.join(str(d) for d in self.source_dirs)}")
        if self.domain is not None:
            lines.append(f"Domain: {self.domain}")
        lines.append(f"Baseline: {self.baseline_hash}")
        lines.append("")

        if self.conflicts:
            lines.append(f"Conflicts ({len(self.conflicts)}):")
            for conflict in self.conflicts:
                lines.append(
                    f"  - {_format_identity(conflict.identity)} "
                    f"from {_format_sources(conflict.sources)}",
                )
            lines.append("")

        if self.missing_targets:
            lines.append(f"Missing targets ({len(self.missing_targets)}):")
            for missing in self.missing_targets:
                lines.append(
                    f"  - {_format_identity(missing.identity)} "
                    f"in {_format_sources(missing.sources)}",
                )
            lines.append("")

        if self.changes:
            total = sum(len(changes) for changes in self.changes.values())
            lines.append(f"Changes ({total} messages in {len(self.changes)} files):")
            for rel in sorted(self.changes):
                lines.append(f"  {rel}:")
                for identity in sorted(self.changes[rel]):
                    comments = self.changes[rel][identity]
                    lines.append(
                        f"    - {_format_identity(identity)} "
                        f"({len(comments)} translator comments)",
                    )
        else:
            lines.append("No changes.")
        return "\n".join(lines)


def _format_identity(identity: MessageIdentity) -> str:
    """Render a message identity for human consumption."""
    msgid, context = identity
    if context is not None:
        return f"{msgid!r} (context: {context!r})"
    return repr(msgid)


def _format_sources(sources: Iterable[tuple[str, str]]) -> str:
    """Render a list of ``(source_dir, relative_path)`` pairs."""
    return ", ".join(f"{directory}/{rel}" for directory, rel in sources)
