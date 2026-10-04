#
# Copyright (C) 2007-2011 Edgewall Software, 2013-2025 the Babel team
# All rights reserved.
#
# This software is licensed as described in the file LICENSE, which
# you should have received as part of this distribution. The terms
# are also available at https://github.com/python-babel/babel/blob/master/LICENSE.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at https://github.com/python-babel/babel/commits/master/.

import copy

import pytest

from babel.messages.merge import (
    ExtractionConflict,
    ExtractionRecord,
    MergedEntry,
    Source,
    merge_extraction_results,
    normalize_path,
)

WIN_SEP = chr(92)  # Windows path separator, kept literal-free for clarity


def test_same_message_same_position_dedupes_to_single_source():
    # Both extraction listings contain a.py line 5 with the same message:
    # exactly one source is kept.
    run_a = [("a.py", 5, "Hello", [], None)]
    run_b = [("a.py", 5, "Hello", [], None)]
    result = merge_extraction_results(run_a, run_b)
    assert result.conflicts == ()
    assert result.entries == (
        MergedEntry(
            message="Hello",
            context=None,
            sources=(Source(path="a.py", lineno=5, method="unknown"),),
        ),
    )


def test_same_message_same_position_different_methods_keeps_both_sources():
    run_a = [("a.py", 5, "Hello", [], None)]
    run_b = [("a.py", 5, "Hello", [], None)]
    result = merge_extraction_results(run_a, run_b, methods=("python", "python2"))
    assert result.conflicts == ()
    assert len(result.entries) == 1
    assert result.entries[0].sources == (
        Source(path="a.py", lineno=5, method="python"),
        Source(path="a.py", lineno=5, method="python2"),
    )


def test_same_msgid_different_context_stays_separate():
    run_a = [("a.py", 5, "Hello", [], None)]
    run_b = [("a.py", 9, "Hello", [], "button")]
    result = merge_extraction_results(run_a, run_b)
    assert result.conflicts == ()
    assert [(e.message, e.context) for e in result.entries] == [
        ("Hello", None),
        ("Hello", "button"),
    ]


def test_none_context_and_empty_string_context_are_not_merged():
    run_a = [("a.py", 5, "Hello", [], None)]
    run_b = [("a.py", 7, "Hello", [], "")]
    result = merge_extraction_results(run_a, run_b)
    assert result.conflicts == ()
    assert [(e.message, e.context) for e in result.entries] == [
        ("Hello", None),
        ("Hello", ""),
    ]
    assert result.entries[0].context is None
    assert result.entries[1].context == ""


def test_same_position_different_msgid_reports_both_sides_as_conflict():
    run_a = [("a.py", 5, "Hello", [], None)]
    run_b = [("a.py", 5, "Goodbye", [], None)]
    result = merge_extraction_results(run_a, run_b, methods=("python", "javascript"))
    # Neither side is picked: the position is absent from the merged list.
    assert result.entries == ()
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert isinstance(conflict, ExtractionConflict)
    assert (conflict.path, conflict.lineno) == ("a.py", 5)
    # Both sides' records are preserved.
    assert {(r.message, r.method) for r in conflict.records} == {
        ("Hello", "python"),
        ("Goodbye", "javascript"),
    }


def test_conflict_by_different_context_at_same_position():
    run_a = [("a.py", 5, "Hello", [], None)]
    run_b = [("a.py", 5, "Hello", [], "button")]
    result = merge_extraction_results(run_a, run_b, methods=("python", "javascript"))
    assert result.entries == ()
    assert len(result.conflicts) == 1
    assert {r.context for r in result.conflicts[0].records} == {None, "button"}


def test_plural_identity_uses_complete_plural_tuple():
    run_a = [
        ("a.py", 3, ("apple", "apples"), [], None),
        ("b.py", 4, ("apple", "apples"), [], None),
    ]
    run_b = [
        ("b.py", 4, ("apple", "apples"), [], None),  # exact duplicate
        ("c.py", 5, ("apple", "apples", "apples"), [], None),  # 3-form plural
        ("d.py", 6, ("apple", "green apples"), [], None),  # different plural
    ]
    result = merge_extraction_results(run_a, run_b)
    assert result.conflicts == ()
    assert [(e.message, e.context) for e in result.entries] == [
        (("apple", "apples"), None),
        (("apple", "apples"), None),
        (("apple", "apples", "apples"), None),
        (("apple", "green apples"), None),
    ]
    # The duplicate at b.py:4 collapsed into a single source.
    b_entry = result.entries[1]
    assert b_entry.sources == (Source(path="b.py", lineno=4, method="unknown"),)
    # The identical plural message at a.py:3 kept its own source.
    assert result.entries[0].sources == (
        Source(path="a.py", lineno=3, method="unknown"),
    )


def test_singular_and_plural_with_same_singular_form_are_distinct():
    run_a = [("a.py", 3, "apple", [], None)]
    run_b = [("b.py", 4, ("apple", "apples"), [], None)]
    result = merge_extraction_results(run_a, run_b)
    assert result.conflicts == ()
    assert [e.message for e in result.entries] == ["apple", ("apple", "apples")]


