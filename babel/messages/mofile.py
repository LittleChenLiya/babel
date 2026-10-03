"""
babel.messages.mofile
~~~~~~~~~~~~~~~~~~~~~

Writing of files in the ``gettext`` MO (machine object) format.

:copyright: (c) 2013-2026 by the Babel Team.
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

import array
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

from babel.messages.catalog import Catalog, Message

if TYPE_CHECKING:
    from _typeshed import SupportsRead, SupportsWrite

LE_MAGIC: int = 0x950412DE
BE_MAGIC: int = 0xDE120495

__all__ = [
    'BE_MAGIC',
    'LE_MAGIC',
    'MoEncodingError',
    'check_mo_encoding',
    'read_mo',
    'write_mo',
]


def read_mo(fileobj: SupportsRead[bytes]) -> Catalog:
    """Read a binary MO file from the given file-like object and return a
    corresponding `Catalog` object.

    :param fileobj: the file-like object to read the MO file from

    :note: The implementation of this function is heavily based on the
           ``GNUTranslations._parse`` method of the ``gettext`` module in the
           standard library.
    """
    catalog = Catalog()
    headers = {}

    filename = getattr(fileobj, 'name', '')

    buf = fileobj.read()
    buflen = len(buf)
    unpack = struct.unpack

    # Parse the .mo file header, which consists of 5 little endian 32
    # bit words.
    magic = unpack('<I', buf[:4])[0]  # Are we big endian or little endian?
    if magic == LE_MAGIC:
        version, msgcount, origidx, transidx = unpack('<4I', buf[4:20])
        ii = '<II'
    elif magic == BE_MAGIC:
        version, msgcount, origidx, transidx = unpack('>4I', buf[4:20])
        ii = '>II'
    else:
        raise OSError(0, 'Bad magic number', filename)

    # Now put all messages from the .mo file buffer into the catalog
    # dictionary
    for _i in range(msgcount):
        mlen, moff = unpack(ii, buf[origidx : origidx + 8])
        mend = moff + mlen
        tlen, toff = unpack(ii, buf[transidx : transidx + 8])
        tend = toff + tlen
        if mend < buflen and tend < buflen:
            raw_msg: bytes = buf[moff:mend]
            raw_tmsg: bytes = buf[toff:tend]
        else:
            raise OSError(0, 'File is corrupt', filename)

        # See if we're looking at GNU .mo conventions for metadata
        if mlen == 0:
            # Catalog description
            lastkey = key = None
            for item in raw_tmsg.splitlines():
                item = item.strip()
                if not item:
                    continue
                if b':' in item:
                    key, value = item.split(b':', 1)
                    lastkey = key = key.strip().lower()
                    headers[key] = value.strip()
                elif lastkey:
                    headers[lastkey] += b'\n' + item

        ctxt: str | None = None
        msg: list[str] | str
        tmsg: list[str] | str

        # > Contexts are stored by storing the concatenation of the context,
        # > a EOT byte, and the original string, instead of the original string.
        # - https://www.gnu.org/software/gettext/manual/html_node/MO-Files.html
        ctxt_or_msg, sep, raw_msg = raw_msg.partition(b'\x04')
        if sep:
            ctxt = ctxt_or_msg.decode(catalog.charset)
        else:
            raw_msg = ctxt_or_msg

        if b'\x00' in raw_msg:  # plural forms
            msg = [x.decode(catalog.charset) for x in raw_msg.split(b'\x00')]
            tmsg = [x.decode(catalog.charset) for x in raw_tmsg.split(b'\x00')]
        else:
            msg = raw_msg.decode(catalog.charset)
            tmsg = raw_tmsg.decode(catalog.charset)
        catalog[msg] = Message(msg, tmsg, context=ctxt)

        # advance to next entry in the seek tables
        origidx += 8
        transidx += 8

    catalog.mime_headers = headers.items()
    return catalog


def write_mo(fileobj: SupportsWrite[bytes], catalog: Catalog, use_fuzzy: bool = False) -> None:
    """Write a catalog to the specified file-like object using the GNU MO file
    format.

    >>> import sys
    >>> from babel.messages import Catalog
    >>> from gettext import GNUTranslations
    >>> from io import BytesIO

    >>> catalog = Catalog(locale='en_US')
    >>> catalog.add('foo', 'Voh')
    <Message ...>
    >>> catalog.add(('bar', 'baz'), ('Bahr', 'Batz'))
    <Message ...>
    >>> catalog.add('fuz', 'Futz', flags=['fuzzy'])
    <Message ...>
    >>> catalog.add('Fizz', '')
    <Message ...>
    >>> catalog.add(('Fuzz', 'Fuzzes'), ('', ''))
    <Message ...>
    >>> buf = BytesIO()

    >>> write_mo(buf, catalog)
    >>> x = buf.seek(0)
    >>> translations = GNUTranslations(fp=buf)
    >>> if sys.version_info[0] >= 3:
    ...     translations.ugettext = translations.gettext
    ...     translations.ungettext = translations.ngettext
    >>> translations.ugettext('foo')
    'Voh'
    >>> translations.ungettext('bar', 'baz', 1)
    'Bahr'
    >>> translations.ungettext('bar', 'baz', 2)
    'Batz'
    >>> translations.ugettext('fuz')
    'fuz'
    >>> translations.ugettext('Fizz')
    'Fizz'
    >>> translations.ugettext('Fuzz')
    'Fuzz'
    >>> translations.ugettext('Fuzzes')
    'Fuzzes'

    :param fileobj: the file-like object to write to
    :param catalog: the `Catalog` instance
    :param use_fuzzy: whether translations marked as "fuzzy" should be included
                      in the output
    """
    messages = list(catalog)
    messages[1:] = [m for m in messages[1:] if m.string and (use_fuzzy or not m.fuzzy)]
    messages.sort()

    ids = strs = b''
    offsets = []

    for message in messages:
        # For each string, we need size and file offset.  Each string is NUL
        # terminated; the NUL does not count into the size.
        if message.pluralizable:
            msgid = b'\x00'.join(msgid.encode(catalog.charset) for msgid in message.id)
            msgstrs = []
            for idx, string in enumerate(message.string):
                if not string:
                    msgstrs.append(message.id[min(int(idx), 1)])
                else:
                    msgstrs.append(string)
            msgstr = b'\x00'.join(msgstr.encode(catalog.charset) for msgstr in msgstrs)
        else:
            msgid = message.id.encode(catalog.charset)
            msgstr = message.string.encode(catalog.charset)
        if message.context:
            msgid = b'\x04'.join([message.context.encode(catalog.charset), msgid])
        offsets.append((len(ids), len(msgid), len(strs), len(msgstr)))
        ids += msgid + b'\x00'
        strs += msgstr + b'\x00'

    # The header is 7 32-bit unsigned integers.  We don't use hash tables, so
    # the keys start right after the index tables.
    keystart = 7 * 4 + 16 * len(messages)
    valuestart = keystart + len(ids)

    # The string table first has the list of keys, then the list of values.
    # Each entry has first the size of the string, then the file offset.
    koffsets = []
    voffsets = []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]
    offsets = koffsets + voffsets

    header = struct.pack(
        'Iiiiiii',
        LE_MAGIC,  # magic
        0,  # version
        len(messages),  # number of entries
        7 * 4,  # start of key index
        7 * 4 + len(messages) * 8,  # start of value index
        0,
        0,  # size and offset of hash table
    )

    fileobj.write(header + array.array.tobytes(array.array("i", offsets)) + ids + strs)


@dataclass
class MoEncodingError:
    """A string in a catalog that cannot be encoded in the catalog's charset.

    This describes a single component (message context, id, or a translation
    slot) of a single message that :func:`write_mo` would fail to encode,
    together with the position of the first unencodable character.
    """

    message: Message
    """The message that contains the unencodable string."""

    slot: str
    """Which part of the message failed.

    One of ``'msgctxt'``, ``'msgid'`` or ``'msgstr'`` for singular messages,
    and additionally ``'msgid[1]'`` / ``'msgstr[1]'`` (and higher indices) for
    the plural source and translation slots.
    """

    text: str
    """The actual text that was to be encoded.

    For plural translation slots this is the text :func:`write_mo` would
    write, i.e. the source id is used as a fallback for empty translations.
    """

    start: int
    """The character index of the first unencodable character in ``text``."""

    end: int
    """The index one past the first unencodable character."""

    charset: str
    """The charset the text was being encoded in (the catalog's charset)."""

    reason: str
    """The underlying codec error message."""

    @property
    def character(self) -> str | None:
        """The first unencodable character, or ``None`` if out of range."""
        if self.start < 0 or self.start >= len(self.text):
            return None
        return self.text[self.start]

    def __str__(self) -> str:
        ident = _describe_message(self.message)
        ch = self.character
        if ch is None:
            where = f"position {self.start}"
        else:
            where = f"position {self.start} ({ch!r}, U+{ord(ch):04X})"
        return (
            f"{ident}: {self.slot}: cannot encode {where} "
            f"in charset {self.charset!r}"
        )


def _describe_message(message: Message) -> str:
    """Return a short human-readable identification of a message."""
    if not message.id and not message.pluralizable:
        return "catalog header (msgid '')"
    parts: list[str] = []
    if message.context:
        parts.append(f"msgctxt {message.context!r}")
    if message.pluralizable:
        parts.append(f"msgid {message.id[0]!r}")
        parts.append(f"msgid[1] {message.id[1]!r}")
    else:
        parts.append(f"msgid {message.id!r}")
    return " ".join(parts)


def _iter_mo_strings(message: Message) -> Iterator[tuple[str, str]]:
    """Yield ``(slot, text)`` pairs for every string :func:`write_mo` would
    encode for the given message, using the same context separator and plural
    slot concatenation rules."""
    if message.context:
        # write_mo joins the context to the id with a '\x04' separator
        yield 'msgctxt', message.context
    if message.pluralizable:
        # write_mo joins the id slots with '\x00'
        for idx, msgid in enumerate(message.id):
            slot = 'msgid' if idx == 0 else f'msgid[{idx}]'
            yield slot, msgid
        for idx, string in enumerate(message.string):
            if not string:
                # write_mo falls back to the source id for empty translations
                text = message.id[min(int(idx), 1)]
            else:
                text = string
            slot = 'msgstr' if idx == 0 else f'msgstr[{idx}]'
            yield slot, text
    else:
        yield 'msgid', message.id
        yield 'msgstr', message.string


def check_mo_encoding(
    catalog: Catalog,
    use_fuzzy: bool = False,
) -> list[MoEncodingError]:
    """Check that every string :func:`write_mo` would write can be encoded in
    the catalog's charset.

    This is a read-only pre-flight check that mirrors :func:`write_mo`'s
    message selection (the header is always included; empty translations and
    fuzzy messages are skipped just like :func:`write_mo` does) as well as its
    context separator and plural slot concatenation rules.  It never modifies
    the catalog (neither its charset nor its translations) and never writes
    anything.

    Unlike :func:`write_mo`, which fails on the first unencodable string, this
    function collects and returns *all* encoding errors so they can be fixed
    before attempting to write the MO file.

    >>> from babel.messages import Catalog
    >>> from io import BytesIO

    >>> catalog = Catalog(charset='ascii')
    >>> catalog.add('hello', '你好')
    <Message ...>
    >>> errors = check_mo_encoding(catalog)
    >>> len(errors)
    1
    >>> errors[0].slot
    'msgstr'
    >>> errors[0].start
    0
    >>> errors[0].character
    '你'

    A catalog using a charset that covers all its strings passes without
    errors, and the catalog is left untouched:

    >>> catalog = Catalog(charset='utf-8')
    >>> catalog.add('hello', '你好')
    <Message ...>
    >>> check_mo_encoding(catalog)
    []
    >>> catalog.charset
    'utf-8'

    :param catalog: the `Catalog` to check
    :param use_fuzzy: whether fuzzy translations would be included, as in
                      :func:`write_mo`
    :return: a list of `MoEncodingError` objects, one per unencodable string
             component, in the order the messages are written
    """
    charset = catalog.charset
    messages = list(catalog)
    # Mirror write_mo's filtering and sorting exactly.
    messages[1:] = [m for m in messages[1:] if m.string and (use_fuzzy or not m.fuzzy)]
    messages.sort()

    errors: list[MoEncodingError] = []
    for message in messages:
        for slot, text in _iter_mo_strings(message):
            try:
                text.encode(charset)
            except UnicodeEncodeError as e:
                errors.append(
                    MoEncodingError(
                        message=message,
                        slot=slot,
                        text=text,
                        start=e.start,
                        end=e.end,
                        charset=charset,
                        reason=str(e),
                    ),
                )
    return errors
