"""
babel.messages.catalog
~~~~~~~~~~~~~~~~~~~~~~

Data structures for message catalogs.

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

import datetime
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from copy import copy, deepcopy
from difflib import SequenceMatcher
from email import message_from_string
from heapq import nlargest
from string import Formatter
from typing import TYPE_CHECKING, NamedTuple, TypedDict

from babel import __version__ as VERSION
from babel.core import Locale, UnknownLocaleError
from babel.dates import format_datetime
from babel.messages.plurals import get_plural
from babel.util import LOCALTZ, _cmp

if TYPE_CHECKING:
    from typing_extensions import TypeAlias

    _MessageID: TypeAlias = str | tuple[str, ...] | list[str]

__all__ = [
    'DEFAULT_HEADER',
    'PYTHON_FORMAT',
    'Catalog',
    'CatalogMergeResult',
    'MergeConflict',
    'Message',
    'TranslationError',
]


def get_close_matches(word, possibilities, n=3, cutoff=0.6):
    """A modified version of ``difflib.get_close_matches``.

    It just passes ``autojunk=False`` to the ``SequenceMatcher``, to work
    around https://github.com/python/cpython/issues/90825.
    """
    if not n > 0:  # pragma: no cover
        raise ValueError(f"n must be > 0: {n!r}")
    if not 0.0 <= cutoff <= 1.0:  # pragma: no cover
        raise ValueError(f"cutoff must be in [0.0, 1.0]: {cutoff!r}")
    result = []
    s = SequenceMatcher(autojunk=False)  # only line changed from difflib.py
    s.set_seq2(word)
    for x in possibilities:
        s.set_seq1(x)
        if (
            s.real_quick_ratio() >= cutoff
            and s.quick_ratio() >= cutoff
            and s.ratio() >= cutoff
        ):
            result.append((s.ratio(), x))

    # Move the best scorers to head of list
    result = nlargest(n, result)
    # Strip scores for the best n matches
    return [x for score, x in result]


PYTHON_FORMAT = re.compile(
    r'''
    \%
        (?:\(([\w]*)\))?
        (
            [-#0\ +]?(?:\*|[\d]+)?
            (?:\.(?:\*|[\d]+))?
            [hlL]?
        )
        ([diouxXeEfFgGcrs%])
''',
    re.VERBOSE,
)


def _has_python_brace_format(string: str) -> bool:
    if "{" not in string:
        return False
    fmt = Formatter()
    try:
        # `fmt.parse` returns 3-or-4-tuples of the form
        # `(literal_text, field_name, format_spec, conversion)`;
        # if `field_name` is set, this smells like brace format
        field_name_seen = False
        for t in fmt.parse(string):
            if t[1] is not None:
                field_name_seen = True
                # We cannot break here, as we need to consume the whole string
                # to ensure that it is a valid format string.
    except ValueError:
        return False
    return field_name_seen


def _parse_datetime_header(value: str) -> datetime.datetime:
    match = re.match(r'^(?P<datetime>.*?)(?P<tzoffset>[+-]\d{4})?$', value)

    dt = datetime.datetime.strptime(match.group('datetime'), '%Y-%m-%d %H:%M')

    # Separate the offset into a sign component, hours, and # minutes
    tzoffset = match.group('tzoffset')
    if tzoffset is not None:
        plus_minus_s, rest = tzoffset[0], tzoffset[1:]
        hours_offset_s, mins_offset_s = rest[:2], rest[2:]

        # Make them all integers
        plus_minus = int(f"{plus_minus_s}1")
        hours_offset = int(hours_offset_s)
        mins_offset = int(mins_offset_s)

        # Calculate net offset
        net_mins_offset = hours_offset * 60
        net_mins_offset += mins_offset
        net_mins_offset *= plus_minus

        # Create an offset object
        tzoffset = datetime.timezone(
            offset=datetime.timedelta(minutes=net_mins_offset),
            name=f'Etc/GMT{net_mins_offset:+d}',
        )

        # Store the offset in a datetime object
        dt = dt.replace(tzinfo=tzoffset)

    return dt


class Message:
    """Representation of a single message in a catalog."""

    def __init__(
        self,
        id: _MessageID,
        string: _MessageID | None = '',
        locations: Iterable[tuple[str, int]] = (),
        flags: Iterable[str] = (),
        auto_comments: Iterable[str] = (),
        user_comments: Iterable[str] = (),
        previous_id: _MessageID = (),
        lineno: int | None = None,
        context: str | None = None,
    ) -> None:
        """Create the message object.

        :param id: the message ID, or a ``(singular, plural)`` tuple for
                   pluralizable messages
        :param string: the translated message string, or a
                       ``(singular, plural)`` tuple for pluralizable messages
        :param locations: a sequence of ``(filename, lineno)`` tuples
        :param flags: a set or sequence of flags
        :param auto_comments: a sequence of automatic comments for the message
        :param user_comments: a sequence of user comments for the message
        :param previous_id: the previous message ID, or a ``(singular, plural)``
                            tuple for pluralizable messages
        :param lineno: the line number on which the msgid line was found in the
                       PO file, if any
        :param context: the message context
        """
        self.id = id
        if not string and self.pluralizable:
            string = ('', '')
        self.string = string
        self.locations = list(dict.fromkeys(locations)) if locations else []
        self.flags = set(flags)
        if id and self.python_format:
            self.flags.add('python-format')
        else:
            self.flags.discard('python-format')
        if id and self.python_brace_format:
            self.flags.add('python-brace-format')
        else:
            self.flags.discard('python-brace-format')
        self.auto_comments = list(dict.fromkeys(auto_comments)) if auto_comments else []
        self.user_comments = list(dict.fromkeys(user_comments)) if user_comments else []
        if previous_id:
            if isinstance(previous_id, str):
                self.previous_id = [previous_id]
            else:
                self.previous_id = list(previous_id)
        else:
            self.previous_id = []
        self.lineno = lineno
        self.context = context

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.id!r} (flags: {list(self.flags)!r})>"

    def __cmp__(self, other: object) -> int:
        """Compare Messages, taking into account plural ids"""

        def values_to_compare(obj):
            if isinstance(obj, Message) and obj.pluralizable:
                return obj.id[0], obj.context or ''
            return obj.id, obj.context or ''

        return _cmp(values_to_compare(self), values_to_compare(other))

    def __gt__(self, other: object) -> bool:
        return self.__cmp__(other) > 0

    def __lt__(self, other: object) -> bool:
        return self.__cmp__(other) < 0

    def __ge__(self, other: object) -> bool:
        return self.__cmp__(other) >= 0

    def __le__(self, other: object) -> bool:
        return self.__cmp__(other) <= 0

    def __eq__(self, other: object) -> bool:
        return self.__cmp__(other) == 0

    def __ne__(self, other: object) -> bool:
        return self.__cmp__(other) != 0

    def is_identical(self, other: Message) -> bool:
        """Checks whether messages are identical, taking into account all
        properties.
        """
        assert isinstance(other, Message)
        return self.__dict__ == other.__dict__

    def clone(self) -> Message:
        return Message(
            id=copy(self.id),
            string=copy(self.string),
            locations=copy(self.locations),
            flags=copy(self.flags),
            auto_comments=copy(self.auto_comments),
            user_comments=copy(self.user_comments),
            previous_id=copy(self.previous_id),
            lineno=self.lineno,  # immutable (str/None)
            context=self.context,  # immutable (str/None)
        )

    def check(self, catalog: Catalog | None = None) -> list[TranslationError]:
        """Run various validation checks on the message.  Some validations
        are only performed if the catalog is provided.  This method returns
        a sequence of `TranslationError` objects.

        :rtype: ``iterator``
        :param catalog: A catalog instance that is passed to the checkers
        :see: `Catalog.check` for a way to perform checks for all messages
              in a catalog.
        """
        from babel.messages.checkers import checkers

        errors: list[TranslationError] = []
        for checker in checkers:
            try:
                checker(catalog, self)
            except TranslationError as e:
                errors.append(e)
        return errors

    @property
    def fuzzy(self) -> bool:
        """Whether the translation is fuzzy.

        >>> Message('foo').fuzzy
        False
        >>> msg = Message('foo', 'foo', flags=['fuzzy'])
        >>> msg.fuzzy
        True
        >>> msg
        <Message 'foo' (flags: ['fuzzy'])>
        """
        return 'fuzzy' in self.flags

    @property
    def pluralizable(self) -> bool:
        """Whether the message is plurizable.

        >>> Message('foo').pluralizable
        False
        >>> Message(('foo', 'bar')).pluralizable
        True
        """
        return isinstance(self.id, (list, tuple))

    @property
    def python_format(self) -> bool:
        """Whether the message contains Python-style parameters.

        >>> Message('foo %(name)s bar').python_format
        True
        >>> Message(('foo %(name)s', 'foo %(name)s')).python_format
        True
        """
        ids = self.id
        if isinstance(ids, (list, tuple)):
            for id in ids:  # Explicit loop for performance reasons.
                if PYTHON_FORMAT.search(id):
                    return True
            return False
        return bool(PYTHON_FORMAT.search(ids))

    @property
    def python_brace_format(self) -> bool:
        """Whether the message contains Python f-string parameters.

        >>> Message('Hello, {name}!').python_brace_format
        True
        >>> Message(('One apple', '{count} apples')).python_brace_format
        True
        """
        ids = self.id
        if isinstance(ids, (list, tuple)):
            for id in ids:  # Explicit loop for performance reasons.
                if _has_python_brace_format(id):
                    return True
            return False
        return _has_python_brace_format(ids)


class TranslationError(Exception):
    """Exception thrown by translation checkers when invalid message
    translations are encountered."""


DEFAULT_HEADER = """\
# Translations template for PROJECT.
# Copyright (C) YEAR ORGANIZATION
# This file is distributed under the same license as the PROJECT project.
# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.
#"""


