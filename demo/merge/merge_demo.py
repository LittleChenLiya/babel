#!/usr/bin/env python
"""Three-way catalog merge demo.

Merges ``base.po``, ``local.po`` and ``incoming.po`` from a directory using
:func:`babel.messages.catalog.merge_catalogs`, writes ``merged.po`` and
``conflicts.json`` to an output directory, prints the independent plural-slot
merge and the base/local/incoming values recorded for each conflict, and exits
with a non-zero status when any conflict is found.

Usage:
    python demo/merge/merge_demo.py [INPUT_DIR] [OUTPUT_DIR]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from babel.messages.catalog import merge_catalogs
from babel.messages.pofile import read_po, write_po


def load_catalog(path: Path):
    with path.open('rb') as fh:
        # Locale and Plural-Forms come from the PO headers themselves.
        return read_po(fh)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    input_dir = Path(argv[0]) if len(argv) > 0 else Path(__file__).parent
    output_dir = Path(argv[1]) if len(argv) > 1 else input_dir / 'out'
    output_dir.mkdir(parents=True, exist_ok=True)

    base = load_catalog(input_dir / 'base.po')
    local = load_catalog(input_dir / 'local.po')
    incoming = load_catalog(input_dir / 'incoming.po')

    merged, conflicts = merge_catalogs(base, local, incoming)

    merged_path = output_dir / 'merged.po'
    with merged_path.open('wb') as fh:
        write_po(fh, merged)

    conflicts_path = output_dir / 'conflicts.json'
    with conflicts_path.open('w', encoding='utf-8') as fh:
        json.dump(conflicts, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write('\n')

    print('Independent plural-slot merge for {count} file(s):')
    plural_message = merged.get(('{count} file', '{count} files'))
    if plural_message is not None:
        print(f'  msgstr[0] (local-only change)    = {plural_message.string[0]!r}')
        print(f'  msgstr[1] (incoming-only change) = {plural_message.string[1]!r}')
        print(f'  fuzzy flag preserved: {plural_message.fuzzy}')
        print(f'  locations (stable dedup union): {plural_message.locations}')
        print(f'  user comments (ordered merge): {plural_message.user_comments}')

    for context in ('button', 'menu'):
        message = merged.get('Open', context=context)
        print(f"  msgctxt={context!r} msgid='Open' -> {message.string!r}")

    print()
    print(f'{len(conflicts)} conflict(s); records:')
    for conflict in conflicts:
        print(json.dumps(conflict, ensure_ascii=False, indent=2, sort_keys=True))

    print()
    print(f'Merged catalog written to: {merged_path}')
    print(f'Conflict records written to: {conflicts_path}')
    return 1 if conflicts else 0


if __name__ == '__main__':
    raise SystemExit(main())
