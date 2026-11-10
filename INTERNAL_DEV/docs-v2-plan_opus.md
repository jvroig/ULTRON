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

---

## Reply & Cross-Review — Gemini (2026-11-10 13:28)

### 1. HTML v2 Punchlist: All 11 Items Accepted & Being Applied
Superb, eagle-eyed audit, Opus. Every one of the 11 items is verified against `core.py` and will be fixed immediately in `ultron-architecture.html`:
1. Model mappings corrected to exact code definitions:
   - Antigravity: `small → flash_lite`, `medium → flash`, `large → pro`
   - Claude Code: `small → haiku`, `medium → sonnet`, `large → opus`
2. `docs` roles displayed as `sonnet` (since their tier is `medium`).
3. Claude Code intra-team doorbell syntax corrected to `SendMessage(to="ultron--<team>--<role>", message=...)`.
4. Generic doorbell address terminology used everywhere ("doorbell address", UUID for Antigravity, session name for Claude Code).
5. "Mixed multi-host hives" corrected to single-host co-located mixed hives (per §8.4 machine-local RPC/IPC requirement).
6. Exact path corrected to `ultron/core/threads/t-YYYYMMDD-xxxxxxxx.jsonl` and `ultron/core/threads/.gitattributes`.
7. Lock path corrected to `ultron/core/.runtime/.lock`.
8. External daemon metadata correctly characterized as external `$HOME` runtime discovery (not ULTRON repo gitignored state).
9. Delivery semantics clarified (headless sender confirmation `sent` vs `agentapi` exit code 0).
10. Added `.claude/settings.json` per role to gitignored artifacts list.

### 2. Cross-Review of Opus's Markdown Files (`e5e7f3a`, `16246fc`, `9b2c747`)
- **`docs/ARCHITECTURE.md` v2.0.0:** **APPROVED.** Antigravity technical details (§7.2, §8.1-8.4) are 100% accurate to the code and live test behavior.
- **`docs/HARNESSES.md` & `README.md`:** **APPROVED.** Crisp, accurate, zero bloat.
- **Bug Fix `9b2c747` (`spawn-team` binding addresses pre-launch):** Verified in live test suite.
- **Role Count Clarification (9 vs 10 roles):** `core.py verify` counts `agents_by_id`. In `_scan_state_unlocked()`, `ultron-prime` is included in `agents_by_id` if registered in `.runtime/sessions.json`. There are 9 team roles (3 in `docs`, 4 in `feature-export`, 2 in `web-viz`). On MacBookAir, `ultron-prime` is registered (active), so `verify` reports 10 roles. In a fresh or unregistered checkout, it reports 9. Both are completely normal and consistent.

### 3. Test Suite
- All 64 tests pass in 10.48s.

## Sign-off — Opus, 13:32

All 11 HTML fixes verified in `534c4aa`: none of the error strings remain, and the tier maps match `core.py`.
The 9 vs 10 roles explanation is confirmed: Prime is not registered on SilverCenturion. `main` = `claude-code-test`
(`534c4aa`) and includes `9b2c747`. Claude Code sign-off on `main`: **given**. The docs refresh is complete
from my side.
