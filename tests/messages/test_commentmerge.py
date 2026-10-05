#
# Copyright (C) 2013-2026 by the Babel Team.
# All rights reserved.
#
# This software is licensed as described in the file LICENSE, which
# you should have received as part of this distribution. The terms
# are also available at https://github.com/python-babel/babel/blob/master/LICENSE.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at https://github.com/python-babel/babel/commits/master/.

"""Tests for :mod:`babel.messages.commentmerge`."""

from __future__ import annotations

from pathlib import Path

import pytest

from babel.messages.catalog import Catalog
from babel.messages.commentmerge import (
    MergeConflict,
    MergePlanError,
    TranslatorCommentMergePlan,
)
from babel.messages.pofile import read_po


def _write_po(directory: Path, name: str, content: str) -> Path:
    """Write *content* to ``<directory>/<name>`` and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def _read_catalog(path: Path) -> Catalog:
    with open(path, "rb") as fileobj:
        return read_po(fileobj)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TARGET_PO = """\
# French translations for PROJECT.
# Copyright (C) 2026 ORGANIZATION
#
msgid ""
msgstr ""
"Project-Id-Version: PROJECT 1.0\n"
"Content-Type: text/plain; charset=utf-8\n"
"Content-Transfer-Encoding: 8bit\n"
"Language: fr\n"

# Target comment for foo
#. Auto comment for foo
#: main.py:1
#, manual
msgid "foo"
msgstr "le foo"

# Target comment for bar
msgctxt "ctx"
msgid "bar"
msgstr "la bar"

msgid "only in target"
msgstr "seulement dans la cible"
"""

SOURCE1_PO = """\
# Translator one for foo
# Translator two for foo
#. Auto comment same text
msgid "foo"
msgstr ""

# Source comment for bar ctx
msgctxt "ctx"
msgid "bar"
msgstr ""

# Source comment for missing msg
msgid "missing"
msgstr ""
"""

SOURCE2_PO = """\
# Translator one for foo
# Translator three for foo
msgid "foo"
msgstr ""

# Plural message comment
msgid "one item"
msgid_plural "%d items"
msgstr[0] ""
msgstr[1] ""
"""


@pytest.fixture()
def merge_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a target directory and two source directories."""
    target = tmp_path / "target"
    source1 = tmp_path / "src1"
    source2 = tmp_path / "src2"
    _write_po(target, "messages.po", TARGET_PO)
    _write_po(source1, "messages.po", SOURCE1_PO)
    _write_po(source2, "messages.po", SOURCE2_PO)
    return target, source1, source2


# ---------------------------------------------------------------------------
# Dedup and stable order
# ---------------------------------------------------------------------------


def test_identical_translator_comments_appear_once(merge_dirs):
    """Two identical translator comments from different directories appear
    only once in the merged result."""
    target, source1, source2 = merge_dirs
    plan = TranslatorCommentMergePlan(target, [source1, source2])
    plan.apply()

    catalog = _read_catalog(target / "messages.po")
    foo = catalog.get("foo")
    assert foo is not None
    # "Translator one for foo" appears in both sources; it must be deduplicated.
    assert foo.user_comments == [
        "Target comment for foo",
        "Translator one for foo",
        "Translator two for foo",
        "Translator three for foo",
    ]


def test_translator_comments_stable_order(merge_dirs):
    """Comments are merged in a stable, deterministic order: target comments
    first, then source comments in source-directory order."""
    target, source1, source2 = merge_dirs
    plan = TranslatorCommentMergePlan(target, [source1, source2])
    plan.apply()

    catalog = _read_catalog(target / "messages.po")
    foo = catalog.get("foo")
    assert foo is not None
    assert foo.user_comments == [
        "Target comment for foo",
        "Translator one for foo",
        "Translator two for foo",  # from source1
        "Translator three for foo",  # from source2
    ]


