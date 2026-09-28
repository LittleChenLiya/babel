"""
babel.messages.checkers
~~~~~~~~~~~~~~~~~~~~~~~

Various routines that help with validation of translations.

:since: version 0.9

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from string import Formatter
from typing import cast

from babel.messages.catalog import PYTHON_FORMAT, Catalog, Message, TranslationError

#: list of format chars that are compatible to each other
_string_format_compatibilities = [
    {'i', 'd', 'u'},
    {'x', 'X'},
    {'f', 'F', 'g', 'G'},
]


def _format_chars_compatible(a: str, b: str) -> bool:
    """Return whether two percent-format conversion characters are compatible."""
    if a == b:
        return True
    for compatible_set in _string_format_compatibilities:
        if a in compatible_set and b in compatible_set:
            return True
    return False


def _branch_prefix(message: Message, branch_index: int | None) -> str:
    """Build the prefix identifying the message context and plural branch."""
    parts: list[str] = []
    if message.context is not None:
        parts.append(f"context {message.context!r}")
    if branch_index is not None:
        parts.append(f"plural branch {branch_index}")
    if not parts:
        return ''
    return ' '.join(parts) + ': '


def _message_pairs(message: Message) -> list[tuple[int | None, str, str]]:
    """Return ``(branch_index, msgid, msgstr)`` pairs for the message.

    For pluralizable messages the singular translation is compared with the
    singular msgid and every other branch with the plural msgid, mirroring the
    structure of the `python_format` checker.
    """
    raw = message.string
    if isinstance(raw, str):
        msgstrs: Sequence[str] = (raw,)
    elif isinstance(raw, (list, tuple)):
        msgstrs = raw
    else:
        msgstrs = ('',)
    if not message.pluralizable:
        return [(None, cast(str, message.id), msgstrs[0])]
    msgids = cast(tuple[str, str], message.id)
    pairs: list[tuple[int | None, str, str]] = []
    for index, msgstr in enumerate(msgstrs):
        msgid = msgids[0] if index == 0 else msgids[1]
        pairs.append((index, msgid, msgstr))
    return pairs


def _fail(message: Message, problems: list[tuple[int | None, str]]) -> None:
    """Raise a `TranslationError` aggregating all problems of one checker."""
    if problems:
        details = [
            _branch_prefix(message, branch_index) + problem
            for branch_index, problem in problems
        ]
        raise TranslationError('\n'.join(details))


def num_plurals(catalog: Catalog | None, message: Message) -> None:
    """Verify the number of plurals in the translation."""
    if not message.pluralizable:
        if not isinstance(message.string, str):
            raise TranslationError("Found plural forms for non-pluralizable message")
        return

    # skip further tests if no catalog is provided.
    elif catalog is None:
        return

    msgstrs = message.string
    if not isinstance(msgstrs, (list, tuple)):
        msgstrs = (msgstrs,)
    if len(msgstrs) != catalog.num_plurals:
        raise TranslationError(
            f"Wrong number of plural forms (expected {catalog.num_plurals})",
        )


def python_format(catalog: Catalog | None, message: Message) -> None:
    """Verify the format string placeholders in the translation."""
    if 'python-format' not in message.flags:
        return
    problems: list[tuple[int | None, str]] = []
    for branch_index, msgid, msgstr in _message_pairs(message):
        if msgstr:
            problems.extend(
                (branch_index, problem)
                for problem in _check_percent_string(msgid, msgstr)
            )
    _fail(message, problems)


def _parse_percent_format(string: str) -> tuple[list[tuple[str | None, str]], list[str]]:
    """Parse a percent-style format string.

    Returns a tuple of a list of ``(name, conversion_character)`` entries and
    a list of human-readable problems caused by malformed percent escapes.
    A doubled ``%%`` is an escape sequence and never yields a placeholder.
    """
    entries: list[tuple[str | None, str]] = []
    problems: list[str] = []
    consumed = 0
    for match in PYTHON_FORMAT.finditer(string):
        # anything containing a percent sign between two matches that is not
        # a literal ``%%`` escape is a malformed format sequence
        gap = string[consumed:match.start()]
        while gap:
            percent_index = gap.find('%')
            if percent_index == -1:
                break
            if percent_index + 1 < len(gap) and gap[percent_index + 1] == '%':
                gap = gap[percent_index + 2:]
                continue
            problems.append('malformed percent-format string')
            break
        consumed = match.end()
        name, _flags, typechar = match.groups()
        if typechar == '%' and name is None:
            # literal ``%%`` escape
            continue
        entries.append((name, str(typechar)))
    tail = string[consumed:]
    while tail:
        percent_index = tail.find('%')
        if percent_index == -1:
            break
        if percent_index + 1 < len(tail) and tail[percent_index + 1] == '%':
            tail = tail[percent_index + 2:]
            continue
        problems.append('malformed percent-format string')
        break
    return entries, problems


def _percent_placeholders_mixed(
    entries: list[tuple[str | None, str]],
) -> bool | None:
    """Return whether entries are positional (``True``) or named (``False``).

    Returns ``None`` for empty entries and raises a `TranslationError` when
    positional and named placeholders are mixed.
    """
    positional: bool | None = None
    for name, _typechar in entries:
        is_positional = name is None
        if positional is None:
            positional = is_positional
        elif is_positional != positional:
            raise TranslationError(
                'format string mixes positional and named placeholders',
            )
    return positional


def _check_percent_string(format: str, alternative: str) -> list[str]:
    """Compare percent-style placeholders of `format` and `alternative`.

    Returns a list of problems; an empty list means the strings are
    compatible.
    """
    source_entries, source_problems = _parse_percent_format(format)
    target_entries, target_problems = _parse_percent_format(alternative)
    problems = list(source_problems)
    problems.extend(target_problems)
    if problems:
        return problems

    try:
        source_positional = _percent_placeholders_mixed(source_entries)
        target_positional = _percent_placeholders_mixed(target_entries)
    except TranslationError as error:
        return [str(error)]

    if not source_entries:
        return []

    if source_positional and not target_positional and not target_entries:
        return ['placeholders are incompatible']
    if source_positional != target_positional:
        return ['the format strings are of different kinds']

    if source_positional:
        if len(source_entries) != len(target_entries):
            return ['positional format placeholders are unbalanced']
        problems = []
        for index, ((_name, source_type), (_other, target_type)) in enumerate(
            zip(source_entries, target_entries),
        ):
            if not _format_chars_compatible(source_type, target_type):
                problems.append(
                    f"incompatible format for placeholder {index + 1:d}: "
                    f"{source_type!r} and {target_type!r} are not compatible",
                )
        return problems

    source_map = dict(source_entries)
    target_map = dict(target_entries)
    problems = []
    for name in source_map:
        if name not in target_map:
            problems.append(f'missing named placeholder {name!r}')
    for name in target_map:
        if name not in source_map:
            problems.append(f'extra named placeholder {name!r}')
    for name in source_map.keys() & target_map.keys():
        source_type = source_map[name]
        target_type = target_map[name]
        if not _format_chars_compatible(source_type, target_type):
            problems.append(
                f"incompatible format for placeholder {name!r}: "
                f"{source_type!r} and {target_type!r} are not compatible",
            )
    return problems


def _validate_format(format: str, alternative: str) -> None:
    """Test format string `alternative` against `format`.  `format` can be the
    msgid of a message and `alternative` one of the `msgstr`\\s.  The two
    arguments are not interchangeable as `alternative` may contain less
    placeholders if `format` uses named placeholders.

    If the string formatting of `alternative` is compatible to `format` the
    function returns `None`, otherwise a `TranslationError` is raised.

    Examples for compatible format strings:

    >>> _validate_format('Hello %s!', 'Hallo %s!')
    >>> _validate_format('Hello %i!', 'Hallo %d!')

    Example for an incompatible format strings:

    >>> _validate_format('Hello %(name)s!', 'Hallo %s!')
    Traceback (most recent call last):
      ...
    TranslationError: the format strings are of different kinds

    This function is used by the `python_format` checker.

    :param format: The original format string
    :param alternative: The alternative format string that should be checked
                        against format
    :raises TranslationError: on formatting errors
    """

    def _parse(string: str) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for match in PYTHON_FORMAT.finditer(string):
            name, format, typechar = match.groups()
            if typechar == '%' and name is None:
                continue
            result.append((name, str(typechar)))
        return result

    def _check_positional(results: list[tuple[str, str]]) -> bool:
        positional = None
        for name, _char in results:
            if positional is None:
                positional = name is None
            else:
                if (name is None) != positional:
                    raise TranslationError(
                        'format string mixes positional and named placeholders',
                    )
        return bool(positional)

    a = _parse(format)
    b = _parse(alternative)

    if not a:
        return

    # now check if both strings are positional or named
    a_positional = _check_positional(a)
    b_positional = _check_positional(b)
    if a_positional and not b_positional and not b:
        raise TranslationError('placeholders are incompatible')
    elif a_positional != b_positional:
        raise TranslationError('the format strings are of different kinds')

    # if we are operating on positional strings both must have the
    # same number of format chars and those must be compatible
    if a_positional:
        if len(a) != len(b):
            raise TranslationError('positional format placeholders are unbalanced')
        for idx, ((_, first), (_, second)) in enumerate(zip(a, b)):
            if not _format_chars_compatible(first, second):
                raise TranslationError(
                    f'incompatible format for placeholder {idx + 1:d}: '
                    f'{first!r} and {second!r} are not compatible',
                )

    # otherwise the second string must not have names the first one
    # doesn't have and the types of those included must be compatible
    else:
        type_map = dict(a)
        for name, typechar in b:
            if name not in type_map:
                raise TranslationError(f'unknown named placeholder {name!r}')
            elif not _format_chars_compatible(typechar, type_map[name]):
                raise TranslationError(
                    f'incompatible format for placeholder {name!r}: '
                    f'{typechar!r} and {type_map[name]!r} are not compatible',
                )


class _BracePlaceholder:
    """One field reference in a ``str.format``-style format string."""

    __slots__ = ('name', 'positional', 'conversion')

    def __init__(self, name: str | int, conversion: str) -> None:
        self.positional = isinstance(name, int)
        self.name = name
        self.conversion = conversion


def _brace_field_key(field_name: str) -> tuple[bool, str | int]:
    """Return the identity of a field.

    Attribute and item access (``foo.bar``/``foo[0]``) is resolved against
    the same parameter as ``foo``, so only the leading component counts.
    """
    if field_name == '':
        return True, 0
    end = 0
    while end < len(field_name) and field_name[end] not in '.[':
        end += 1
    head = field_name[:end]
    if head.isdecimal():
        return True, int(head)
    return False, head


def _parse_brace_format(
    string: str,
) -> tuple[list[_BracePlaceholder], bool, list[str]]:
    """Parse a ``str.format``-style format string.

    Returns the entries, whether automatic field numbering is used and a list
    of problems.  Fields nested in format specs (e.g. the ``width`` in
    ``"{value:{width}.2f}"``) are collected as well, while doubled braces
    (``{{``/``}}``) are escapes and never yield placeholders.
    """
    entries: list[_BracePlaceholder] = []
    problems: list[str] = []
    automatic = False
    automatic_index = 0
    explicit_indices: set[int] = set()

    formatter = Formatter()

    def add_field(field_name: str, conversion: str | None) -> None:
        nonlocal automatic, automatic_index
        positional, key = _brace_field_key(field_name)
        if positional and field_name == '':
            automatic = True
            key = automatic_index
            automatic_index += 1
        elif positional:
            explicit_indices.add(int(key))
        entries.append(
            _BracePlaceholder(key, conversion if conversion is not None else 's'),
        )

    def collect(literal_text: str, field_name: str | None,
                format_spec, conversion: str | None) -> None:
        if field_name is None:
            return
        add_field(field_name, conversion)
        if format_spec:
            for inner in formatter.parse(format_spec):
                collect(*inner)

    try:
        for parts in formatter.parse(string):
            collect(*parts)
    except (ValueError, IndexError) as error:
        problems.append(f'malformed brace-format string: {error}')
        return entries, automatic, problems

    if automatic and explicit_indices:
        problems.append(
            'cannot switch from automatic field numbering to manual field specification',
        )
    return entries, automatic, problems


def _check_brace_string(format: str, alternative: str) -> list[str]:
    """Compare brace-format placeholders of `format` and `alternative`."""
    source_entries, _source_auto, source_problems = _parse_brace_format(format)
    target_entries, _target_auto, target_problems = _parse_brace_format(alternative)
    problems = list(source_problems)
    problems.extend(target_problems)
    if problems:
        return problems
    if not source_entries:
        return []

    def group(entries: list[_BracePlaceholder]) -> tuple[
        dict[str, set[str]],
        dict[int, set[str]],
    ]:
        named: dict[str, set[str]] = {}
        positional: dict[int, set[str]] = {}
        for entry in entries:
            if entry.positional:
                assert isinstance(entry.name, int)
                positional.setdefault(entry.name, set()).add(entry.conversion)
            else:
                assert isinstance(entry.name, str)
                named.setdefault(entry.name, set()).add(entry.conversion)
        return named, positional

    source_named, source_positional = group(source_entries)
    target_named, target_positional = group(target_entries)

    for name in source_named:
        if name not in target_named:
            problems.append(f'missing named placeholder {name!r}')
    for name in target_named:
        if name not in source_named:
            problems.append(f'extra named placeholder {name!r}')
    for name in source_named.keys() & target_named.keys():
        if source_named[name] != target_named[name]:
            problems.append(
                f"incompatible conversion for placeholder {name!r}: "
                f"{sorted(source_named[name])!r} and {sorted(target_named[name])!r} "
                'are not compatible',
            )

    for index in source_positional:
        if index not in target_positional:
            problems.append(f'missing positional placeholder {index + 1:d}')
    for index in target_positional:
        if index not in source_positional:
            problems.append(f'extra positional placeholder {index + 1:d}')
    for index in source_positional.keys() & target_positional.keys():
        if source_positional[index] != target_positional[index]:
            problems.append(
                f"incompatible conversion for placeholder {index + 1:d}: "
                f"{sorted(source_positional[index])!r} and "
                f"{sorted(target_positional[index])!r} are not compatible",
            )
    return problems


def python_brace_format(catalog: Catalog | None, message: Message) -> None:
    """Verify ``str.format``-style placeholders in the translation."""
    if 'python-brace-format' not in message.flags:
        return
    problems: list[tuple[int | None, str]] = []
    for branch_index, msgid, msgstr in _message_pairs(message):
        if msgstr:
            problems.extend(
                (branch_index, problem)
                for problem in _check_brace_string(msgid, msgstr)
            )
    _fail(message, problems)


def _find_checkers() -> list[Callable[[Catalog | None, Message], object]]:
    from babel.messages._compat import find_entrypoints

    checkers: list[Callable[[Catalog | None, Message], object]] = []
    checkers.extend(load() for (name, load) in find_entrypoints('babel.checkers'))
    if len(checkers) == 0:
        # if entrypoints are not available or no usable egg-info was found
        # (see #230), just resort to hard-coded checkers
        return [num_plurals, python_format, python_brace_format]
    return checkers


checkers: list[Callable[[Catalog | None, Message], object]] = _find_checkers()