def parse_separated_header(value: str) -> dict[str, str]:
    # Adapted from https://peps.python.org/pep-0594/#cgi
    from email.message import Message

    m = Message()
    m['content-type'] = value
    return dict(m.get_params())


def _force_text(s: str | bytes, encoding: str = 'utf-8', errors: str = 'strict') -> str:
    if isinstance(s, str):
        return s
    if isinstance(s, bytes):
        return s.decode(encoding, errors)
    return str(s)


class ConflictInfo(TypedDict):
    message: Message
    filename: str
    project: str
    version: str


class MergeConflict(TypedDict, total=False):
    """Structured description of a conflict found by `merge_catalogs`.

    Catalog-level conflicts (``level`` is ``"catalog"``) use the ``field``,
    ``base``, ``local`` and ``incoming`` keys to describe the differing
    property (``"locale"`` or ``"plural_forms"``).

    Message-level conflicts (``level`` is ``"message"``) always carry the
    ``context`` and ``msgid`` keys, plus ``field`` (``"translation"``,
    ``"auto_comments"``, ``"presence"``) and, for plural translations,
    ``plural_index``.  The ``base``/``local``/``incoming`` values are plain
    JSON-serialisable data; a missing entry is represented by ``None``.
    """

    level: str
    field: str
    context: str | None
    msgid: str | tuple[str, ...]
    plural_index: int
    kind: str
    base: object
    local: object
    incoming: object


class CatalogMergeResult(NamedTuple):
    """Result of `merge_catalogs`: the merged catalog and its conflict list.

    The conflict list is stable (sorted by catalog then message identity) and
    contains only JSON-serialisable values.
    """

    catalog: Catalog
    conflicts: list[MergeConflict]


