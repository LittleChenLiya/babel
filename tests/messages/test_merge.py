#
# Copyright (C) 2007-2011 Edgewall Software, 2013-2026 the Babel team
# All rights reserved.
#
# This software is licensed as described in the file LICENSE, which
# you should have received as part of this distribution. The terms
# are also available at https://github.com/python-babel/babel/blob/master/LICENSE.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at https://github.com/python-babel/babel/commits/master/.

from __future__ import annotations

from babel.messages.merge import (
    Conflict,
    Location,
    MergedMessage,
    MergeResult,
    merge_extraction_results,
)

BS = chr(92)  # backslash, to avoid escaping issues in the test source


def test_same_message_same_location_keeps_one_record_with_both_sources():
    # Both lists carry the same message at a.py:5: a single merged record is
    # kept, but every source (file line + extraction method) is retained.
    results_a = [('a.py', 5, 'hello', ['A comment'], None)]
    results_b = [('a.py', 5, 'hello', ['B comment'], None)]

    result = merge_extraction_results(results_a, results_b, 'python', 'javascript')

    assert isinstance(result, MergeResult)
    assert len(result.messages) == 1
    assert result.conflicts == []
    message = result.messages[0]
    assert isinstance(message, MergedMessage)
    assert message.message == 'hello'
    assert message.context is None
    assert message.comments == ['A comment', 'B comment']
    methods = {location.method for location in message.locations}
    assert methods == {'python', 'javascript'}
    assert all(
        location.filename == 'a.py' and location.lineno == 5 for location in message.locations
    )


def test_same_msgid_different_context_stays_two_records():
    # The same msgid with a different context must not collapse.
    results_a = [('a.py', 1, 'hello', [], 'ctx_a')]
    results_b = [('a.py', 2, 'hello', [], 'ctx_b')]

    result = merge_extraction_results(results_a, results_b, 'python', 'javascript')

    assert len(result.messages) == 2
    assert result.messages[0].context == 'ctx_a'
    assert result.messages[1].context == 'ctx_b'


def test_same_location_different_msgid_reports_conflict():
    # The same location identified as a different message by the two
    # extractors is reported as a conflict with both full records.
    results_a = [('a.py', 5, 'hello', ['from python'], None)]
    results_b = [('a.py', 5, 'world', ['from javascript'], None)]

    result = merge_extraction_results(results_a, results_b, 'python', 'javascript')

    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert isinstance(conflict, Conflict)
    assert conflict.filename == 'a.py'
    assert conflict.lineno == 5
    assert conflict.record_a.message == 'hello'
    assert conflict.record_a.method == 'python'
    assert conflict.record_b.message == 'world'
    assert conflict.record_b.method == 'javascript'
    # No side is silently dropped: both messages remain in the source list.
    messages = {m.message for m in result.messages}
    assert messages == {'hello', 'world'}


def test_none_context_and_empty_string_context_are_distinct():
    # A missing context (None) and an empty-string context must never merge.
    results_a = [('a.py', 1, 'hello', [], None)]
    results_b = [('a.py', 2, 'hello', [], '')]

    result = merge_extraction_results(results_a, results_b, 'python', 'javascript')

    assert len(result.messages) == 2
    contexts = {message.context for message in result.messages}
    assert contexts == {None, ''}


def test_plural_identity_is_complete():
    # The full plural composition is part of the identity: singular vs.
    # plural, and two plural tuples with different plural forms, are distinct.
    results_a = [('a.py', 1, 'one', [], None)]
    results_b = [('a.py', 2, ('one', 'other'), [], None)]
    result = merge_extraction_results(results_a, results_b, 'python', 'javascript')
    assert len(result.messages) == 2

    results_a = [('a.py', 1, ('one', 'other'), [], None)]
    results_b = [('a.py', 2, ('one', 'others'), [], None)]
    result = merge_extraction_results(results_a, results_b, 'python', 'javascript')
    assert len(result.messages) == 2
    assert result.messages[0].message == ('one', 'other')
    assert result.messages[1].message == ('one', 'others')

    # Same plural tuple from both sides merges into one record.
    results_a = [('a.py', 3, ('one', 'other'), [], None)]
    results_b = [('a.py', 3, ('one', 'other'), [], None)]
    result = merge_extraction_results(results_a, results_b, 'python', 'javascript')
    assert len(result.messages) == 1
    assert result.messages[0].message == ('one', 'other')


