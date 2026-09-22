# Three-way PO catalog merge demo

This directory contains a worked example for
`babel.messages.catalog.merge_catalogs(base, local, incoming)`.

## Files

- `base.po` -- the common ancestor translation branch.
- `local.po` -- the "ours" branch (wins conflicts).
- `incoming.po` -- the "theirs" branch.
- `merge_demo.py` -- runs the merge, writes `out/merged.po` and
  `out/conflicts.json`, prints the merged plural slots and conflict records,
  and exits non-zero when conflicts were found.

## Run

```sh
python demo/merge/merge_demo.py
```

The run is quick (well under 90 seconds) and repeatable; outputs are
overwritten in `demo/merge/out/`.

## Scenarios covered

- Same `msgid` with different `msgctxt` values ("Open" / button / menu).
- Two plural slots changed on different branches: the merged PO keeps both
  changes independently.
- A translation conflict on "Hello": the local value is kept and the conflict
  record contains the base/local/incoming values.
- A single-sided deletion ("Removed on local"): merged without conflict.
- Delete-vs-modify ("Legacy"): local deleted it, incoming modified it; the
  local deletion is kept and a conflict is recorded.
- Unicode translations ("Öffnen", "Auf Wiedersehen").
- An obsolete message ("Ancient") resurrected on exactly one branch.
- Stable location deduplication and ordered user-comment merging on the
  plural message.
- The `fuzzy` flag is preserved (never auto-removed).