class Catalog:
    """Representation of a message catalog."""

    def __init__(
        self,
        locale: Locale | str | None = None,
        domain: str | None = None,
        header_comment: str | None = DEFAULT_HEADER,
        project: str | None = None,
        version: str | None = None,
        copyright_holder: str | None = None,
        msgid_bugs_address: str | None = None,
        creation_date: datetime.datetime | str | None = None,
        revision_date: datetime.datetime | datetime.time | float | str | None = None,
        last_translator: str | None = None,
        language_team: str | None = None,
        charset: str | None = None,
        fuzzy: bool = True,
    ) -> None:
        """Initialize the catalog object.

        :param locale: the locale identifier or `Locale` object, or `None`
                       if the catalog is not bound to a locale (which basically
                       means it's a template)
        :param domain: the message domain
        :param header_comment: the header comment as string, or `None` for the
                               default header
        :param project: the project's name
        :param version: the project's version
        :param copyright_holder: the copyright holder of the catalog
        :param msgid_bugs_address: the email address or URL to submit bug
                                   reports to
        :param creation_date: the date the catalog was created
        :param revision_date: the date the catalog was revised
        :param last_translator: the name and email of the last translator
        :param language_team: the name and email of the language team
        :param charset: the encoding to use in the output (defaults to utf-8)
        :param fuzzy: the fuzzy bit on the catalog header
        """
        self.domain = domain
        self.locale = locale
        self._header_comment = header_comment
        self._messages: dict[str | tuple[str, str], Message] = {}
        self._conflicts: dict[str | tuple[str, str], list[ConflictInfo]] = defaultdict(list)

        self.project = project or 'PROJECT'
        self.version = version or 'VERSION'
        self.copyright_holder = copyright_holder or 'ORGANIZATION'
        self.msgid_bugs_address = msgid_bugs_address or 'EMAIL@ADDRESS'

        self.last_translator = last_translator or 'FULL NAME <EMAIL@ADDRESS>'
        """Name and email address of the last translator."""
        self.language_team = language_team or 'LANGUAGE <LL@li.org>'
        """Name and email address of the language team."""

        self.charset = charset or 'utf-8'

        if creation_date is None:
            creation_date = datetime.datetime.now(LOCALTZ)
        elif isinstance(creation_date, datetime.datetime) and not creation_date.tzinfo:
            creation_date = creation_date.replace(tzinfo=LOCALTZ)
        self.creation_date = creation_date
        if revision_date is None:
            revision_date = 'YEAR-MO-DA HO:MI+ZONE'
        elif isinstance(revision_date, datetime.datetime) and not revision_date.tzinfo:
            revision_date = revision_date.replace(tzinfo=LOCALTZ)
        self.revision_date = revision_date
        self.fuzzy = fuzzy

        # Dictionary of obsolete messages
        self.obsolete: dict[str | tuple[str, str], Message] = {}
        self._num_plurals = None
        self._plural_expr = None

    def _set_locale(self, locale: Locale | str | None) -> None:
        if locale is None:
            self._locale_identifier = None
            self._locale = None
            return

        if isinstance(locale, Locale):
            self._locale_identifier = str(locale)
            self._locale = locale
            return

        if isinstance(locale, str):
            self._locale_identifier = str(locale)
            try:
                self._locale = Locale.parse(locale)
            except UnknownLocaleError:
                self._locale = None
            return

        raise TypeError(
            f"`locale` must be a Locale, a locale identifier string, or None; got {locale!r}",
        )

    @property
    def locale(self) -> Locale | None:
        return self._locale

    @locale.setter
    def locale(self, locale: Locale | str | None) -> None:
        self._set_locale(locale)

    @property
    def locale_identifier(self) -> str | None:
        return self._locale_identifier

    def _get_header_comment(self) -> str:
        comment = self._header_comment
        year = datetime.datetime.now(LOCALTZ).strftime('%Y')
        if hasattr(self.revision_date, 'strftime'):
            year = self.revision_date.strftime('%Y')
        comment = (
            comment.replace('PROJECT', self.project)
            .replace('VERSION', self.version)
            .replace('YEAR', year)
            .replace('ORGANIZATION', self.copyright_holder)
        )
        locale_name = self.locale.english_name if self.locale else self.locale_identifier
        if locale_name:
            comment = comment.replace("Translations template", f"{locale_name} translations")
        return comment

    def _set_header_comment(self, string: str | None) -> None:
        self._header_comment = string

    @property
    def header_comment(self) -> str:
        """
        The header comment for the catalog.

        >>> catalog = Catalog(project='Foobar', version='1.0',
        ...                   copyright_holder='Foo Company')
        >>> print(catalog.header_comment) #doctest: +ELLIPSIS
        # Translations template for Foobar.
        # Copyright (C) ... Foo Company
        # This file is distributed under the same license as the Foobar project.
        # FIRST AUTHOR <EMAIL@ADDRESS>, ....
        #

        The header can also be set from a string. Any known upper-case variables
        will be replaced when the header is retrieved again:

        >>> catalog = Catalog(project='Foobar', version='1.0',
        ...                   copyright_holder='Foo Company')
        >>> catalog.header_comment = '''\\
        ... # The POT for my really cool PROJECT project.
        ... # Copyright (C) 1990-2003 ORGANIZATION
        ... # This file is distributed under the same license as the PROJECT
        ... # project.
        ... #'''
        >>> print(catalog.header_comment)
        # The POT for my really cool Foobar project.
        # Copyright (C) 1990-2003 Foo Company
        # This file is distributed under the same license as the Foobar
        # project.
        #
        """
        return self._get_header_comment()

    @header_comment.setter
    def header_comment(self, value: str) -> None:
        self._set_header_comment(value)

    def _get_mime_headers(self) -> list[tuple[str, str]]:
        if isinstance(self.revision_date, (datetime.datetime, datetime.time, int, float)):
            revision_date = format_datetime(
                self.revision_date,
                'yyyy-MM-dd HH:mmZ',
                locale='en',
            )
        else:
            revision_date = self.revision_date

        language_team = self.language_team
        if self.locale_identifier and 'LANGUAGE' in language_team:
            language_team = language_team.replace('LANGUAGE', str(self.locale_identifier))

        headers: list[tuple[str, str]] = [
            ("Project-Id-Version", f"{self.project} {self.version}"),
            ('Report-Msgid-Bugs-To', self.msgid_bugs_address),
            ('POT-Creation-Date', format_datetime(self.creation_date, 'yyyy-MM-dd HH:mmZ', locale='en')),
            ('PO-Revision-Date', revision_date),
            ('Last-Translator', self.last_translator),
        ]  # fmt: skip
        if self.locale_identifier:
            headers.append(('Language', str(self.locale_identifier)))
        headers.append(('Language-Team', language_team))
        if self.locale is not None or self._num_plurals is not None:
            # Keep explicit plural forms even when no locale set.
            headers.append(('Plural-Forms', self.plural_forms))
        headers += [
            ('MIME-Version', '1.0'),
            ("Content-Type", f"text/plain; charset={self.charset}"),
            ('Content-Transfer-Encoding', '8bit'),
            ("Generated-By", f"Babel {VERSION}\n"),
        ]
        return headers

    def _set_mime_headers(self, headers: Iterable[tuple[str, str]]) -> None:
        for name, value in headers:
            name = _force_text(name.lower(), encoding=self.charset)
            value = _force_text(value, encoding=self.charset)
            if name == 'project-id-version':
                parts = value.split(' ')
                self.project = ' '.join(parts[:-1])
                self.version = parts[-1]
            elif name == 'report-msgid-bugs-to':
                self.msgid_bugs_address = value
            elif name == 'last-translator':
                self.last_translator = value
            elif name == 'language':
                value = value.replace('-', '_')
                # The `or None` makes sure that the locale is set to None
                # if the header's value is an empty string, which is what
                # some tools generate (instead of eliding the empty Language
                # header altogether).
                self._set_locale(value or None)
            elif name == 'language-team':
                self.language_team = value
            elif name == 'content-type':
                params = parse_separated_header(value)
                if 'charset' in params:
                    self.charset = params['charset'].lower()
            elif name == 'plural-forms':
                params = parse_separated_header(f" ;{value}")
                self._num_plurals = int(params.get('nplurals', 2))
                self._plural_expr = params.get('plural', '(n != 1)')
            elif name == 'pot-creation-date':
                self.creation_date = _parse_datetime_header(value)
            elif name == 'po-revision-date':
                # Keep the value if it's not the default one
                if 'YEAR' not in value:
                    self.revision_date = _parse_datetime_header(value)

    @property
    def mime_headers(self) -> list[tuple[str, str]]:
        """
        The MIME headers of the catalog, used for the special ``msgid ""`` entry.

        The behavior of this property changes slightly depending on whether a locale
        is set or not, the latter indicating that the catalog is actually a template
        for actual translations.

        Here's an example of the output for such a catalog template:

        >>> from babel.dates import UTC
        >>> from datetime import datetime
        >>> created = datetime(1990, 4, 1, 15, 30, tzinfo=UTC)
        >>> catalog = Catalog(project='Foobar', version='1.0',
        ...                   creation_date=created)
        >>> for name, value in catalog.mime_headers:
        ...     print('%s: %s' % (name, value))
        Project-Id-Version: Foobar 1.0
        Report-Msgid-Bugs-To: EMAIL@ADDRESS
        POT-Creation-Date: 1990-04-01 15:30+0000
        PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE
        Last-Translator: FULL NAME <EMAIL@ADDRESS>
        Language-Team: LANGUAGE <LL@li.org>
        MIME-Version: 1.0
        Content-Type: text/plain; charset=utf-8
        Content-Transfer-Encoding: 8bit
        Generated-By: Babel ...

        And here's an example of the output when the locale is set:

        >>> revised = datetime(1990, 8, 3, 12, 0, tzinfo=UTC)
        >>> catalog = Catalog(locale='de_DE', project='Foobar', version='1.0',
        ...                   creation_date=created, revision_date=revised,
        ...                   last_translator='John Doe <jd@example.com>',
        ...                   language_team='de_DE <de@example.com>')
        >>> for name, value in catalog.mime_headers:
        ...     print('%s: %s' % (name, value))
        Project-Id-Version: Foobar 1.0
        Report-Msgid-Bugs-To: EMAIL@ADDRESS
        POT-Creation-Date: 1990-04-01 15:30+0000
        PO-Revision-Date: 1990-08-03 12:00+0000
        Last-Translator: John Doe <jd@example.com>
        Language: de_DE
        Language-Team: de_DE <de@example.com>
        Plural-Forms: nplurals=2; plural=(n != 1);
        MIME-Version: 1.0
        Content-Type: text/plain; charset=utf-8
        Content-Transfer-Encoding: 8bit
        Generated-By: Babel ...
        """
        return self._get_mime_headers()

    @mime_headers.setter
    def mime_headers(self, value: Iterable[tuple[str, str]]) -> None:
        self._set_mime_headers(value)

    @property
    def num_plurals(self) -> int:
        """The number of plurals used by the catalog or locale.

        >>> Catalog(locale='en').num_plurals
        2
        >>> Catalog(locale='ga').num_plurals
        5
        """
        if self._num_plurals is not None:
            return self._num_plurals
        if self.locale:
            return get_plural(self.locale)[0]
        return 2

    @property
    def plural_expr(self) -> str:
        """The plural expression used by the catalog or locale.

        >>> Catalog(locale='en').plural_expr
        '(n != 1)'
        >>> Catalog(locale='ga').plural_expr
        '(n == 1 ? 0 : n == 2 ? 1 : n >= 3 && n <= 6 ? 2 : n >= 7 && n <= 10 ? 3 : 4)'
        >>> Catalog(locale='ding').plural_expr  # unknown locale
        '(n != 1)'
        """
        if self._plural_expr is not None:
            return self._plural_expr
        if self.locale:
            return get_plural(self.locale)[1]
        return '(n != 1)'

    @property
    def plural_forms(self) -> str:
        """Return the plural forms declaration for the locale.

        >>> Catalog(locale='en').plural_forms
        'nplurals=2; plural=(n != 1);'
        >>> Catalog(locale='pt_BR').plural_forms
        'nplurals=3; plural=(n == 0 || n == 1) ? 0 : n != 0 && n % 1000000 == 0 ? 1 : 2;'
        """
        return f"nplurals={self.num_plurals}; plural={self.plural_expr};"

    def __contains__(self, id: _MessageID) -> bool:
        """Return whether the catalog has a message with the specified ID."""
        return self._key_for(id) in self._messages

    def __len__(self) -> int:
        """The number of messages in the catalog.

        This does not include the special ``msgid ""`` entry."""
        return len(self._messages)

    def __iter__(self) -> Iterator[Message]:
        """Iterates through all the entries in the catalog, in the order they
        were added, yielding a `Message` object for every entry.

        :rtype: ``iterator``"""
        buf = []
        for name, value in self.mime_headers:
            buf.append(f"{name}: {value}")
        flags = set()
        if self.fuzzy:
            flags |= {'fuzzy'}
        yield Message('', '\n'.join(buf), flags=flags)
        for key in self._messages:
            yield self._messages[key]

    def __repr__(self) -> str:
        locale = ''
        if self.locale:
            locale = f" {self.locale}"
        return f"<{type(self).__name__} {self.domain!r}{locale}>"

    def __delitem__(self, id: _MessageID) -> None:
        """Delete the message with the specified ID."""
        self.delete(id)

    def __getitem__(self, id: _MessageID) -> Message:
        """Return the message with the specified ID.

        :param id: the message ID
        """
        return self.get(id)

    def __setitem__(self, id: _MessageID, message: Message) -> None:
        """Add or update the message with the specified ID.

        >>> catalog = Catalog()
        >>> catalog['foo'] = Message('foo')
        >>> catalog['foo']
        <Message 'foo' (flags: [])>

        If a message with that ID is already in the catalog, it is updated
        to include the locations and flags of the new message.

        >>> catalog = Catalog()
        >>> catalog['foo'] = Message('foo', locations=[('main.py', 1)])
        >>> catalog['foo'].locations
        [('main.py', 1)]
        >>> catalog['foo'] = Message('foo', locations=[('utils.py', 5)])
        >>> catalog['foo'].locations
        [('main.py', 1), ('utils.py', 5)]

        :param id: the message ID
        :param message: the `Message` object
        """
        assert isinstance(message, Message), 'expected a Message object'
        key = self._key_for(id, message.context)
        current = self._messages.get(key)
        if current:
            if message.pluralizable and not current.pluralizable:
                # The new message adds pluralization
                current.id = message.id
                current.string = message.string
            current.locations = list(dict.fromkeys([*current.locations, *message.locations]))
            current.auto_comments = list(dict.fromkeys([*current.auto_comments, *message.auto_comments]))  # fmt:skip
            current.user_comments = list(dict.fromkeys([*current.user_comments, *message.user_comments]))  # fmt:skip
            current.flags |= message.flags
        elif id == '':
            # special treatment for the header message
            self.mime_headers = message_from_string(message.string).items()
            self.header_comment = "\n".join(f"# {c}".rstrip() for c in message.user_comments)
            self.fuzzy = message.fuzzy
        else:
            if isinstance(id, (list, tuple)):
                assert isinstance(message.string, (list, tuple)), (
                    f"Expected sequence but got {type(message.string)}"
                )
            self._messages[key] = message

    def add_conflict(self, message: Message, filename: str, project: str, version: str) -> None:
        """Record a conflicting translation for a message.

        When the same message ID has different translations across input files,
        the conflicting entry is stored and the message is marked as fuzzy in
        the output catalog.

        :param message: the conflicting :class:`Message` object
        :param filename: the basename of the file where the conflict originates
        :param project: the project name of the conflicting file
        :param version: the project version of the conflicting file
        """
        key = self._key_for(message.id, message.context)
        self._conflicts[key].append({
            'message': message,
            'filename': filename,
            'project': project,
            'version': version,
        })

    def get_conflicts(self, id: _MessageID, context: str | None = None) -> list[ConflictInfo]:
        """Return all recorded conflicts for a message ID.

        :param id: the message ID to look up conflicts for
        :param context: optional message context (msgctxt)
        :return: list of :class:`ConflictInfo` dicts, or an empty list if none
        """
        key = self._key_for(id, context)
        return self._conflicts.get(key, [])

    def add(
        self,
        id: _MessageID,
        string: _MessageID | None = None,
        locations: Iterable[tuple[str, int]] = (),
        flags: Iterable[str] = (),
        auto_comments: Iterable[str] = (),
        user_comments: Iterable[str] = (),
        previous_id: _MessageID = (),
        lineno: int | None = None,
        context: str | None = None,
    ) -> Message:
        """Add or update the message with the specified ID.

        >>> catalog = Catalog()
        >>> catalog.add('foo')
        <Message ...>
        >>> catalog['foo']
        <Message 'foo' (flags: [])>

        This method simply constructs a `Message` object with the given
        arguments and invokes `__setitem__` with that object.

        :param id: the message ID, or a ``(singular, plural)`` tuple for
                   pluralizable messages
        :param string: the translated message string, or a
                       ``(singular, plural)`` tuple for pluralizable messages
        :param locations: a sequence of ``(filename, lineno)`` tuples
        :param flags: a set or sequence of flags
        :param auto_comments: a sequence of automatic comments
        :param user_comments: a sequence of user comments
        :param previous_id: the previous message ID, or a ``(singular, plural)``
                            tuple for pluralizable messages
        :param lineno: the line number on which the msgid line was found in the
                       PO file, if any
        :param context: the message context
        """
        message = Message(
            id,
            string,
            list(locations),
            flags,
            auto_comments,
            user_comments,
            previous_id,
            lineno=lineno,
            context=context,
        )
        self[id] = message
        return message

    def check(self) -> Iterable[tuple[Message, list[TranslationError]]]:
        """Run various validation checks on the translations in the catalog.

        For every message which fails validation, this method yield a
        ``(message, errors)`` tuple, where ``message`` is the `Message` object
        and ``errors`` is a sequence of `TranslationError` objects.

        :rtype: ``generator`` of ``(message, errors)``
        """
        for message in self._messages.values():
            errors = message.check(catalog=self)
            if errors:
                yield message, errors

    def get(self, id: _MessageID, context: str | None = None) -> Message | None:
        """Return the message with the specified ID and context.

        :param id: the message ID
        :param context: the message context, or ``None`` for no context
        """
        return self._messages.get(self._key_for(id, context))

    def delete(self, id: _MessageID, context: str | None = None) -> None:
        """Delete the message with the specified ID and context.

        :param id: the message ID
        :param context: the message context, or ``None`` for no context
        """
        key = self._key_for(id, context)
        if key in self._messages:
            del self._messages[key]

    def update(
        self,
        template: Catalog,
        no_fuzzy_matching: bool = False,
        update_header_comment: bool = False,
        keep_user_comments: bool = True,
        update_creation_date: bool = True,
    ) -> None:
        """Update the catalog based on the given template catalog.

        >>> from babel.messages import Catalog
        >>> template = Catalog()
        >>> template.add('green', locations=[('main.py', 99)])
        <Message ...>
        >>> template.add('blue', locations=[('main.py', 100)])
        <Message ...>
        >>> template.add(('salad', 'salads'), locations=[('util.py', 42)])
        <Message ...>
        >>> catalog = Catalog(locale='de_DE')
        >>> catalog.add('blue', 'blau', locations=[('main.py', 98)])
        <Message ...>
        >>> catalog.add('head', 'Kopf', locations=[('util.py', 33)])
        <Message ...>
        >>> catalog.add(('salad', 'salads'), ('Salat', 'Salate'),
        ...             locations=[('util.py', 38)])
        <Message ...>

        >>> catalog.update(template)
        >>> len(catalog)
        3

        >>> msg1 = catalog['green']
        >>> msg1.string
        >>> msg1.locations
        [('main.py', 99)]

        >>> msg2 = catalog['blue']
        >>> msg2.string
        'blau'
        >>> msg2.locations
        [('main.py', 100)]

        >>> msg3 = catalog['salad']
        >>> msg3.string
        ('Salat', 'Salate')
        >>> msg3.locations
        [('util.py', 42)]

        Messages that are in the catalog but not in the template are removed
        from the main collection, but can still be accessed via the `obsolete`
        member:

        >>> 'head' in catalog
        False
        >>> list(catalog.obsolete.values())
        [<Message 'head' (flags: [])>]

        :param template: the reference catalog, usually read from a POT file
        :param no_fuzzy_matching: whether to use fuzzy matching of message IDs
        :param update_header_comment: whether to copy the header comment from the template
        :param keep_user_comments: whether to keep user comments from the old catalog
        :param update_creation_date: whether to copy the creation date from the template
        """
        messages = self._messages
        remaining = messages.copy()
        self._messages = {}

        # Prepare for fuzzy matching
        fuzzy_candidates = {}
        if not no_fuzzy_matching:
            for msgid in messages:
                if msgid and messages[msgid].string:
                    key = self._key_for(msgid)
                    ctxt = messages[msgid].context
                    fuzzy_candidates[self._to_fuzzy_match_key(key)] = (key, ctxt)
        fuzzy_matches = set()

        def _merge(
            message: Message,
            oldkey: tuple[str, str] | str,
            newkey: tuple[str, str] | str,
        ) -> None:
            message = message.clone()
            fuzzy = False
            if oldkey != newkey:
                fuzzy = True
                fuzzy_matches.add(oldkey)
                oldmsg = messages.get(oldkey)
                assert oldmsg is not None
                if isinstance(oldmsg.id, str):
                    message.previous_id = [oldmsg.id]
                else:
                    message.previous_id = list(oldmsg.id)
            else:
                oldmsg = remaining.pop(oldkey, None)
                assert oldmsg is not None
            message.string = oldmsg.string

            if keep_user_comments and oldmsg.user_comments:
                message.user_comments = list(dict.fromkeys(oldmsg.user_comments))

            if isinstance(message.id, (list, tuple)):
                if not isinstance(message.string, (list, tuple)):
                    fuzzy = True
                    message.string = tuple(
                        [message.string] + ([''] * (len(message.id) - 1)),
                    )
                elif len(message.string) != self.num_plurals:
                    fuzzy = True
                    message.string = tuple(message.string[: len(oldmsg.string)])
            elif isinstance(message.string, (list, tuple)):
                fuzzy = True
                message.string = message.string[0]
            message.flags |= oldmsg.flags
            if fuzzy:
                message.flags |= {'fuzzy'}
            self[message.id] = message

        for message in template:
            if message.id:
                key = self._key_for(message.id, message.context)
                if key in messages:
                    _merge(message, key, key)
                else:
                    if not no_fuzzy_matching:
                        # do some fuzzy matching with difflib
                        matches = get_close_matches(
                            self._to_fuzzy_match_key(key),
                            fuzzy_candidates.keys(),
                            1,
                        )
                        if matches:
                            modified_key = matches[0]
                            newkey, newctxt = fuzzy_candidates[modified_key]
                            if newctxt is not None:
                                newkey = newkey, newctxt
                            _merge(message, newkey, key)
                            continue

                    self[message.id] = message

        for msgid in remaining:
            if no_fuzzy_matching or msgid not in fuzzy_matches:
                self.obsolete[msgid] = remaining[msgid]

        if update_header_comment:
            # Allow the updated catalog's header to be rewritten based on the
            # template's header
            self.header_comment = template.header_comment

        # Make updated catalog's POT-Creation-Date equal to the template
        # used to update the catalog
        if update_creation_date:
            self.creation_date = template.creation_date

    def _to_fuzzy_match_key(self, key: tuple[str, str] | str) -> str:
        """Converts a message key to a string suitable for fuzzy matching."""
        if isinstance(key, tuple):
            matchkey = key[0]  # just the msgid, no context
        else:
            matchkey = key
        return matchkey.lower().strip()

    def _key_for(
        self,
        id: _MessageID,
        context: str | None = None,
    ) -> tuple[str, str] | str:
        """The key for a message is just the singular ID even for pluralizable
        messages, but is a ``(msgid, msgctxt)`` tuple for context-specific
        messages.
        """
        key = id
        if isinstance(key, (list, tuple)):
            key = id[0]
        if context is not None:
            key = (key, context)
        return key

    def is_identical(self, other: Catalog) -> bool:
        """Checks if catalogs are identical, taking into account messages and
        headers.
        """
        assert isinstance(other, Catalog)
        for key in self._messages.keys() | other._messages.keys():
            message_1 = self.get(key)
            message_2 = other.get(key)
            if message_1 is None or message_2 is None or not message_1.is_identical(message_2):
                return False
        return dict(self.mime_headers) == dict(other.mime_headers)


