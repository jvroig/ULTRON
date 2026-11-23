# Implementation Plan: Antigravity `swarm` Support (Replacing `invoke_subagent`)

- **Date:** 2026-11-23
- **Status:** Plan finalized — awaiting Commander go-ahead to implement
- **Scope:** Migrate ULTRON's `antigravity` harness adapter (`ultron/core/core.py`) from `define_subagent` / `invoke_subagent` / `manage_subagents` to Antigravity's native `swarm` tool (`swarm`, `post_message`, `read_board`, `swarm_wait`), add `set-model` CLI support for standing teams/roles, and preserve 100% of ULTRON's Hive manifests, board threads, and bidirectional cross-harness (mixed-hive) doorbells.

**Approved Commander Decisions:**
1. **Default Antigravity tier-to-model mapping (`ANTIGRAVITY_MODEL_FOR_TIER`):**
   - `small` → `gemini-4-hydrogen-medium`
   - `medium` → `inherit` (omits `model` in `swarm(action="add")` so daily-driver workers inherit Prime's active model, e.g. Gemini 4 Neon Medium)
   - `large` → `gemini-4-argon-medium`
   - Explicit model IDs (e.g. `gemini-4-argon-high`, `gemini-4-neon-xhigh`, `claude-opus-5-5-high`) are accepted directly on `--model` and `set-model`.
2. **`set-model` CLI command:** Included in this change (`core.py set-model <team> [--role <role>] <model>`, Prime-only) to close the existing gap for updating persisted team/role models after creation.

---

## 1. Motivation & Empirical Verification

### Why Replace `invoke_subagent`
ULTRON's `AntigravityAdapter` currently spawns roles via `define_subagent` + `invoke_subagent`, whose `Model` enum is restricted to `["inherit", "flash_lite", "flash", "pro"]`. Antigravity's native `swarm` tool (`swarm(action="add", model=...)`) unlocks:
- **Full model roster & reasoning levels:** `gemini-4-argon-{low,medium,high}`, `gemini-4-neon-{low,medium,high,xhigh}`, `gemini-4-hydrogen-{low,medium,high,xhigh}`, `claude-opus-5-5-{low,medium,high}`, `claude-sonnet-5-5-{low,medium,high}`, `gemini-3.8-flash-*`, `gpt-oss-120b-medium`, etc. (discoverable live via `swarm(action="models", all=true)`).
- **Hot model switching without teardown:** `swarm(action="model", name=..., model=...)` switches a waiting worker's model mid-campaign (e.g. on quota exhaustion) while preserving its conversation history.
- **Real liveness & native UI:** `swarm(action="status")` reports `waiting` / `working` / `stopped` / `killed` directly, and renders workers in Antigravity's Swarm UI Overview.
- **Same workspace modes:** `swarm(action="add")` natively supports `inherit`, `share`, and `branch`.

### Live Verification of Cross-Harness Compatibility (2026-11-23)
A live diagnostic test was executed against a disposable `swarm` worker (`probe`, `gemini-3.8-flash-low`) to verify mixed-hive invariants before committing to replacing `invoke_subagent`:
1. **`conversation_id` returned on spawn:** `swarm(action="add")` returns `"conversation_id": "<uuid>"`, matching the worker's own `<user_information>` Conversation ID.
2. **`Claude Code → Antigravity Swarm` shell doorbell works unchanged:** `AntigravityAdapter().shell_doorbell(<uuid>, "SHELL_DOORBELL_PING")` (via `agentapi send-message`) delivered a `SYSTEM_MESSAGE` wake-up to the swarm worker immediately.
3. **`Antigravity Swarm → Claude Code` shell doorbell works unchanged:** Swarm workers have `run_command`, so `python3 ultron/core/core.py doorbell <target> "<msg>" --from <you>` works identically.
4. **Intra-swarm doorbell nuance (key finding):** Swarm workers do **not** have the `send_message` tool declared in their tool list. They wake peers (and Prime) via `post_message(text="@<roster-name> ...")` (or `@coordinator` for Prime) on the shared swarm board. Prime can wake workers via either `post_message` (`@<roster-name>`) or `send_message(Recipient=<uuid>)`.

Because cross-harness doorbells work bidirectionally with zero regressions, maintaining a parallel `invoke_subagent` adapter adds unnecessary complexity. Replacing `invoke_subagent` directly in `AntigravityAdapter` is the cleanest path.

---

## 2. Detailed Design

### 2.1 Deterministic Swarm Roster Naming (`swarm_name_for`)
Antigravity's `swarm(action="add")` requires worker `name` to:
- Match `^[a-z0-9][a-z0-9_-]{0,23}$` (lowercase, max **24 characters**)
- Not equal `all`, `coordinator`, or start with `coordinator-`

**Design:** Add `swarm_name_for(agent_id: str) -> str` in `ultron/core/core.py`:
- For `agent_id == PRIME_ID` (`"ultron-prime"`): return `"coordinator"`.
- For `<team_slug>/<role_slug>`:
  - Candidate: `base = f"{team_slug}-{role_slug}"`.
  - Reserved guard: if `base in {"all", "coordinator"}` or `base.startswith("coordinator-")`, prefix with `u-` (e.g. `u-{base}`).
  - Length guard: if `len(base) <= 24`, return `base` verbatim (readable: e.g. `xcom-dev-lead`, `xcom-dev-coder`).
  - If `len(base) > 24`: compute a deterministic 4-hex SHA-256 suffix of `agent_id`: `digest = hashlib.sha256(agent_id.encode("utf-8")).hexdigest()[:4]`, and return `f"{base[:19].rstrip('-_')}-{digest}"` (always `<= 24` chars, collision-resistant, and deterministic).
- Because `swarm_name_for(agent_id)` is pure and deterministic:
  - `render_spawn`, `spawn-team`, `stop-team`, `liveness`, `whois`, and `directory` always agree on a role's `@<swarm_name>` without requiring extra flags on `activate-team`.
  - `activate-team` will also record `"swarm_name": swarm_name_for(agent_id)` in `.runtime/sessions.json` when `harness == "antigravity"` for explicit introspection.

### 2.2 File-Based Role Context Delivery (Short Public `brief`)
Unlike `define_subagent(SystemPrompt=...)`, `swarm(action="add", brief=...)` posts `brief` publicly onto the shared swarm message board where every swarm worker can read it. Dumping full charters into `brief` would bloat every worker's context across teams.

**Design:** Adopt the same `role_context.generated.md` pattern already used by `ClaudeCodeAdapter` (and already gitignored at `.gitignore:9`):
1. `AntigravityAdapter.build_spec()` renders the full role context (`self.render_role_context(core, ctx)`) and stores it in `spec["role_context"]` along with `spec["role_context_path"] = str(role_dir / ROLE_CONTEXT_FILENAME)`.
2. `AntigravityAdapter.spawn()` writes `<role_dir>/role_context.generated.md` for every role in the team before returning the launch plan (just like `ClaudeCodeAdapter.spawn()` writes it before launching `claude --bg`).
3. `spec["swarm_add"]["brief"]` stays concise (~8–12 lines):
   - Role identity (`agent_id`, `role`, `team`, `swarm_name`, and `target_repo_abs` if set)
   - Mandatory first action: `read_file` on `<abs_path>/role_context.generated.md` to load full charter, inherited charters, project decisions, read-only constraints, and routing rules
   - Startup hydration commands (`list --as <aid> --visibility personal|team|global`, `directory <aid>`)
   - Explicit governance guard: *"Only ULTRON PRIME spawns or stops agents — never call `swarm(action='add')` or `swarm(action='kill')`."*
   - Mission brief (if supplied) and instruction to report readiness to `@coordinator` via `post_message`, then end turn (`swarm_wait`).

### 2.3 Flexible Model Tiers + Explicit Model ID Pass-Through
Currently `normalize_model()` in `ultron/core/core.py:136` rejects anything outside `VALID_MODELS = {"inherit", "small", "medium", "large"}` (plus legacy aliases `flash_lite`/`flash`/`pro`).

**Design:**
- Keep canonical tiers (`small`, `medium`, `large`, `inherit`) and legacy aliases (`flash_lite`, `flash`, `pro`) fully supported for portability across blueprints and harnesses.
- Extend `normalize_model(value, source="")` to also accept explicit model IDs matching `MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")` (rejecting whitespace, uppercase after `.lower()`, shell metacharacters, or empty strings).
- Add a small helper `resolve_antigravity_model(model: str) -> Optional[str]`:
  - `"inherit"` → `None` (omit `model` key from `swarm_add` so `swarm` uses Prime's active model).
  - Canonical tier (`small` / `medium` / `large`) → look up `ANTIGRAVITY_MODEL_FOR_TIER[tier]` (returning `None` if mapped to `"inherit"`).
  - Any other validated explicit model ID (e.g. `gemini-4-argon-high`, `gemini-4-neon-medium`, `claude-opus-5-5-high`) → return verbatim as `swarm_add["model"]`.
- **Tier defaults (`ANTIGRAVITY_MODEL_FOR_TIER`):**
  - `"small": "gemini-4-hydrogen-medium"`
  - `"medium": "inherit"` (omits `"model"` in `swarm_add`)
  - `"large": "gemini-4-argon-medium"`
- Update `ClaudeCodeAdapter` model resolution gracefully: canonical tiers still map via `CLAUDE_MODEL_FOR_TIER` (`haiku`/`sonnet`/`opus`), `"inherit"` maps to `""`, and explicit IDs pass through to `--model` unchanged.
- **New `set-model` CLI command (Prime-only, added to `PRIME_ONLY_COMMANDS`):**
  - `python3 ultron/core/core.py set-model <team> <model>` → validates `<model>` via `normalize_model()` and atomically updates `default_model` + `updated_at` in `team.json` (roles without an explicit override inherit the new default; optionally also supports `--role <role>` to update `model` + `updated_at` in `roles/<role>/role.json`).
  - Takes effect on the next `render-spawn` / `spawn-team` (and Prime can hot-switch an already-running worker immediately via `swarm(action="model", ...)`).

### 2.4 Doorbell & Directory Updates
- **`HARNESS_TOOLS["antigravity"]["doorbell"]`**: change `"send_message"` → `"post_message"`.
- **`AntigravityAdapter.doorbell_address(ctx)`**:
  `f"@{swarm_name_for(ctx['agent_id'])} (swarm board) / conversation UUID bound by activate-team (cross-harness)"`
- **`AntigravityAdapter.doorbell_call()`**:
  `'call `post_message(text="@<swarm_name> Doorbell: Posted on Thread <thread_id> (\'Title\')...")` (use `@coordinator` for `ultron-prime`)'`
- **`whois` (`core.py:5657`)**:
  - Keep `whois <agent_id> --id-only` returning `conversation_id` for backwards compatibility with existing scripts and `agentapi` UUID lookups.
  - Add `--swarm-name` flag to `whois` (prints `@<swarm_name>`, or `@coordinator` for `ultron-prime`, when the target is on `antigravity`).
  - Print `Swarm Name:      @<swarm_name>` in default human `whois` output and include `"swarm_name"` in `--json` output (and in `directory` entries).
- **`role_context.md.tmpl` (`ultron/core/templates/role_context.md.tmpl`)**:
  - Update line 39 so Antigravity roles resolve `@<swarm_name>` cleanly (via `directory` or `whois <target> --swarm-name`) for intra-swarm `post_message`, while continuing to use `core.py doorbell <target> "<msg>" --from <agent_id>` for cross-harness targets (parent/child teams or Prime on another harness).
  - Update line 52 (`Never Poll`): compatible with `post_message` / `swarm_wait` (ending turn after `post_message` parks the worker cleanly).

### 2.5 `AntigravityAdapter` Lifecycle Methods (`core.py:365-530`)
1. **`build_spec()`**:
   - Returns:
     ```python
     {
         "agent_id": aid,
         "team_slug": clean_team,
         "role": r_slug,
         "swarm_name": s_name,
         "read_only_mode": ctx["read_only"],
         "target_repo": ctx["target_repo"],
         "target_repo_abs": repo_abs,
         "role_context_path": str(role_dir / ROLE_CONTEXT_FILENAME),
         "role_context": system_prompt,
         "swarm_add": {
             "action": "add",
             "name": s_name,
             "workspace": team["workspace_mode"],
             "brief": short_brief,
             # "model": resolved_model  (included only when resolved_model is not None)
         },
     }
     ```
2. **`spawn()`**:
   - Writes `<role_dir>/role_context.generated.md` for each spec.
   - Returns `next_steps`:
     - Optional `swarm(action="title", title=f"ULTRON: {team['slug']}")`
     - For each spec: `swarm(**spec["swarm_add"])`
     - Bind returned `conversation_id` UUIDs: `activate-team <team> --uuids '{"<role>": "<uuid>", ...}'`
     - Arm Safety Cron (`schedule`, e.g. `'*/10 * * * *'`) and commit & push `ultron/hive/` and `ultron/core/threads/`.
3. **`stop()`**:
   - Computes `swarm_names_to_kill = [swarm_name_for(a["agent_id"]) for a in plan["agents_to_kill"]]`.
   - Includes `"swarm_names_to_kill": swarm_names_to_kill` in the returned plan dict.
   - Returns `next_steps`:
     - Kill each worker: `swarm(action="kill", name="<swarm_name>")` for each name in `swarm_names_to_kill`
     - `disable-team <team>[--cascade]`
     - Commit & push `ultron/hive/` and `ultron/core/threads/` (and cancel Safety Cron if no active teams remain).
4. **`probe()`**:
   - Lists expected `swarm_names = sorted(swarm_name_for(aid) for aid in agents)`.
   - Returns `next_steps`:
     - `swarm(action="status") and verify these workers are waiting/working (not stopped/killed): <swarm_names>`
     - Checkpoint ULTRON HQ board/hive updates to git.
5. **`render-spawn` human CLI formatter (`core.py:5506-5520`)**:
   - Print `SPAWN SPEC FOR: <agent_id> (swarm=@<swarm_name>)`, `Model=<model or inherit> | Workspace=<ws> | ContextFile=<path>`, followed by `s["role_context"]` and `s["swarm_add"]["brief"]`.

---

## 3. Files to Modify

| File | Summary of Changes |
|---|---|
| `ultron/core/core.py` | Add `swarm_name_for()`, update `ANTIGRAVITY_MODEL_FOR_TIER`, `HARNESS_TOOLS["antigravity"]`, `normalize_model()`, `AntigravityAdapter` (`build_spec`, `spawn`, `stop`, `probe`, `doorbell_address`, `doorbell_call`), `activate_team` (`swarm_name` recording), `whois` (`--swarm-name` + display), `directory` (`swarm_name` field), `render-spawn` CLI output, and `set-model` CLI command (added to `PRIME_ONLY_COMMANDS`). |
| `ultron/core/templates/role_context.md.tmpl` | Make line 39 (`Doorbell`) harness-clean via `{{DOORBELL_RESOLVE}}` or clear intra-swarm vs cross-harness phrasing. |
| `ultron/core/ULTRON_PRIME.md` | Replace `manage_subagents(Action="list")` with `swarm(action="status")`; document `swarm(action="model")` hot model switching on quota limits, `swarm(action="models", all=true)`, and explicit `--model <model_id>` support. |
| `docs/HARNESSES.md` | Update Actions table and Antigravity requirements section (`swarm` spawn/stop/liveness, `post_message` intra-swarm doorbell, `agentapi` cross-harness doorbell, model tier mapping + explicit model IDs). |
| `docs/ARCHITECTURE.md` | Update §7.2 / §8 references from `define_subagent` / `invoke_subagent` / `manage_subagents` to `swarm` + `role_context.generated.md`. |
| `tests/golden/render_spawn_antigravity.json` | Regenerate golden snapshot for the new `swarm_add` + `role_context` schema. |
| `tests/test_ultron_core.py` | Update existing Antigravity spec assertions (`define_subagent`/`invoke_subagent` → `swarm_add`/`role_context`) and add new unit tests (Section 4). |

---

## 4. Verification & Test Plan

1. **Automated Test Suite (`python3 -W error -m unittest discover -s tests`):**
   - **Unit tests for `swarm_name_for()`:**
     - `ultron-prime` → `coordinator`
     - Short `<team>/<role>` (`api/coder` → `api-coder`)
     - Long `<team>/<role>` (>24 chars) → deterministic truncation + 4-char SHA-256 suffix, always `<= 24` chars and matching `^[a-z0-9][a-z0-9_-]{0,23}$`
     - Reserved prefix collision (`coordinator/lead` → `u-coordinator-lead`, never `coordinator-*` or `all`)
   - **Unit tests for `normalize_model()`, `set-model`, & model resolution:**
     - Canonical tiers (`small`, `medium`, `large`, `inherit`) and legacy aliases (`flash_lite`, `flash`, `pro`)
     - Explicit model IDs (`gemini-4-argon-high`, `gemini-4-neon-medium`, `claude-opus-5-5-high`, `gpt-oss-120b-medium`)
     - Rejection of invalid/unsafe strings (spaces, `;`, `$(...)`, empty string, >64 chars)
     - `small` → `gemini-4-hydrogen-medium`, `medium` / `inherit` omits `"model"` from `swarm_add`, `large` → `gemini-4-argon-medium`, and explicit IDs pass through verbatim
     - `set-model` updates `team.json` (`default_model`) or `roles/<role>/role.json` (`model`), rejects unknown team/role or invalid model, and is enforced as Prime-only
   - **Unit tests for `AntigravityAdapter`:**
     - `spawn()` writes `<role_dir>/role_context.generated.md` and returns `swarm_add` specs
     - `swarm_add["brief"]` is concise and does NOT inline the full charter, while `role_context.generated.md` contains the full charter, inherited charters, `[READ-ONLY ROLE MODE]`, target repo dual-directory rule, and project decisions
     - `stop()` returns `swarm_names_to_kill` and `swarm(action="kill", ...)` next steps
     - `probe()` returns `swarm(action="status")` next steps with expected `swarm_names`
     - `whois --swarm-name` and `directory` expose `swarm_name` alongside `conversation_id`
     - Existing `shell_doorbell` / mixed-hive tests remain green
   - **Golden fixture verification:** `tests/golden/render_spawn_antigravity.json` matches `render_spawn_fixture.py` output.
2. **Live Smoke Test (Post-Implementation):**
   - Spawn a 2-role test team on Antigravity via `core.py spawn-team`, execute the emitted `swarm(action="add", ...)` calls with explicit models (e.g. `gemini-4-argon-medium` + `gemini-3.8-flash-low`), bind UUIDs with `activate-team`, verify intra-swarm `@<swarm_name>` doorbell AND `core.py doorbell` shell delivery, inspect `swarm(action="status")`, and cleanly tear down with `stop-team` + `swarm(action="kill")` + `disable-team`.

---

## 5. Rollout & Risk Notes

- **Soft vs. hard subagent-spawn guard:** Unlike `define_subagent(EnableSubagentTools=False)`, `swarm` does not expose a tool-level flag to disable `swarm(action="add")` on workers. The `brief` and `role_context.generated.md` explicitly forbid workers from calling `swarm(action="add")` or `swarm(action="kill")` (matching how `ClaudeCodeAdapter` enforces this via charter + settings).
- **Multi-team shared swarm board:** All teams active under one Antigravity Prime share one swarm board. Keeping `brief` short (pointers to `role_context.generated.md`) and keeping substantive work on ULTRON's scoped `ultron/core/threads/*.jsonl` board (using `post_message` strictly for short `@<swarm_name> Doorbell: ...` wake-ups) prevents cross-team context bloat.
- **No breaking change to `ultron/hive/` or `ultron/core/threads/`:** Existing teams, blueprints, threads, projects, and decisions remain 100% compatible on disk.
