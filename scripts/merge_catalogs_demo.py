#!/usr/bin/env python3
"""Demo for ``babel.messages.catalog.merge_catalogs``.

Running this script without arguments creates three small PO catalogs (base,
local, incoming) covering:

* the same msgid in different msgctxt entries,
* two plural slots changed independently on the two branches,
* a conflicting singular translation,
* a one-sided deletion (no conflict),
* a deletion on one side against a modification on the other,
* Unicode content, locations, translator/developer comments and a fuzzy flag.

It then merges them, writes ``merged.po`` and ``conflicts.json`` into the
output directory, prints the independent plural-slot merge plus every
conflict with its base/local/incoming values, and exits with a non-zero code
when conflicts were found.

The ``merge`` subcommand performs the same operation on arbitrary PO files::

    python scripts/merge_catalogs_demo.py merge base.po local.po incoming.po out
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from babel.messages.catalog import merge_catalogs
from babel.messages.pofile import read_po, write_po

BASE_PO = r'''msgid ""
msgstr ""
"Language: de\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"
"Content-Type: text/plain; charset=utf-8\n"

#: app.py:10
msgid "Save"
msgstr "base-save"

#: app.py:20
msgctxt "menu"
msgid "Open"
msgstr "base-open-menu"

#: app.py:30
#. developer note for apples
msgid "%(num)d apple"
msgid_plural "%(num)d apples"
msgstr[0] "base-one"
msgstr[1] "base-many"

#: app.py:40
msgid "Welcome"
msgstr "base-welcome"

#: app.py:50
msgid "Settings"
msgstr "base-settings"

#: app.py:60
msgid "Goodbye"
msgstr "base-goodbye"
'''

LOCAL_PO = r'''msgid ""
msgstr ""
"Language: de\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"
"Content-Type: text/plain; charset=utf-8\n"

#: app.py:10
#  local translator remark
msgid "Save"
msgstr "lokal-speichern"

#: app.py:20
#: app.py:21
msgctxt "menu"
msgid "Open"
msgstr "base-open-menu"

#: app.py:30
#. developer note for apples
msgid "%(num)d apple"
msgid_plural "%(num)d apples"
msgstr[0] "lokal-eine"
msgstr[1] "base-many"

#: app.py:40
msgid "Welcome"
msgstr "Willkommen ☺"

#: app.py:60
msgid "Goodbye"
msgstr "lokal-tschuess"

# local branch simply removed the Settings entry (one-sided deletion)
'''

INCOMING_PO = r'''msgid ""
msgstr ""
"Language: de\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"
"Content-Type: text/plain; charset=utf-8\n"

#: app.py:10
msgid "Save"
msgstr "base-save"

#: app.py:20
msgctxt "menu"
msgid "Open"
msgstr "eingehend-offen"

#: app.py:30
#. developer note for apples
#  incoming translator remark
msgid "%(num)d apple"
msgid_plural "%(num)d apples"
msgstr[0] "base-one"
msgstr[1] "eingehend-viele"

#: app.py:40
msgid "Welcome"
msgstr "Herzlich willkommen 你好"

#: app.py:50
#: app.py:51
msgid "Settings"
msgstr "base-settings"

# incoming branch deleted Goodbye
'''


def run_merge(base_path: Path, local_path: Path, incoming_path: Path, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    with base_path.open('rb') as fp:
        base = read_po(fp)
    with local_path.open('rb') as fp:
        local = read_po(fp)
    with incoming_path.open('rb') as fp:
        incoming = read_po(fp)

    merged, conflicts = merge_catalogs(base, local, incoming)

    merged_path = out_dir / 'merged.po'
    with merged_path.open('wb') as fp:
        write_po(fp, merged)
    conflicts_path = out_dir / 'conflicts.json'
    with conflicts_path.open('w', encoding='utf-8') as fp:
        json.dump(conflicts, fp, ensure_ascii=False, indent=2, sort_keys=True)
        fp.write('\n')

    plural = merged.get('%(num)d apple')
    print('Independent plural slots merged to:', plural.string)
    print(f'Wrote {merged_path} and {conflicts_path} ({len(conflicts)} conflict entries)')
    for conflict in conflicts:
        print(json.dumps(conflict, ensure_ascii=False, sort_keys=True))
    return 1 if conflicts else 0


def main(argv: list[str]) -> int:
    if len(argv) == 1:
        import tempfile

        out_dir = Path(tempfile.gettempdir()) / 'babel-merge-catalogs-demo'
        paths = []
        for name, content in (
            ('base.po', BASE_PO),
            ('local.po', LOCAL_PO),
            ('incoming.po', INCOMING_PO),
        ):
            path = out_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            paths.append(path)
        print(f'Fixture PO files written to {out_dir}')
        return run_merge(paths[0], paths[1], paths[2], out_dir)
    if len(argv) == 6 and argv[1] == 'merge':
        return run_merge(Path(argv[2]), Path(argv[3]), Path(argv[4]), Path(argv[5]))
    print(__doc__)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