def _merge_catalog_key(message: Message) -> tuple[str | None, object]:
    # Messages are identified by context plus the *complete* msgid, so a
    # singular and a plural message with the same singular string stay apart.
    msgid: object = tuple(message.id) if message.pluralizable else message.id
    return message.context, msgid


def _message_snapshot(message: Message | None) -> dict[str, object] | None:
    # Content used for three-way presence comparison; parser bookkeeping such
    # as ``lineno`` is intentionally excluded.
    if message is None:
        return None
    return {
        'id': tuple(message.id) if message.pluralizable else message.id,
        'string': tuple(message.string) if message.pluralizable else (message.string or ''),
        'flags': frozenset(message.flags),
        'auto_comments': tuple(message.auto_comments),
        'user_comments': tuple(message.user_comments),
        'locations': tuple(message.locations),
        'previous_id': tuple(message.previous_id),
        'context': message.context,
    }


def _ordered_union(*sequences: Iterable[object]) -> list[object]:
    # Stable de-duplicating union preserving first-seen order.
    return list(dict.fromkeys(item for sequence in sequences for item in sequence))


def _resolve_presence(
    base_snapshot: dict[str, object] | None,
    local_snapshot: dict[str, object] | None,
    incoming_snapshot: dict[str, object] | None,
    *,
    base_obsolete: bool,
    local_obsolete: bool,
    incoming_obsolete: bool,
) -> tuple[str, bool]:
    # Resolve one message presence across the catalogs. Returns
    # ``(action, result_obsolete)``; action is keep, drop or conflict.
    # Obsolete is a soft deletion: an unchanged obsolete entry facing an
    # actively modified entry is a resurrection, while a hard deletion
    # facing a modification is a conflict.
    local_absent = local_snapshot is None
    incoming_absent = incoming_snapshot is None
    local_removed = local_absent or local_obsolete
    incoming_removed = incoming_absent or incoming_obsolete
    local_changed = local_snapshot != base_snapshot
    incoming_changed = incoming_snapshot != base_snapshot

    if base_snapshot is None or base_obsolete:
        # The message was absent or obsolete in the base. An active entry on
        # a branch (re)introduces it; otherwise the obsolete form is kept (or
        # dropped once a branch fully deleted it).
        if not local_removed or not incoming_removed:
            return 'keep', False  # resurrection / new message
        if local_absent or incoming_absent:
            return 'drop', False
        return 'keep', True

    if not local_removed and not incoming_removed:
        return 'keep', False
    if local_removed and incoming_removed:
        return ('drop', False) if (local_absent or incoming_absent) else ('keep', True)

    if local_removed:
        if local_absent:
            # Hard local deletion vs an active incoming change is a conflict;
            # the local deletion still wins (message dropped).
            return ('conflict', False) if incoming_changed else ('drop', False)
        # Local obsoleted (soft): an incoming content change resurrects the
        # message; an incoming content edit recorded *on the obsolete entry*
        # is an obsolete-vs-modified conflict.
        if not local_changed:
            return 'keep', not incoming_changed
        return 'conflict', True

    if incoming_absent:
        return ('conflict', False) if local_changed else ('drop', False)
    if local_changed:
        return 'conflict', False  # local modified, incoming obsoleted
    return 'keep', True  # unchanged local, incoming obsoleted