def test_windows_separators_are_normalized():
    # Backslash separators in relative paths are normalized to forward
    # slashes so the same file is recognized as one location.
    results_a = [('src' + BS + 'pkg' + BS + 'a.py', 5, 'hello', [], None)]
    results_b = [('src/pkg/a.py', 5, 'hello', [], None)]

    result = merge_extraction_results(results_a, results_b, 'python', 'javascript')

    assert len(result.messages) == 1
    filenames = {location.filename for location in result.messages[0].locations}
    assert filenames == {'src/pkg/a.py'}
    assert all(BS not in location.filename for location in result.messages[0].locations)


def test_duplicate_locations_within_one_side_collapse():
    # The same file and line appearing twice in one result set collapses to a
    # single source.
    results_a = [
        ('a.py', 5, 'hello', [], None),
        ('a.py', 5, 'hello', [], None),
    ]
    results_b = []

    result = merge_extraction_results(results_a, results_b, 'python', 'javascript')

    assert len(result.messages) == 1
    assert len(result.messages[0].locations) == 1
    location = result.messages[0].locations[0]
    assert isinstance(location, Location)
    assert location.filename == 'a.py'
    assert location.lineno == 5
    assert location.method == 'python'


def test_inputs_are_not_mutated():
    # The input records must remain unchanged after merging.
    results_a = [('a.py', 5, 'hello', ['c1'], None), ('a.py', 6, 'world', [], 'ctx')]
    results_b = [('a.py', 5, 'hello', ['c2'], None)]
    snapshot_a = [tuple(record) for record in results_a]
    snapshot_b = [tuple(record) for record in results_b]

    merge_extraction_results(results_a, results_b, 'python', 'javascript')

    assert results_a == snapshot_a
    assert results_b == snapshot_b


def test_comments_are_merged_and_deduplicated():
    # Comments from both sides are merged, deduplicated, in first-seen order.
    results_a = [('a.py', 1, 'hello', ['a', 'b'], None)]
    results_b = [('a.py', 1, 'hello', ['b', 'c'], None)]

    result = merge_extraction_results(results_a, results_b, 'python', 'javascript')

    assert result.messages[0].comments == ['a', 'b', 'c']


def test_output_is_stably_sorted():
    # Output is sorted by normalized path, line and message identity.
    results_a = [
        ('b.py', 2, 'z', [], None),
        ('a.py', 1, 'y', [], None),
        ('a.py', 1, 'x', [], None),
    ]
    results_b = []

    result = merge_extraction_results(results_a, results_b, 'python', 'javascript')

    keys = [
        (location.filename, location.lineno, message.message)
        for message in result.messages
        for location in message.locations
    ]
    assert keys == sorted(keys)
    assert [message.message for message in result.messages] == ['x', 'y', 'z']


def test_empty_inputs():
    result = merge_extraction_results([], [])
    assert result.messages == []
    assert result.conflicts == []


def test_conflicts_are_sorted_by_location():
    results_a = [
        ('z.py', 1, 'a', [], None),
        ('a.py', 1, 'b', [], None),
    ]
    results_b = [
        ('z.py', 1, 'x', [], None),
        ('a.py', 1, 'y', [], None),
    ]

    result = merge_extraction_results(results_a, results_b, 'python', 'javascript')

    assert len(result.conflicts) == 2
    assert [(c.filename, c.lineno) for c in result.conflicts] == [
        ('a.py', 1),
        ('z.py', 1),
    ]
