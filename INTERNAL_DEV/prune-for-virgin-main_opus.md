# Prune `main` to a virgin install: catalogue for Gemini

**Commander (2026-11-10 14:15):** a fresh clone must start with an empty hive and board; only blueprints
ship. Gemini executes; Opus catalogued. Checked against `main` @ `4c4b4a4`.

## Remove

| Path | What it is | Files |
|---|---|---|
| `ultron/hive/docs/` (includes `teams/web-viz/`) | Team that wrote ULTRON's own docs | 21 |
| `ultron/hive/feature-export/` | Team that built `export-thread` (includes `roles/spec/workspace/SPEC_EXPORT_THREAD.md`) | 16 |
| `ultron/core/threads/t-*.jsonl` | Board history of those teams | 9 |

## Keep

- `ultron/hive/.gitkeep` and `ultron/core/threads/.gitattributes` (the `merge=union` rule must ship).
- `ultron/core/blueprints/`, `templates/`, `core.py`, docs, tests, `ultron-architecture.html`.
- **Examples in docs stay.** `docs/ARCHITECTURE.md` uses `ultron/hive/docs` and `t-20261107-567656f5` in sample JSON, and
  `ultron-architecture.html` draws `docs`/`web-viz`/`feature-export` in the hive diagram. Both are illustrations
  and need no live team.

## Commander decides

- `INTERNAL_DEV/`: our dev channel, which is not product. Options: delete it from `main` (history keeps it), or
  keep it only on `claude-code-test`.

## Checks (I ran the removal locally and reverted it, so these are known)

- No test or `core.py` code path depends on the removed files. Tests pass without them.
- Before `verify`, run `python3 ultron/core/core.py verify --prune-orphans` on each machine. Each machine's gitignored
  `.runtime/sessions.json` still holds entries for the removed roles, and plain `verify` fails on those orphans.
  The prune touches only the local file.
- After the removal: in a fresh clone, `verify`, `stats` and `blueprints` work; `org-tree` is empty; tests pass.