def _three_way_field(base: object, local: object, incoming: object) -> tuple[object, bool]:
    # Three-way merge of one scalar field; returns (value, conflict).
    if local == base:
        return incoming, False
    if incoming == base:
        return local, False
    if local == incoming:
        return local, False
    return local, True


def _conflict_value(message: Message | None) -> str | list[str] | None:
    # JSON-serialisable representation of a possibly missing message.
    if message is None:
        return None
    if message.pluralizable:
        return list(message.string)
    return message.string or ''


def merge_catalogs(
    base: Catalog,
    local: Catalog,
    incoming: Catalog,
) -> CatalogMergeResult:
    """Merge two translation branches diverged from a common ``base`` catalog.

    The input catalogs are never modified.  A new `Catalog` with cloned
    `Message` objects is returned, together with a structured, JSON-
    serialisable conflict list.  The result can be written with `write_po`
    and read back with `read_po`.

    Messages are identified by their context and their *complete* msgid
    (the singular/plural pair); singular and plural messages never collapse
    into one entry.  No fuzzy similarity matching is performed, so a renamed
    message is a deletion plus an addition.

    Per message:

    * unchanged relative to base -> base value is kept;
    * one branch changed a translation, a single plural slot, or developer
      (``#.``) comments -> that branch's value is used;
    * both branches changed the same field identically -> shared value;
    * both branches changed the same field differently -> the ``local`` value
      is kept and a message-level conflict records base/local/incoming;
    * plural translations merge slot by slot, so independent slots changed on
      different branches combine without a conflict;
    * one branch deletes (or obsoletes) while the other modifies -> the
      ``local`` version is kept and a ``presence`` conflict is recorded;
    * locations are unioned and de-duplicated (base order first); translator
      (``# ``) comments are unioned in original order; flags are unioned so a
      ``fuzzy`` flag is never stripped automatically.

    Obsolete semantics are preserved.  Differing locales or Plural-Forms are
    catalog-level conflicts; with mismatched plural rules, plural translations
    are not spliced and keep the complete ``local`` form.  Header metadata is
    taken from ``local``.
    """

    conflicts: list[MergeConflict] = []

    local_locale = local.locale_identifier
    incoming_locale = incoming.locale_identifier
    if local_locale != incoming_locale:
        conflicts.append(
            {
                'level': 'catalog',
                'field': 'locale',
                'base': base.locale_identifier,
                'local': local_locale,
                'incoming': incoming_locale,
            },
        )

    plural_forms_conflict = local.plural_forms != incoming.plural_forms
    if plural_forms_conflict:
        conflicts.append(
            {
                'level': 'catalog',
                'field': 'plural_forms',
                'base': base.plural_forms,
                'local': local.plural_forms,
                'incoming': incoming.plural_forms,
            },
        )

    result = deepcopy(local)
    result._messages = {}
    result.obsolete = {}
    result._conflicts = defaultdict(list)

    def find(catalog: Catalog, key: tuple[str | None, object]) -> tuple[Message | None, bool]:
        context, msgid = key
        lookup_id: _MessageID = msgid  # type: ignore[assignment]
        active = catalog.get(lookup_id, context)  # type: ignore[arg-type]
        if active is not None:
            return active, False
        stored = catalog.obsolete.get(catalog._key_for(lookup_id, context))  # type: ignore[arg-type]
        return stored, stored is not None

    all_keys: dict[tuple[str | None, object], None] = {}
    for catalog in (base, local, incoming):
        for message in [*catalog._messages.values(), *catalog.obsolete.values()]:
            all_keys.setdefault(_merge_catalog_key(message), None)

    def _key_sort_key(key: tuple[str | None, object]) -> tuple[object, ...]:
        context, msgid = key
        if isinstance(msgid, tuple):
            identity: tuple[object, ...] = (1, msgid[0], msgid[1] if len(msgid) > 1 else '')
        else:
            identity = (0, msgid, '')
        return (context is None, context or '', *identity)

    for key in sorted(all_keys, key=_key_sort_key):
        context, _msgid = key
        base_message, _base_obsolete = find(base, key)
        local_message, local_obsolete = find(local, key)
        incoming_message, incoming_obsolete = find(incoming, key)
        presence, result_obsolete = _resolve_presence(
            _message_snapshot(base_message),
            _message_snapshot(local_message),
            _message_snapshot(incoming_message),
            base_obsolete=_base_obsolete,
            local_obsolete=local_obsolete,
            incoming_obsolete=incoming_obsolete,
        )

        if presence == 'drop':
            continue

        message_conflicts: list[MergeConflict] = []
        if presence == 'conflict':
            # The local version always wins; a hard local deletion drops the
            # message from the result entirely, an obsolete local version is
            # kept obsolete.
            kind = (
                'obsolete_vs_modified'
                if local_message is not None and (local_obsolete or incoming_obsolete)
                else 'deleted_vs_modified'
            )
            message_conflicts.append(
                {
                    'level': 'message',
                    'field': 'presence',
                    'kind': kind,
                    'context': context,
                    'msgid': key[1],
                    'base': _conflict_value(base_message),
                    'local': _conflict_value(local_message),
                    'incoming': _conflict_value(incoming_message),
                },
            )
            if local_message is None:
                conflicts.extend(message_conflicts)
                continue
            kept_message = local_message.clone()
        else:
            if local_message is not None and not local_obsolete:
                survivor = local_message
            elif incoming_message is not None and not incoming_obsolete:
                survivor = incoming_message
            else:
                survivor = local_message or incoming_message or base_message
            kept_message = survivor.clone()
            if local_message is not None or incoming_message is not None:
                # Cross-state keeps (resurrections / obsolete propagation) may
                # combine metadata from the other side; a same-state merge does
                # the full three-way field merge.
                same_state = (
                    not local_obsolete
                    and not incoming_obsolete
                    and local_message is not None
                    and incoming_message is not None
                )
                if same_state:
                    _merge_message_fields(
                        kept_message,
                        base_message,
                        local_message,
                        incoming_message,
                        key,
                        plural_forms_conflict=plural_forms_conflict,
                        message_conflicts=message_conflicts,
                    )
                else:
                    _merge_message_metadata(
                        kept_message,
                        base_message,
                        local_message,
                        incoming_message,
                    )

        kept_message.lineno = None
        stored_key = result._key_for(kept_message.id, kept_message.context)
        if result_obsolete:
            result.obsolete[stored_key] = kept_message
        else:
            result._messages[stored_key] = kept_message
        conflicts.extend(message_conflicts)

    return CatalogMergeResult(result, conflicts)