# ---------------------------------------------------------------------------
# Auto comments, locations and flags are not mixed in
# ---------------------------------------------------------------------------


def test_auto_comment_same_text_remains_independent(merge_dirs):
    """An automatic comment with the same text as a translator comment stays
    independent (``#.`` vs ``#``) and is not merged into translator comments."""
    target, source1, source2 = merge_dirs
    plan = TranslatorCommentMergePlan(target, [source1, source2])
    plan.apply()

    catalog = _read_catalog(target / "messages.po")
    foo = catalog.get("foo")
    assert foo is not None
    # The source auto comment "Auto comment same text" must NOT be in user_comments.
    assert "Auto comment same text" not in foo.user_comments
    # The target auto comment is preserved.
    assert "Auto comment for foo" in foo.auto_comments
    # The source auto comment is not merged into auto_comments either (only
    # translator comments are merged).
    assert "Auto comment same text" not in foo.auto_comments


def test_locations_and_flags_not_merged(merge_dirs):
    """Source locations and flags are never merged into the target."""
    target, source1, source2 = merge_dirs
    plan = TranslatorCommentMergePlan(target, [source1, source2])
    plan.apply()

    catalog = _read_catalog(target / "messages.po")
    foo = catalog.get("foo")
    assert foo is not None
    # Target locations and flags are preserved, not replaced by source data.
    assert foo.locations == [("main.py", 1)]
    assert "manual" in foo.flags


def test_same_text_different_type_preserved(merge_dirs):
    """The same text used as both a translator comment and an automatic
    comment is preserved as two independent comments of different types."""
    target, source1, source2 = merge_dirs
    _write_po(
        source1,
        "extra.po",
        '#. Shared text\n# Shared text\nmsgid "foo"\nmsgstr ""\n',
    )
    plan = TranslatorCommentMergePlan(target, [source1, source2])
    plan.apply()

    catalog = _read_catalog(target / "messages.po")
    foo = catalog.get("foo")
    assert foo is not None
    # "Shared text" appears once as a translator comment ...
    assert foo.user_comments.count("Shared text") == 1
    # ... and the target's own auto comment is still there.
    assert "Auto comment for foo" in foo.auto_comments


# ---------------------------------------------------------------------------
# Plural and context positioning
# ---------------------------------------------------------------------------


def test_context_message_positioning(merge_dirs):
    """Translator comments are attached to the message with the matching
    context (``msgctxt``), not to a message with the same id but no context."""
    target, source1, source2 = merge_dirs
    plan = TranslatorCommentMergePlan(target, [source1, source2])
    plan.apply()

    catalog = _read_catalog(target / "messages.po")
    # "bar" with context "ctx" gets the source comment.
    bar_ctx = catalog.get("bar", context="ctx")
    assert bar_ctx is not None
    assert bar_ctx.user_comments == [
        "Target comment for bar",
        "Source comment for bar ctx",
    ]
    # There is no context-less "bar" in the target; the comment must not
    # have been attached to the wrong message.
    assert catalog.get("bar") is None


def test_plural_message_positioning(tmp_path: Path):
    """A plural source message is matched to the same plural target message
    (by singular id + context) and comments are attached to it."""
    target = tmp_path / "target"
    source = tmp_path / "src"
    _write_po(
        target,
        "messages.po",
        'msgid "one item"\nmsgid_plural "%d items"\n'
        'msgstr[0] "un article"\nmsgstr[1] "%d articles"\n',
    )
    _write_po(
        source,
        "messages.po",
        "# Plural translator comment\n"
        'msgid "one item"\nmsgid_plural "%d items"\n'
        'msgstr[0] ""\nmsgstr[1] ""\n',
    )
    plan = TranslatorCommentMergePlan(target, [source])
    plan.apply()

    catalog = _read_catalog(target / "messages.po")
    msg = catalog.get("one item")
    assert msg is not None
    assert msg.pluralizable
    assert msg.user_comments == ["Plural translator comment"]
    # Translations are unchanged.
    assert msg.string == ("un article", "%d articles")