def test_windows_path_separators_normalize_to_same_position():
    win_path = WIN_SEP.join(["dir", "a.py"])
    run_a = [(win_path, 5, "Hello", [], None)]
    run_b = [("dir/a.py", 5, "Hello", [], None)]
    result = merge_extraction_results(run_a, run_b)
    assert result.conflicts == ()
    assert len(result.entries) == 1
    assert result.entries[0].sources == (
        Source(path="dir/a.py", lineno=5, method="unknown"),
    )


def test_windows_and_posix_conflict_positions_match():
    win_path = WIN_SEP.join(["dir", "a.py"])
    run_a = [(win_path, 5, "Hello", [], None)]
    run_b = [("dir/a.py", 5, "Goodbye", [], None)]
    result = merge_extraction_results(run_a, run_b, methods=("python", "javascript"))
    assert result.entries == ()
    assert len(result.conflicts) == 1
    assert result.conflicts[0].path == "dir/a.py"


def test_normalize_path_strips_dot_segments():
    assert normalize_path("./a.py") == "a.py"
    assert normalize_path("dir/./a.py") == "dir/a.py"
    win_nested = WIN_SEP.join(["dir", "sub", "a.py"])
    assert normalize_path(win_nested) == "dir/sub/a.py"


def test_duplicate_positions_within_one_listing_dedupe():
    run_a = [
        ("a.py", 5, "Hello", [], None),
        ("a.py", 5, "Hello", [], None),
        ("a.py", 5, "Hello", [], None),
    ]
    result = merge_extraction_results(run_a)
    assert result.conflicts == ()
    assert len(result.entries) == 1
    assert result.entries[0].sources == (
        Source(path="a.py", lineno=5, method="unknown"),
    )


def test_duplicate_position_different_messages_same_method_is_not_conflict():
    # A single extractor reporting two messages at one position is not a
    # cross-extractor conflict; both identities are kept.
    run_a = [
        ("a.py", 5, "Hello", [], None),
        ("a.py", 5, "Goodbye", [], None),
    ]
    result = merge_extraction_results(run_a, methods=("python",))
    assert result.conflicts == ()
    assert [e.message for e in result.entries] == ["Goodbye", "Hello"]
    for entry in result.entries:
        assert entry.sources == (Source(path="a.py", lineno=5, method="python"),)


def test_inputs_are_not_mutated():
    run_a = [
        ("a.py", 5, "Hello", ["note"], None),
        ("b.py", 3, ("apple", "apples"), [], None),
    ]
    run_b = [
        ("a.py", 5, "Hello", ["note"], None),
        {"filename": "c.py", "lineno": 1, "message": "Hi", "context": "",
         "method": "javascript", "comments": ["x"]},
    ]
    snapshot_a = copy.deepcopy(run_a)
    snapshot_b = copy.deepcopy(run_b)
    merge_extraction_results(run_a, run_b, methods=("python", "javascript"))
    assert run_a == snapshot_a
    assert run_b == snapshot_b


def test_output_is_sorted_by_path_lineno_and_identity():
    run_a = [
        ("b.py", 10, "zeta", [], None),
        ("b.py", 2, "beta", [], None),
        ("a.py", 9, "alpha", [], None),
        ("b.py", 2, "alpha", [], None),
    ]
    run_b = [("a.py", 1, "omega", [], None)]
    result = merge_extraction_results(run_a, run_b)
    ordering = [
        (entry.sources[0].path, entry.sources[0].lineno, entry.message)
        for entry in result.entries
    ]
    assert ordering == [
        ("a.py", 1, "omega"),
        ("a.py", 9, "alpha"),
        ("b.py", 2, "alpha"),
        ("b.py", 2, "beta"),
        ("b.py", 10, "zeta"),
    ]


def test_conflicts_sorted_by_position():
    run_a = [("b.py", 2, "one", [], None), ("a.py", 3, "two", [], None)]
    run_b = [("b.py", 2, "uno", [], None), ("a.py", 3, "dos", [], None)]
    result = merge_extraction_results(run_a, run_b, methods=("python", "javascript"))
    assert result.entries == ()
    assert [(c.path, c.lineno) for c in result.conflicts] == [
        ("a.py", 3),
        ("b.py", 2),
    ]


def test_mapping_and_record_inputs():
    run_a = [
        {"filename": "a.py", "lineno": 5, "message": "Hello", "method": "python"},
        ExtractionRecord("b.py", 2, ("apple", "apples"), context="menu",
                         method="python"),
    ]
    run_b = [("a.py", 5, "Hello", [], None)]
    result = merge_extraction_results(run_a, run_b, methods=("python", "python"))
    assert result.conflicts == ()
    assert len(result.entries) == 2
    hello = next(e for e in result.entries if e.message == "Hello")
    assert hello.sources == (Source(path="a.py", lineno=5, method="python"),)


def test_methods_length_mismatch_raises():
    with pytest.raises(ValueError):
        merge_extraction_results([], [], methods=("python",))


def test_unsupported_record_raises():
    with pytest.raises(TypeError):
        merge_extraction_results([("a.py", 5, "Hello")])