def _merge_message_fields(
    merged: Message,
    base: Message | None,
    local: Message | None,
    incoming: Message | None,
    key: tuple[str | None, object],
    *,
    plural_forms_conflict: bool,
    message_conflicts: list[MergeConflict],
) -> None:
    # Field-by-field three-way merge into an already cloned target message.

    def add_conflict(
        field: str,
        base_value: object,
        local_value: object,
        incoming_value: object,
        plural_index: int | None = None,
    ) -> None:
        conflict: MergeConflict = {
            'level': 'message',
            'field': field,
            'context': key[0],
            'msgid': key[1],
            'base': base_value,
            'local': local_value,
            'incoming': incoming_value,
        }
        if plural_index is not None:
            conflict['plural_index'] = plural_index
        message_conflicts.append(conflict)

    # Translations. Plural slots merge independently, but only while the
    # plural rules agree; otherwise local translations are kept wholesale and
    # slots are never spliced across different rules.
    if merged.pluralizable:
        if plural_forms_conflict:
            if local is not None:
                merged.string = tuple(local.string)
        else:

            def slot(message: Message | None, index: int) -> str:
                if message is not None and index < len(message.string):
                    return message.string[index]
                return ''

            slot_sources = [
                message.string
                for message in (base, local, incoming)
                if message is not None and isinstance(message.string, (list, tuple))
            ]
            max_slots = max((len(slots) for slots in slot_sources), default=0)
            merged_slots: list[str] = []
            for index in range(max_slots):
                value, conflicted = _three_way_field(
                    slot(base, index),
                    slot(local, index),
                    slot(incoming, index),
                )
                merged_slots.append(value or '')
                if conflicted:
                    add_conflict(
                        'translation',
                        slot(base, index),
                        slot(local, index),
                        slot(incoming, index),
                        plural_index=index,
                    )
            merged.string = tuple(merged_slots)
    else:

        def singular(message: Message | None) -> str:
            return (message.string or '') if message is not None else ''

        value, conflicted = _three_way_field(
            singular(base),
            singular(local),
            singular(incoming),
        )
        merged.string = value or ''
        if conflicted:
            add_conflict('translation', singular(base), singular(local), singular(incoming))

    # Developer (automatic, ``#.``) comments compare as a single field.
    def auto(message: Message | None) -> list[str]:
        return list(message.auto_comments) if message is not None else []

    value, conflicted = _three_way_field(auto(base), auto(local), auto(incoming))
    merged.auto_comments = list(value) if value is not None else []
    if conflicted:
        add_conflict('auto_comments', auto(base), auto(local), auto(incoming))

    # Translator (``# ``) comments: ordered union, base first, then additions
    # from local, then from incoming.
    def user(message: Message | None) -> list[str]:
        return list(message.user_comments) if message is not None else []

    merged.user_comments = [*_ordered_union(user(base), user(local), user(incoming))]

    # Locations: stable de-duplicated union in the same order.
    def locations(message: Message | None) -> list[tuple[str, int | None]]:
        return list(message.locations) if message is not None else []

    merged.locations = [
        *_ordered_union(locations(base), locations(local), locations(incoming)),
    ]

    # Flags are unioned; fuzzy is never removed automatically. previous_id and
    # lineno follow local (lineno is reset by the caller).
    merged.flags = set().union(
        *(message.flags for message in (base, local, incoming) if message),
    )
    if local is not None and local.previous_id:
        merged.previous_id = list(local.previous_id)


def _merge_message_metadata(
    merged: Message,
    base: Message | None,
    local: Message | None,
    incoming: Message | None,
) -> None:
    # Merge comments/locations/flags without touching the translation, used
    # when presence was resolved across active/obsolete states.
    def user(message: Message | None) -> list[str]:
        return list(message.user_comments) if message is not None else []

    def auto(message: Message | None) -> list[str]:
        return list(message.auto_comments) if message is not None else []

    def locations(message: Message | None) -> list[tuple[str, int | None]]:
        return list(message.locations) if message is not None else []

    merged.user_comments = [*_ordered_union(user(base), user(local), user(incoming))]
    merged.auto_comments = [*_ordered_union(auto(base), auto(local), auto(incoming))]
    merged.locations = [
        *_ordered_union(locations(base), locations(local), locations(incoming)),
    ]
    merged.flags = set().union(
        *(message.flags for message in (base, local, incoming) if message),
    )
