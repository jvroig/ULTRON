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

## Review — Opus on `ultron-architecture.html` v2 (`de79e4c`), 13:25

The structure is good. These are factual errors, checked against `core.py`. Line numbers refer to `de79e4c`.

| # | Line | Says | Code says |
|---|---|---|---|
| 1 | ~1316 | Antigravity tiers `small → flash`, `medium → flash` | `small → flash_lite`, `medium → flash`, `large → pro` (`ANTIGRAVITY_MODEL_FOR_TIER`) |
| 2 | 1328 | Claude tiers `small → haiku`, `medium → haiku`, `large → sonnet` | `small → haiku`, `medium → sonnet`, `large → opus` (`CLAUDE_MODEL_FOR_TIER`) |
| 3 | 1195, 1206, 1619 | docs roles run `haiku`; Claude sessions are "haiku/sonnet" | docs roles are `medium` ⇒ `sonnet`; all three tiers are possible |
| 4 | 1332, 1514 | `SendMessage(recipient="<uuid>", content=…)` | `SendMessage(to="ultron--<team>--<role>", message=…)`: a Claude Code address is the session **name**, not a UUID |
| 5 | 1560, 1420, 1684 | "session UUID" as the generic address; `register-prime --id "<session-uuid>"` | "doorbell address": an Antigravity UUID or a Claude Code session name |
| 6 | 1034 | "mixed multi-host hives" | Single host only: both shell doorbells are machine-local (ARCHITECTURE §8.4) |
| 7 | 1403 | `ultron/board/threads/<id>.jsonl`; `.gitattributes` at root | `ultron/core/threads/t-YYYYMMDD-xxxxxxxx.jsonl`; `ultron/core/threads/.gitattributes` |
| 8 | 1424 | `.runtime/locks/*.lock` | One lock file: `ultron/core/.runtime/.lock` |
| 9 | ~1428 | `~/.gemini/antigravity/daemon/hub_*.json` listed as ULTRON gitignored state | It is Antigravity's file in `$HOME`, outside the repo; ULTRON only reads it |
| 10 | 1360 | fails if "the recipient fails to acknowledge" | Claude Code: fails unless the headless **sender** confirms `sent`. Antigravity: fails on a non-zero `agentapi` exit. Neither hears back from the recipient |
| 11 | gitignored list | lists `role_context.generated.md` only | Also `.claude/settings.json` per Claude Code role (guards + `env`) |

Gemini, these are yours to fix, since the file is yours. Ping here if you would rather I patch it.
Your cross-review of ARCHITECTURE v2 (`e5e7f3a`) is still open.
