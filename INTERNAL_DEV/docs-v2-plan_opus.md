# Docs refresh + Architecture v2 — work split

**Commander (2026-11-10 13:06):** "Work with Gemini to make sure all docs are updated, including making an
architecture v2 doc."

## Split

| Owner | Work |
|---|---|
| **Opus** | `docs/ARCHITECTURE.md` → **v2.0.0**, rewritten in place (links keep working; v1 stays in git history). Covers the harness adapters, mixed hives, the shell doorbell, liveness, the role guard, and the per-role settings/env. |
| **Opus** | Audit and fix every other Markdown doc: `README.md`, `AGENTS.md`, `ultron/core/README.md`, `ULTRON_PRIME.md`, `docs/HARNESSES.md`, blueprint and hive charters. |
| **Gemini** | `ultron-architecture.html` → v2 (the visual showcase; currently Antigravity-only). Must show both harnesses, the mixed hive, and the shell doorbell. |
| **Both** | Cross-review: Gemini checks Antigravity accuracy in my files; I check Claude Code accuracy in the HTML. Findings go in this file. |

## Ground rules

- **Facts come from the code:** `core.py` and the tests. A claim no test or code path backs gets cut or verified.
- **Terse.** No counts, versions or file lists in prose unless a test asserts them.
- **One commit per file family.** The subject names the reader, e.g. `docs: Gemini — ...`.

I'm starting on ARCHITECTURE v2 now. Gemini, please start the HTML.
