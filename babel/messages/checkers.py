"""
babel.messages.checkers
~~~~~~~~~~~~~~~~~~~~~~~

Various routines that help with validation of translations.

:since: version 0.9

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from string import Formatter
from typing import cast

from babel.messages.catalog import PYTHON_FORMAT, Catalog, Message, TranslationError

#: list of format chars that are compatible to each other
_string_format_compatibilities = [
    {'i', 'd', 'u'},
    {'x', 'X'},
    {'f', 'F', 'g', 'G'},
]

_BRACE_FORMATTER = Formatter()


class PlaceholderError(TranslationError):
    """A mismatch between the placeholders of a message id and a translation.

    Besides the error message, structured information about the offending
    message context and plural branch is available as attributes.
    """

    def __init__(
        self,
        message: str,
        *,
        context: str | None = None,
        branch_index: int | None = None,
        kind: str | None = None,
        placeholders: Iterable[str] = (),
    ) -> None:
        super().__init__(message)
        self.context = context
        self.branch_index = branch_index
        self.kind = kind
        self.placeholders = tuple(placeholders)


@dataclass(frozen=True)
class _PlaceholderContract:
    """The placeholders of a single format string.

    Named placeholders map their name to the conversions used per occurrence
    (named placeholders may occur more than once); positional placeholders are
    kept in order for percent-style strings and keyed by index for brace
    strings.
    """

    named: dict[str, tuple[str, ...]]
    positional: tuple[tuple[str, str], ...]


def _compatible_conversion(a: str, b: str) -> bool:
    if a == b:
        return True
    for set in _string_format_compatibilities:
        if a in set and b in set:
            return True
    return False


def _error_prefix(context: str | None, branch_index: int | None) -> str:
    parts = []
    if context is not None:
        parts.append(f'message context {context!r}')
    if branch_index is not None:
        parts.append(f'plural form {branch_index}')
    if parts:
        return ' '.join(parts) + ': '
    return ''


def _parse_percent_contract(string: str) -> _PlaceholderContract:
    """Extract the percent-style placeholder contract of `string`.

    Literal `%%` escapes are not considered placeholders.  Strings mixing
    positional and named placeholders or containing stray percent characters
    are rejected with a `PlaceholderError`.
    """
    named: dict[str, list[str]] = {}
    positional: list[str] = []
    saw_named = saw_positional = False
    for match in PYTHON_FORMAT.finditer(string):
        name, _spec, typechar = match.groups()
        if typechar == '%' and name is None:
            # A literal `%%` escape, not a placeholder.
            continue
        if name is None:
            saw_positional = True
            positional.append(typechar)
        else:
            saw_named = True
            named.setdefault(name, []).append(typechar)
    if saw_named and saw_positional:
        raise PlaceholderError(
            'python-format string mixes positional and named placeholders',
            kind='mixed_placeholders',
        )
    # Everything matching the format regex (including `%%`) is removed; a
    # remaining percent means the format string is malformed.
    if '%' in PYTHON_FORMAT.sub('', string):
        raise PlaceholderError(
            'invalid python-format string',
            kind='invalid_format',
        )
    return _PlaceholderContract(
        named={name: tuple(conversions) for name, conversions in named.items()},
        positional=tuple(
            (str(index), conversion) for index, conversion in enumerate(positional)
        ),
    )


def _parse_brace_contract(string: str) -> _PlaceholderContract:
    """Extract the str.format brace placeholder contract of `string`.

    Placeholders nested inside format specs (such as the `width` field in
    `{value:{width}.2f}`) are included, and literal double-brace escapes are
    not considered placeholders.  Strings mixing automatic and manual field
    numbering or containing stray braces are rejected.
    """
    named: dict[str, list[str]] = {}
    positional: list[tuple[str, str]] = []
    numbering: str | None = None
    auto_index = 0

    def walk(part: str) -> None:
        nonlocal numbering, auto_index
        for _literal, field_name, format_spec, conversion in _BRACE_FORMATTER.parse(part):
            if field_name is None:
                continue
            first = field_name.split('.', 1)[0].split('[', 1)[0]
            if first == '':
                if numbering == 'manual':
                    raise PlaceholderError(
                        'python-brace-format string mixes automatic and '
                        'manual field numbering',
                        kind='mixed_placeholders',
                    )
                numbering = 'auto'
                index = auto_index
                auto_index += 1
                positional.append((str(index), conversion or ''))
            elif first.isdigit():
                if numbering == 'auto':
                    raise PlaceholderError(
                        'python-brace-format string mixes automatic and '
                        'manual field numbering',
                        kind='mixed_placeholders',
                    )
                numbering = 'manual'
                positional.append((first, conversion or ''))
            else:
                named.setdefault(field_name, []).append(conversion or '')
            if format_spec:
                walk(format_spec)

    try:
        walk(string)
    except ValueError as e:
        raise PlaceholderError(
            f'invalid python-brace-format string: {e}',
            kind='invalid_format',
        ) from e
    return _PlaceholderContract(
        named={name: tuple(conversions) for name, conversions in named.items()},
        positional=tuple(positional),
    )


def _named_contract_errors(
    expected: dict[str, tuple[str, ...]],
    found: dict[str, tuple[str, ...]],
    *,
    style: str,
    compatible: Callable[[str, str], bool],
    context: str | None,
    branch_index: int | None,
    positional: bool = False,
) -> list[PlaceholderError]:
    errors: list[PlaceholderError] = []
    prefix = _error_prefix(context, branch_index)
    expected_keys = set(expected)
    found_keys = set(found)
    missing = sorted(expected_keys - found_keys)
    extra = sorted(found_keys - expected_keys)
    if missing:
        errors.append(
            PlaceholderError(
                f'{prefix}missing {style} placeholders in translation: '
                + ', '.join(repr(key) for key in missing),
                context=context,
                branch_index=branch_index,
                kind='missing',
                placeholders=missing,
            ),
        )
    if extra:
        errors.append(
            PlaceholderError(
                f'{prefix}unexpected {style} placeholders in translation: '
                + ', '.join(repr(key) for key in extra),
                context=context,
                branch_index=branch_index,
                kind='extra',
                placeholders=extra,
            ),
        )
    incompatible: list[str] = []
    for key in sorted(expected_keys & found_keys):
        expected_conversions = dict.fromkeys(expected[key])
        found_conversions = set(found[key])
        for wanted in expected_conversions:
            if not any(compatible(wanted, c) for c in found_conversions):
                if positional:
                    label = f'positional placeholder {key}'
                else:
                    label = f'placeholder {key!r}'
                incompatible.append(
                    f'{label}: expected {wanted!r}, found '
                    + ', '.join(repr(c) for c in sorted(found_conversions)),
                )
                break
        else:
            for found_conversion in sorted(found_conversions):
                if not any(compatible(found_conversion, c) for c in expected_conversions):
                    if positional:
                        label = f'positional placeholder {key}'
                    else:
                        label = f'placeholder {key!r}'
                    incompatible.append(
                        f'{label}: expected '
                        + ', '.join(repr(c) for c in expected_conversions)
                        + f', found {found_conversion!r}',
                    )
    if incompatible:
        errors.append(
            PlaceholderError(
                f'{prefix}incompatible {style} conversion for ' + '; '.join(incompatible),
                context=context,
                branch_index=branch_index,
                kind='incompatible_conversion',
                placeholders=incompatible,
            ),
        )
    return errors


def _percent_contract_errors(
    source: str,
    translation: str,
    *,
    context: str | None,
    branch_index: int | None,
) -> list[PlaceholderError]:
    try:
        expected_contract = _parse_percent_contract(source)
        found_contract = _parse_percent_contract(translation)
    except PlaceholderError as error:
        raise PlaceholderError(
            _error_prefix(context, branch_index) + str(error),
            context=context,
            branch_index=branch_index,
            kind=error.kind,
        ) from error

    expected_positional: tuple[tuple[str, str], ...] = expected_contract.positional
    found_positional: tuple[tuple[str, str], ...] = found_contract.positional

    errors: list[PlaceholderError] = []
    prefix = _error_prefix(context, branch_index)
    expected_conversions = tuple(conversion for _, conversion in expected_positional)
    found_conversions = tuple(conversion for _, conversion in found_positional)
    if len(expected_conversions) != len(found_conversions):
        kind = 'missing' if len(expected_conversions) > len(found_conversions) else 'extra'
        errors.append(
            PlaceholderError(
                f'{prefix}python-format positional placeholders are unbalanced: '
                f'expected {len(expected_conversions)}, found {len(found_conversions)}',
                context=context,
                branch_index=branch_index,
                kind=kind,
                placeholders=(
                    expected_conversions if kind == 'missing' else found_conversions
                ),
            ),
        )
    incompatible: list[str] = []
    for index, (wanted, found_conversion) in enumerate(
        zip(expected_conversions, found_conversions),
    ):
        if not _compatible_conversion(wanted, found_conversion):
            incompatible.append(
                f'positional placeholder {index + 1}: '
                f'expected {wanted!r}, found {found_conversion!r}',
            )
    if incompatible:
        errors.append(
            PlaceholderError(
                f'{prefix}incompatible python-format conversion for '
                + '; '.join(incompatible),
                context=context,
                branch_index=branch_index,
                kind='incompatible_conversion',
                placeholders=incompatible,
            ),
        )
    errors.extend(
        _named_contract_errors(
            expected_contract.named,
            found_contract.named,
            style='python-format',
            compatible=_compatible_conversion,
            context=context,
            branch_index=branch_index,
        ),
    )
    return errors


def _brace_contract_errors(
    source: str,
    translation: str,
    *,
    context: str | None,
    branch_index: int | None,
) -> list[PlaceholderError]:
    try:
        expected_contract = _parse_brace_contract(source)
        found_contract = _parse_brace_contract(translation)
    except PlaceholderError as error:
        raise PlaceholderError(
            _error_prefix(context, branch_index) + str(error),
            context=context,
            branch_index=branch_index,
            kind=error.kind,
        ) from error

    expected_positional: tuple[tuple[str, str], ...] = expected_contract.positional
    found_positional: tuple[tuple[str, str], ...] = found_contract.positional
    errors: list[PlaceholderError] = []
    prefix = _error_prefix(context, branch_index)
    expected_counter = Counter(key for key, _ in expected_positional)
    found_counter = Counter(key for key, _ in found_positional)

    def _field_sort_key(key: str) -> tuple[int, int | str]:
        return (0, int(key)) if key.isdigit() else (1, key)

    missing_keys: list[str] = []
    for key in sorted(expected_counter, key=_field_sort_key):
        missing_keys.extend([key] * max(0, expected_counter[key] - found_counter.get(key, 0)))
    extra_keys = []
    for key, count in found_counter.items():
        extra_keys.extend([key] * (count - expected_counter.get(key, 0)))
    extra_keys.sort(key=_field_sort_key)
    if missing_keys:
        errors.append(
            PlaceholderError(
                f'{prefix}missing python-brace-format placeholders in translation: '
                + ', '.join(repr(key) for key in missing_keys),
                context=context,
                branch_index=branch_index,
                kind='missing',
                placeholders=missing_keys,
            ),
        )
    if extra_keys:
        errors.append(
            PlaceholderError(
                f'{prefix}unexpected python-brace-format placeholders in translation: '
                + ', '.join(repr(key) for key in extra_keys),
                context=context,
                branch_index=branch_index,
                kind='extra',
                placeholders=extra_keys,
            ),
        )
    remaining = list(found_positional)
    incompatible: list[str] = []
    for key, wanted in expected_positional:
        for remaining_index, (found_key, found_conversion) in enumerate(remaining):
            if found_key == key and wanted == found_conversion:
                del remaining[remaining_index]
                break
        else:
            incompatible.append(
                f'positional placeholder {key}: expected {wanted!r}',
            )
    if incompatible:
        errors.append(
            PlaceholderError(
                f'{prefix}incompatible python-brace-format conversion for '
                + '; '.join(dict.fromkeys(incompatible)),
                context=context,
                branch_index=branch_index,
                kind='incompatible_conversion',
                placeholders=incompatible,
            ),
        )
    errors.extend(
        _named_contract_errors(
            expected_contract.named,
            found_contract.named,
            style='python-brace-format',
            compatible=lambda a, b: a == b,
            context=context,
            branch_index=branch_index,
        ),
    )
    return errors


def _iter_branches(message: Message) -> Iterable[tuple[int, str, str]]:
    """Yield (branch_index, source_id, translation) triples.

    For pluralizable messages, branch 0 is checked against the singular id
    and all further branches against the plural id; empty translations are
    skipped.
    """
    if not message.pluralizable:
        translation = message.string
        if isinstance(translation, (list, tuple)):
            translation = translation[0]
        translation = cast(str, translation)
        if translation:
            yield 0, cast(str, message.id), translation
        return

    msgstrs = message.string
    if not isinstance(msgstrs, (list, tuple)):
        msgstrs = cast(tuple[str, ...], (msgstrs,))
    else:
        msgstrs = cast(tuple[str, ...] | list[str], msgstrs)
    ids = cast(tuple[str, str] | list[str], message.id)
    for index, msgstr in enumerate(msgstrs):
        if not msgstr:
            continue
        source = ids[0] if index == 0 else ids[1]
        yield index, source, msgstr


def _placeholder_errors(
    message: Message,
    flag: str,
    contract_errors: Callable[..., list[PlaceholderError]],
) -> list[PlaceholderError]:
    if flag not in message.flags:
        return []
    errors: list[PlaceholderError] = []
    for branch_index, source, translation in _iter_branches(message):
        try:
            errors.extend(
                contract_errors(
                    source,
                    translation,
                    context=message.context,
                    branch_index=branch_index if message.pluralizable else None,
                ),
            )
        except PlaceholderError as error:
            errors.append(error)
    return errors


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


def python_format(catalog: Catalog | None, message: Message) -> list[PlaceholderError]:
    """Verify the percent-style format placeholder contract of a message.

    Every plural branch is compared against the matching msgid.  Missing or
    unexpected placeholders and incompatible conversion characters are
    reported separately, carrying the message context and plural branch index.
    """
    return _placeholder_errors(message, 'python-format', _percent_contract_errors)


def python_brace_format(
    catalog: Catalog | None,
    message: Message,
) -> list[PlaceholderError]:
    """Verify the str.format brace placeholder contract of a message.

    Named and positional fields, conversions and fields nested inside format
    specs are compared with every plural branch.  Named placeholders may be
    reordered, while escaping through double braces is ignored.
    """
    return _placeholder_errors(message, 'python-brace-format', _brace_contract_errors)


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

    def _compatible(a: str, b: str) -> bool:
        if a == b:
            return True
        for set in _string_format_compatibilities:
            if a in set and b in set:
                return True
        return False

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
            if not _compatible(first, second):
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
            elif not _compatible(typechar, type_map[name]):
                raise TranslationError(
                    f'incompatible format for placeholder {name!r}: '
                    f'{typechar!r} and {type_map[name]!r} are not compatible',
                )


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
