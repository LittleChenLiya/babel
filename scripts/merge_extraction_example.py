"""
Example: merging two Babel extraction result sets into one source list.

This script demonstrates :func:`babel.messages.merge.merge_extraction_results`.
It only consumes already-extracted records; it never reads source files itself.

Run it with::

    python scripts/merge_extraction_example.py
"""

from __future__ import annotations

import os
import sys

# Make the local worktree package importable when run directly from a checkout.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from babel.messages.merge import merge_extraction_results


def main() -> None:
    # Two extraction runs over the same project.  Each record is a 5-tuple of
    # (filename, lineno, message, comments, context), exactly what
    # ``extract_from_dir`` yields.
    python_results = [
        ('src/app.py', 5, 'Hello, world!', ['TRANSLATOR: greeting'], None),
        ('src/app.py', 6, ('One apple', '{count} apples'), [], None),
        ('src/auth.py', 12, 'Sign in', [], 'button'),
    ]
    javascript_results = [
        ('src/app.py', 5, 'Hello, world!', [], None),
        ('src/app.py', 6, ('One apple', '{count} apples'), [], None),
        # The JS extractor sees a different message at src/auth.py:12 --
        # this is reported as a conflict instead of being silently picked.
        ('src/auth.py', 12, 'Log in', [], 'button'),
    ]

    result = merge_extraction_results(
        python_results,
        javascript_results,
        method_a='python',
        method_b='javascript',
    )

    print('=== Merged source list ===')
    for message in result.messages:
        print(f'  msgid:   {message.message!r}')
        print(f'  context: {message.context!r}')
        for location in message.locations:
            print(f'    source: {location.filename}:{location.lineno} (via {location.method})')
        if message.comments:
            print(f'  comments: {message.comments}')
        print()

    print('=== Conflicts ===')
    if not result.conflicts:
        print('  (none)')
    for conflict in result.conflicts:
        print(f'  {conflict.filename}:{conflict.lineno}')
        print(f'    python:     {conflict.record_a.message!r}')
        print(f'    javascript: {conflict.record_b.message!r}')


if __name__ == '__main__':
    main()
