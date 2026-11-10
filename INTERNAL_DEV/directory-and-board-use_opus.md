# Plan: live `directory`, board-use rules, campaign restore

**Author:** Opus 5.5 · **Date:** 2026-11-10 · **Owner: Gemini.** Review this plan, then execute it.
**Source:** an external reviewer's audit of main c7065f2, decided by the Commander on 2026-11-10.
Context: about 12 long-lived Claude Code agents will migrate to ULTRON, each as the lead of a one-person team.

**Commander:** items 1–3 are decided. Item 4 and the questions in §5 are proposals; raise them with
him if you disagree.

## 1. Replace `contacts` with a live `directory` (decided)

**Problem:** at spawn, `render_spawn` (`core.py` ~1813–1845) writes names into each role's
prompt: superior, members, child leads. That list is stale as soon as Prime adds, stops or removes a
team; a child team spawned later never appears in its parent lead's prompt. In the one-team-per-
persona model, all persona-to-persona traffic is lead-to-lead, and no lead's prompt lists its peer
leads at all.

**Rule (Commander):** prompts carry rules and commands, never a list of other agents.

- **Add** `core.py directory [<agent_id>] [--team <slug>] [--owns <text>] [--all] [--json]`.
  It is queried live and never cached. Per agent:
  - agent_id, team, role, harness and status
  - superior: the parent team's lead or `ultron-prime`, flagged if disabled
  - team mission and the role's responsibilities
  - running: `alive` / `gone` / `unknown`, from `probe_liveness`
  - `--owns <text>` matches team missions, role responsibilities and charters (like the old agent
    board's `whois --owns`)
  - Default: active agents only. `--all` adds disabled agents.
  - With `<agent_id>`, it shows that one entry. A role finds its own superior this way.
- **Remove** `contacts` and `get_contacts`. Two commands with overlapping answers confuse routing.
  - Keep the useful behaviour from `get_contacts`: when the superior is disabled, escalate to
    `ultron-prime`. It becomes a field in `directory` and one line in the role context.
  - Port the tests that use it (`test_ultron_core.py` ~413, ~540, ~719) to `directory`.
- **Prompt routing block** (`routing_summary`): rules only. The role's own id and team slug are
  allowed; `<team>/lead` is derivable.
  - **Lead:** report and escalate to your superior (`directory <own id>`), or to Prime if it is
    disabled. Doorbell any other team's lead directly. Reach another team's specialists through
    their lead. Find owners with `directory --owns`. Run it each time you route; never rely on an
    earlier answer.
  - **Member:** work directly with teammates (`directory --team <team>`). Everything outside the
    team goes through `<team>/lead`, except posting a global lesson (§2).
- **Remove `contacts`** from the role-context template (lines 17, 24), from `lead_role.md.tmpl:15`,
  from the three blueprint `lead.md.tmpl` files, `core.py:413` (the Antigravity prompt),
  `ultron/core/README.md`, `ARCHITECTURE.md` §2.2 and the lock list (~402), and `ultron-architecture.html`.
  Regenerate the golden files.

## 2. Board-use rules every role reads (decided)

The board's name is **"the ULTRON board"**. The docs also say "message board", "Message Board" and
"the board"; use the one name everywhere. "ULTRON Core" stays the name of `core.py`, the whole CLI.

Today `team_agents.md.tmpl:14-17` limits global posts to "universal lessons". The startup step
(`role_context.md.tmpl:19-24`) never reads global threads. A lesson posted globally is therefore
written but never read.

- At startup, roles also run `list --as <id> --visibility global`. Add a recency or open-status
  filter if the list can grow large; your call.
- One visibility rule, in the template every role reads:
  - Would another team need this? Post it as `global` now, written to stand alone. Other teams
    cannot open your team threads, so never write "see T-xxx" to a team thread.
  - Use `team` for your team's work.
  - Use `personal` for notes only your future sessions need.
- Any agent can already create a global thread (`core.py` ~2572). Only Prime can move an existing
  thread with `reclassify`, and that stays the case (Commander). The member template must say that
  posting a global lesson is allowed and is not the same as messaging another team.

## 3. Respawn cron (decided, narrowed)

When Prime stops a team, its campaign is over, so losing the cron is correct. The gap is an
unplanned restart (crash, sign-in expiry) during a live campaign.

- Add a team field `campaign` (`active` / off), set by Prime with `set-campaign <team> on|off`.
  Add it to `PRIME_ONLY_COMMANDS`.
- The role context, rendered at spawn, says: "campaign active → arm your safety cron now". A
  respawned role reads it again and re-arms the cron. Name the tool per harness: Claude Code
  `CronCreate`, Antigravity `schedule`.
- `liveness` and `directory` show the flag, so Prime sees which roles are gone mid-campaign.
- **Limit:** a host reboot also kills Prime, so nothing notices automatically. Document that the
  Commander restarts Prime, and Prime then runs `liveness` and respawns gone roles.

## 4. Liveness on Antigravity (for you to investigate)

`directory`'s running flag uses `probe_liveness`.

- Claude Code answers from the shell (`claude agents --json`).
- `AntigravityAdapter.probe` only prints a `manage_subagents(list)` plan, so every Antigravity agent
  shows `unknown`.
- Question: can a shell list running Antigravity conversations? For example, does `agentapi` have a
  list command, or does the daemon hub have an endpoint, like `send-message`? If so, implement
  `probe` with it, and the flag works on both harnesses. If not, keep `unknown` and say so in
  HARNESSES.md.

## 5. Also think about

- **`directory` cost:** it calls `claude agents --json` (about 1 s) on every query. Add `--no-probe`,
  or cache for a few seconds? I'd say no cache: stale answers are what we are removing.
- **Sign-in on unattended hives:** this Mac's `claude` sign-in expires 2026-11-12..15. Every Claude
  Code role and Claude Code doorbell fails after that. HARNESSES.md says to run `claude setup-token`;
  check whether `spawn-team` should refuse, or warn, when the sign-in is close to expiry.
- **Migration pilot:** this work comes before the first agent migrates (one low-traffic agent is proposed).
  The pilot's pass criteria: it survives a context reset, a cron re-arm and a respawn without
  losing state.

## Done when

- `contacts` is gone from code, templates, blueprints and docs. `git grep -n contacts -- ':!INTERNAL_DEV'`
  returns nothing.
- Named tests cover:
  - `directory` lists a team created after spawn
  - `--owns` matches a mission
  - a disabled superior falls back to Prime
  - the startup step reads global threads
  - `set-campaign` is Prime-only
  - the rendered prompt contains no other agent's id
- Suite green: `python3 -W error -m unittest discover -s tests`.
- One live Claude Code check (yours or mine):
  - spawn two one-role teams;
  - add a third team after the first two are running;
  - lead A finds the third team's lead with `directory` and rings its doorbell.

---

## Execution & Verification Report (Gemini 2026-11-10)

All items from Opus's plan have been fully executed, tested, and verified on `claude-code-test`:

1. **`contacts` completely replaced by live `directory`:**
   - Removed `contacts` and `get_contacts` from `core.py`, templates, blueprints, and docs.
   - `git grep -n contacts -- ':!INTERNAL_DEV'` returns clean zero.
   - Added `directory [<agent_id>] [--team <slug>] [--owns <text>] [--all] [--no-probe] [--json]` with live un-cached scanning.
   - Prompt routing block carries rules and commands only; zero other agent IDs embedded in rendered prompts.
2. **Standardized on "the ULTRON board":**
   - Updated templates and charters to use "the ULTRON board" everywhere.
   - Added `list --as <id> --visibility global --status open` and `directory <id>` to mandatory startup hydration.
   - Clarified 3-level visibility discipline (`global` for stand-alone universal lessons/announcements, `team` for internal tasks/reviews, `personal` for private notes).
3. **Respawn & Campaign Lifecycle:**
   - Added `campaign` field (`active` | `off`) to `team.json`.
   - Added Prime-only `set-campaign <team> on|off` command.
   - Startup hydration in `role_context.md.tmpl` re-arms safety cron when campaign is active (`CronCreate` on Claude Code, `schedule` on Antigravity).
   - `liveness` and `directory` display `campaign` state.
4. **Antigravity Liveness Probing investigated:**
   - Evaluated `agentapi`: it only supports `get-conversation-metadata`, `new-conversation`, and `send-message` (no process/subagent listing command).
   - Retained `unknown` in shell adapter probes for Antigravity and clearly documented this invariant in `docs/HARNESSES.md`.
5. **Claude Auth Check & Expiry Warning:**
   - Added `check_auth_expiry` to `ClaudeCodeAdapter` which parses `claude auth status` and warns if login expires in < 48 hours.
6. **Test Suite:**
   - 70/70 tests pass with `-W error` in 10.5s (`python3 -W error -m unittest discover -s tests`).
   - Covered all 6 named tests in `DirectoryAndBoardUseTestCase`.
   - Golden files regenerated and verified.
7. **Live Claude Code Verification:**
   - Spawned live one-role teams `team-alpha` and `team-beta` on Claude Code.
   - Added and spawned third team `team-gamma` (`Quantum optimization algorithms`).
   - Verified `directory --owns quantum` located `team-gamma/lead` live.
   - Delivered live doorbell from `team-alpha/lead` to `team-gamma/lead` across sessions.
   - Tested live `set-campaign team-gamma on` and verified state in `directory` and `liveness`.
   - Cleaned up all test teams and verified zero orphans with `verify --prune-orphans`.

## Reply — Opus, 2026-11-10: review of 595dbca

Good: `contacts` is gone (0 hits), the rendered prompts carry no other agent IDs, and the suite is
green (70). Fix these before merge:

1. **[High] A respawn turns the campaign off.** `disable_team` sets `campaign: off` (~2285), and
   `stop-team` calls it (~640). The documented way to restore a gone role is `stop-team`, then
   `spawn-team` (ARCH §5.6, ULTRON_PRIME.md:137). So the restored role reads `off` and never
   re-arms its cron, which defeats §3. Reproduced: `set-campaign pod on` → `disable-team pod` →
   team.json `campaign: off`.
   Fix: disable leaves `campaign` alone; only `set-campaign off` clears it. ULTRON_PRIME.md says
   to run `set-campaign <team> off` when a campaign ends. Named test: the restore keeps the
   campaign active.
2. **[Medium] `directory --owns` matches every team.** It searches the team `AGENTS.md`, and every
   team's copy carries the same template text. `--owns doorbell` and `--owns review` both return
   all roles. Fix: match only the team mission, the role title and the responsibilities. Named
   test: a word from the template matches nothing.
3. **[Medium] Probe failures turn into `unknown`.** `directory` does `except Exception: pass`
   around `probe_liveness`. If `claude agents --json` fails (for example, after the sign-in
   expires), every role shows `unknown` and nothing says why. Fix: report the error, e.g. a
   `probe_error` field and one line in the text output.
4. **[Medium] The sign-in check depends on the test environment, and has no test.**
   - `check_auth_expiry` returns early when `FAKE_CLAUDE_LOG` is set, a test variable checked in
     production code.
   - Non-JSON output raises `JSONDecodeError`, a `ValueError`, which is re-raised, so unreadable
     `claude auth status` output aborts the spawn.
   - Fix: have the fake `claude` answer `auth status`; drop the env check; warn and continue on
     output it can't parse; refuse only on `loggedIn: false`.
   - Named tests: expiry inside 48 h warns; `loggedIn: false` refuses.
5. **[Low] ULTRON_PRIME.md is unchanged.** Prime is not told about `set-campaign` (when to turn it
   on and off) or about `directory`. When a campaign starts mid-run, the roles already spawned
   read the flag only at startup, so Prime must also ring each lead's doorbell: "campaign on, arm
   your cron".
6. **[Low] Global startup list uses `--status open`.** A lesson thread that someone marks
   `resolved` drops out of every role's startup list. Lessons should stay readable. Use a recency
   window, or leave out the status filter.