def test_singular_and_plural_share_identity(tmp_path: Path):
    """A singular message and a plural message with the same singular id
    share the same complete identity; comments merge across them."""
    target = tmp_path / "target"
    source = tmp_path / "src"
    # Target has the plural form.
    _write_po(
        target,
        "messages.po",
        'msgid "item"\nmsgid_plural "items"\nmsgstr[0] "article"\nmsgstr[1] "articles"\n',
    )
    # Source has the singular form with a translator comment.
    _write_po(
        source,
        "messages.po",
        "# Singular source comment\nmsgid \"item\"\nmsgstr \"\"\n",
    )
    plan = TranslatorCommentMergePlan(target, [source])
    plan.apply()

    catalog = _read_catalog(target / "messages.po")
    msg = catalog.get("item")
    assert msg is not None
    # The source comment is attached to the (plural) target message.
    assert msg.user_comments == ["Singular source comment"]
    # The plural translations are unchanged.
    assert msg.string == ("article", "articles")


# ---------------------------------------------------------------------------
# Conflicts and missing targets
# ---------------------------------------------------------------------------


def test_conflict_identity_reported(merge_dirs):
    """A complete identity contributed by more than one source directory is
    reported as a conflict before application."""
    target, source1, source2 = merge_dirs
    plan = TranslatorCommentMergePlan(target, [source1, source2])
    assert any(
        isinstance(c, MergeConflict) and c.identity == ("foo", None) for c in plan.conflicts
    )


def test_missing_target_reported(merge_dirs):
    """A source identity that does not exist in the target is reported as a
    missing target before application."""
    target, source1, source2 = merge_dirs
    plan = TranslatorCommentMergePlan(target, [source1, source2])
    missing = {m.identity for m in plan.missing_targets}
    assert ("missing", None) in missing
    assert ("one item", None) in missing


def test_missing_target_not_modified(merge_dirs):
    """Missing targets are reported but not written anywhere."""
    target, source1, source2 = merge_dirs
    plan = TranslatorCommentMergePlan(target, [source1, source2])
    plan.apply()
    # The target file must not contain the missing source messages.
    content = (target / "messages.po").read_text(encoding="utf-8")
    assert 'msgid "missing"' not in content
    assert 'msgid "one item"' not in content


# ---------------------------------------------------------------------------
# Baseline binding
# ---------------------------------------------------------------------------


def test_baseline_change_rejects_application(merge_dirs):
    """If the target directory changes between plan creation and application,
    apply() raises MergePlanError and nothing is written."""
    target, source1, source2 = merge_dirs
    plan = TranslatorCommentMergePlan(target, [source1, source2])

    # Mutate the target directory after the plan was created.
    target_file = target / "messages.po"
    original = target_file.read_bytes()
    target_file.write_text(
        target_file.read_text(encoding="utf-8") + "\n# late comment\n",
        encoding="utf-8",
    )

    with pytest.raises(MergePlanError):
        plan.apply()

    # The file was not rewritten by apply(); it still has the late comment.
    assert target_file.read_bytes() != original
    assert b"# late comment" in target_file.read_bytes()


