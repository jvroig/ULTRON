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

---

## Execution Report — Gemini (2026-11-10 14:24)

1. **Pruning Executed:**
   - Removed 46 files: `ultron/hive/docs/` (21 files), `ultron/hive/feature-export/` (16 files), and `ultron/core/threads/t-*.jsonl` (9 files).
   - Preserved `ultron/hive/.gitkeep` and `ultron/core/threads/.gitattributes`.
2. **Local Session Healing:**
   - `python3 ultron/core/core.py verify --prune-orphans` pruned all 9 removed roles from local `.runtime/sessions.json`.
3. **Automated Test Suite:**
   - Ran `python3 -W error -m unittest discover -s tests -v`: **64/64 tests passing** in 10.69s.
4. **Fresh Clone Zero-State Verification (`/tmp/ultron-virgin-test`):**
   - `verify`: `[ULTRON] Integrity Verified: 0 team(s), 0 role(s), 0 JSONL thread(s) (0 post(s)), pruned_orphans=0, merge=union=True.`
   - `stats`: `0 active / 0 total teams`, `0 active / 0 total roles`, `0 threads`, `0 posts`.
   - `blueprints`: lists all 3 blueprints (`coding-light`, `tech-docs`, `thought-leadership`).
   - `org-tree`: `[ULTRON HIVE] ULTRON-PRIME [UNREGISTERED]` with `└── (No teams created in ultron/hive/ yet)`.
5. **Main Fast-Forward:**
   - Committed on `claude-code-test` (`bd31cd9`), fast-forwarded `main`, and pushed to `origin/main`.

