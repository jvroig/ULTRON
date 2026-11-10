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

## Decided (Commander, 14:20)

- `INTERNAL_DEV/` stays on `main` as it is. It is inert docs that ULTRON never reads, so it doesn't change a fresh clone.

## Checks

- **Known:** `git grep` finds no reference to the removed files in `tests/` or `core.py`. On SilverCenturion, after
  the removal, plain `verify` failed only because the local gitignored `.runtime/sessions.json` still listed the
  removed roles as orphans. Run `python3 ultron/core/core.py verify --prune-orphans` on each machine; it touches
  only that local file.
- **Not yet run (Gemini, please):** the test suite without the files, and a fresh clone where `verify`, `stats` and
  `blueprints` work and `org-tree` is empty.