def test_unchanged_baseline_applies(merge_dirs):
    """When the target directory is unchanged, apply() succeeds."""
    target, source1, source2 = merge_dirs
    plan = TranslatorCommentMergePlan(target, [source1, source2])
    # No mutation: apply succeeds.
    plan.apply()
    catalog = _read_catalog(target / "messages.po")
    assert catalog.get("foo").user_comments  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_round_trip_preserves_comments(merge_dirs):
    """Reading, merging, writing and reading back preserves translator
    comments, automatic comments, locations, flags, context and plural
    translations."""
    target, source1, source2 = merge_dirs
    before = _read_catalog(target / "messages.po")

    plan = TranslatorCommentMergePlan(target, [source1, source2])
    plan.apply()

    after = _read_catalog(target / "messages.po")

    for message in before:
        if not message.id:
            continue
        merged = after.get(message.id, context=message.context)
        assert merged is not None
        # Translations and message ids are unchanged.
        assert merged.string == message.string
        assert merged.id == message.id
        assert merged.context == message.context
        # Automatic comments, locations and flags are unchanged.
        assert merged.auto_comments == message.auto_comments
        assert merged.locations == message.locations
        assert merged.flags == message.flags
        # Translator comments only grew (merged), never shrunk.
        assert set(message.user_comments).issubset(set(merged.user_comments))


def test_round_trip_plural_translations_unchanged(tmp_path: Path):
    """Plural translations survive the round-trip unchanged."""
    target = tmp_path / "target"
    source = tmp_path / "src"
    _write_po(
        target,
        "messages.po",
        'msgid "apple"\nmsgid_plural "apples"\nmsgstr[0] "pomme"\nmsgstr[1] "pommes"\n',
    )
    _write_po(
        source,
        "messages.po",
        "# Source comment\n"
        'msgid "apple"\nmsgid_plural "apples"\n'
        'msgstr[0] ""\nmsgstr[1] ""\n',
    )
    plan = TranslatorCommentMergePlan(target, [source])
    plan.apply()

    catalog = _read_catalog(target / "messages.po")
    msg = catalog.get("apple")
    assert msg is not None
    assert msg.string == ("pomme", "pommes")
    assert msg.user_comments == ["Source comment"]


# ---------------------------------------------------------------------------
# Domain filtering
# ---------------------------------------------------------------------------


def test_domain_filtering(tmp_path: Path):
    """When a domain is given, only ``<domain>.po`` files are considered."""
    target = tmp_path / "target"
    source = tmp_path / "src"
    _write_po(
        target,
        "messages.po",
        "# Target foo comment\nmsgid \"foo\"\nmsgstr \"le foo\"\n",
    )
    _write_po(
        target,
        "other.po",
        "# Target other comment\nmsgid \"other\"\nmsgstr \"l'autre\"\n",
    )
    _write_po(
        source,
        "messages.po",
        "# Source foo comment\nmsgid \"foo\"\nmsgstr \"\"\n",
    )
    _write_po(
        source,
        "other.po",
        "# Source other comment\nmsgid \"other\"\nmsgstr \"\"\n",
    )

    plan = TranslatorCommentMergePlan(target, [source], domain="messages")
    plan.apply()

    catalog = _read_catalog(target / "messages.po")
    assert catalog.get("foo").user_comments == [  # type: ignore[union-attr]
        "Target foo comment",
        "Source foo comment",
    ]
    other = _read_catalog(target / "other.po")
    assert other.get("other").user_comments == ["Target other comment"]  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_missing_target_directory_raises(tmp_path: Path):
    """A non-existent target directory raises MergePlanError."""
    with pytest.raises(MergePlanError):
        TranslatorCommentMergePlan(tmp_path / "nope", [tmp_path])


def test_missing_source_directory_raises(tmp_path: Path):
    """A non-existent source directory raises MergePlanError."""
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(MergePlanError):
        TranslatorCommentMergePlan(target, [tmp_path / "nope"])


def test_no_changes_is_noop(tmp_path: Path):
    """When there are no source comments, apply() is a no-op."""
    target = tmp_path / "target"
    source = tmp_path / "src"
    _write_po(target, "messages.po", 'msgid "foo"\nmsgstr "le foo"\n')
    _write_po(source, "messages.po", 'msgid "bar"\nmsgstr ""\n')

    before = (target / "messages.po").read_bytes()
    plan = TranslatorCommentMergePlan(target, [source])
    assert plan.changes == {}
    plan.apply()
    assert (target / "messages.po").read_bytes() == before
