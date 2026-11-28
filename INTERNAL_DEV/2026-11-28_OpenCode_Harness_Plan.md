# Architecture & Implementation Plan: OpenCode Harness Support (`opencode`)

- **Date:** 2026-11-28
- **Status:** Plan Finalized (All 3 Commander Decisions Locked) — ready for implementation on Commander go-ahead
- **Target Harness:** `opencode` (OpenCode `1.19.6+`, third first-class `HarnessAdapter` alongside `antigravity` and `claude-code`)
- **Goal:** Enable ULTRON Hive teams (and mixed hives) to run on **OpenCode**, unlocking local GPU / subscription-free models (vLLM, Ollama, llama.cpp, LM Studio, OpenAI-compatible endpoints) as well as BYOK providers — either mixed with paid Antigravity/Claude Code teams or as a 100% locally-hosted ULTRON Hive on multi-GPU servers.

---

**Commander Decisions:**
1. **Daemon Management Mode (LOCKED — Option A: Connect-Only):**
   - `OpenCodeAdapter` is strictly **connect-only**: it connects to a running `opencode serve` at `ULTRON_OPENCODE_URL` (default `http://127.0.0.1:4096`) and **fails loud** with actionable start instructions if unreachable. It never spawns or manages background daemons itself.
   - Server/daemon provisioning (starting `opencode serve` with port/config/model setup) will live as a **separate, decoupled ULTRON capability** in the future — establishing a clean modular pattern reusable across future server-backed harnesses (e.g., Pi, DeepSeekHarness) and supporting native, Docker, and remote GPU hosts identically.
2. **Model Policy & 3-Layer Separation (LOCKED — Explicit Fail-Loud):**
   - ULTRON cleanly decouples local/self-hosted model infrastructure into 3 independent layers:
     1. **Inference Server Layer (separate future module):** Optional local `llama.cpp` / `vLLM` setup (with model choice) — or omitted entirely when using an external self-hosted endpoint.
     2. **Harness Server Setup Layer (separate future module):** Optional `opencode serve` + `opencode.json` provisioning pointing at Layer 1 (local or external) — or omitted entirely when the user already has a running `opencode serve` hooked up to local or external endpoints.
     3. **Connect-Only Harness Adapter (`OpenCodeAdapter`, this work):** Connects directly to `ULTRON_OPENCODE_URL` and orchestrates ULTRON teams on it.
   - **Model resolution rules (fail loud, zero silent guessing):**
     - **Explicit `provider/model` (primary contract):** `--model <provider/model>` or `set-model <team> [--role <role>] <provider/model>` passes `{"providerID": ..., "modelID": ...}` verbatim.
     - **Explicit `inherit`:** Intentionally omits `model` on API calls so OpenCode uses the default model already configured in the target server's `opencode.json`.
     - **Generic tiers (`small` / `medium` / `large`, e.g., from blueprints):** Resolved via explicit `ULTRON_OPENCODE_MODEL_{SMALL,MEDIUM,LARGE}` env vars if set; if unset, `spawn-team` **fails loud** instructing the operator to set an explicit `provider/model` (via `set-model` / `--model`), choose `inherit`, or export `ULTRON_OPENCODE_MODEL_<TIER>`.
3. **OpenCode as ULTRON PRIME (LOCKED — Full Any-Prime Support):**
   - **Design goal:** Every supported harness must be usable as **ULTRON PRIME** (e.g., OpenCode Prime managing OpenCode + Claude Code teams, or a 100% locally-hosted OpenCode Prime + OpenCode teams on a multi-GPU server).
   - **Phase 1 (this work):**
     - `OpenCodeAdapter` supports both OpenCode worker teams (`launches_from_cli = True`) AND OpenCode as Prime via `core.py register-prime --id <ses_id> --harness opencode`.
     - Document exact OpenCode Prime boot steps in `docs/HARNESSES.md` & `ultron/core/ULTRON_PRIME.md`: attaching TUI (`opencode attach <url>`), discovering own `ses_...` ID (`opencode session list --format json` or `GET /session`), and waking OpenCode Prime on a Safety Cron via host cron/timer calling `core.py doorbell ultron-prime "Safety Cron tick..."`.
   - **Known cross-harness gap (tracked on Roadmap below):** Today `AntigravityAdapter.launches_from_cli = False` (pre-existing Antigravity constraint), so OpenCode/Claude Code Prime can doorbell existing Antigravity sessions via `agentapi send-message` but cannot CLI-spawn new Antigravity teams yet — tracked via `agentapi new-conversation` in Section 6.

---

## 1. Empirical Verification Against Live OpenCode `1.19.6` (CPU-Only Docker)

All API contracts below were verified directly against `ghcr.io/anomalyco/opencode:latest` (`v1.19.6`, OpenAPI `3.1.0`, 162 paths) in a CPU-only container (zero GPU usage):

| Capability | Verified OpenCode `1.19.6` Endpoint / Behavior |
|---|---|
| **Health check** | `GET /global/health` → `{"healthy": true, "version": "1.19.6"}` |
| **Create per-role session** | `POST /session?directory=<abs_role_dir>` with body `{"title": "ultron--<team>--<role>", "permission": [...]}` → returns `{"id": "ses_...", "directory": "<abs_role_dir>", ...}`. Verified live that **one** `opencode serve` instance hosts multiple sessions pinned to distinct role directories simultaneously. |
| **Non-blocking async wake & dispatch** | `POST /session/{sessionID}/prompt_async?directory=<abs_role_dir>` with body `{"parts": [{"type": "text", "text": "..."}], "model": {"providerID": "...", "modelID": "..."}, "variant": "...", "system": "...", "tools": {...}}` → returns immediately (non-blocking). |
| **Liveness & status** | `GET /experimental/session` (lists all sessions across directories with `id`, `directory`, `title`) + `GET /session/status?directory=<abs_role_dir>` (reports `busy` / `idle` / `retry`). |
| **Abort & teardown** | `POST /session/{sessionID}/abort?directory=<abs_role_dir>` then `DELETE /session/{sessionID}?directory=<abs_role_dir>` → `200 true`. |
| **Built-in tool IDs** | `GET /experimental/tool/ids` → `['invalid', 'question', 'bash', 'read', 'glob', 'grep', 'edit', 'write', 'task', 'webfetch', 'todowrite', 'websearch', 'skill', 'apply_patch']`. |
| **Built-in agents** | `GET /agent` → `build` (primary, default), `plan` (primary, read-only), `explore` / `general` (subagents). |
| **Hard permission rules** | `POST /session` accepts `permission: PermissionRule[]` where each rule is `{"permission": "<tool|*>", "pattern": "<glob|*>", "action": "allow"|"ask"|"deny"}` (last-match-wins). |
| **Auth** | Optional HTTP Basic Auth via `OPENCODE_SERVER_USERNAME` (default `opencode`) and `OPENCODE_SERVER_PASSWORD`. |

### Why OpenCode Fits ULTRON Exceptionally Well
1. **Zero external Python dependencies:** The entire `OpenCodeAdapter` talks to `opencode serve` using Python's stdlib `urllib.request` — keeping ULTRON 100% pure stdlib.
2. **Instant, zero-cost doorbells (`launches_from_cli = True`):** Unlike Claude Code's shell doorbell (which spawns a headless `claude -p --model haiku` LLM call per wake), waking an OpenCode session is a single sub-50ms HTTP `POST /session/{sid}/prompt_async` call — **zero extra LLM invocation** and **zero subprocess overhead**.
3. **True hard tool/permission enforcement:** `POST /session` accepts a `PermissionRuleset` array, letting ULTRON hard-deny:
   - `task` (no rogue subagent spawning — enforces "only ULTRON PRIME spawns agents")
   - `question` (never block a headless role waiting for an interactive TUI prompt)
   - `edit`, `write`, `apply_patch` on `read_only_mode=True` roles
   - Prime-only `core.py` lifecycle commands (`bash` pattern deny for `*core.py*spawn-team*`, `*core.py*stop-team*`, `*core.py*create-team*`, etc.)

---

## 2. Detailed Architecture & Design

### 2.1 Transport & Server Discovery (`OpenCodeAdapter`)
- **Server URL:** Resolved from `ULTRON_OPENCODE_URL` (default `http://127.0.0.1:4096`).
- **Auth header:** If `OPENCODE_SERVER_PASSWORD` is set in env, attach `Authorization: Basic base64(<username>:<password>)` (username defaults to `OPENCODE_SERVER_USERNAME` or `"opencode"`).
- **Preflight health check:** Before `spawn()`, `stop()`, `probe()`, or `shell_doorbell()`, check `GET /global/health` (short timeout, e.g. 5s). If unreachable, **fail loud** with an actionable message:
  > `OpenCode server not reachable at http://127.0.0.1:4096. Start it with 'opencode serve --port 4096' (or Docker: 'docker run -d -p 127.0.0.1:4096:4096 -v /path:/path ghcr.io/anomalyco/opencode serve --hostname 0.0.0.0 --port 4096'), or set ULTRON_OPENCODE_URL.`
- **Native vs. Docker path parity:**
  - **Native host install (recommended):** Host paths match 1:1 (`--target-repo`, `role_dir`, `ultron/core/core.py`).
  - **Dockerized `opencode serve`:** Mount both ULTRON HQ and any `--target-repo` at **identical absolute paths** inside the container (e.g. `-v /home/user/Dev:/home/user/Dev`), and use `--network host` (or `host.docker.internal`) so the container can reach local Ollama/vLLM servers on the host. Document this clearly in `docs/HARNESSES.md`.

### 2.2 Model Naming & `normalize_model()` Extension
OpenCode models use `provider/model` syntax, often with tags (Ollama `:32b`, `:latest`), nested slashes (OpenRouter `openrouter/qwen/qwen3-coder:free`), and optional reasoning variants (`--variant high`).

- **Extend `MODEL_ID_RE` in `ultron/core/core.py`:**
  - Current: `re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")`
  - Proposed: `re.compile(r"^[a-z0-9][a-z0-9._:/@-]{1,127}$")` (with an explicit guard rejecting `".."` path-traversal sequences, consecutive slashes `"//"`, or trailing `"/"`).
  - Still strictly rejects whitespace, shell metacharacters (`;`, `$`, `` ` ``, `&`, `|`, quotes), and empty strings.
- **Model resolution helper (`resolve_opencode_model(model: str) -> Optional[Dict[str, str]]`):**
  - `"inherit"` → `None` (explicit opt-in: omit `model` key so OpenCode uses the server's configured default model in `opencode.json`).
  - Canonical tiers (`small`, `medium`, `large`) → read `ULTRON_OPENCODE_MODEL_{SMALL,MEDIUM,LARGE}` env vars; if set, parse as `provider/model` (or `inherit`). If unset, **fail loud** at `spawn-team` with an actionable `ValueError` telling the operator to run `set-model <team> <provider/model>`, pass `--model`, set `inherit`, or export `ULTRON_OPENCODE_MODEL_<TIER>`.
  - Explicit `provider/model` string (e.g. `ollama/qwen3-coder:32b` or `vllm/qwen/qwen3-coder-30b`) → split on the **first** `/` into `{"providerID": provider, "modelID": model_id}`.
  - If an explicit non-tier model string lacks `/` when targeting OpenCode, fail loud with a clear `ValueError`: *"OpenCode explicit models must be in 'provider/model' format (e.g. 'ollama/qwen3-coder:32b')."*
- **Note on `POST /session` vs `POST /session/{id}/prompt_async` schema difference (verified live!):**
  - `POST /session` expects `model: {"providerID": ..., "id": ...}`
  - `POST /session/{id}/prompt_async` expects `model: {"providerID": ..., "modelID": ...}`
  - Catching this schema asymmetry during our live Docker test prevents a subtle 400 Bad Request bug at implementation time!

### 2.3 Role Context Delivery & Permissions
1. **Dual delivery (belt-and-suspenders):**
   - `OpenCodeAdapter.spawn()` writes `<role_dir>/role_context.generated.md` (already gitignored at `.gitignore:9`) containing the full rendered role context + inherited team & ancestor charters + role charter (just like Antigravity).
   - `POST /session/{sid}/prompt_async` ALSO passes `"system": sp["role_context"]` directly so the model receives its role identity, routing rules, and charters in the system prompt immediately without an extra file-read turn (especially valuable for smaller local models!).
2. **Hard `PermissionRuleset` on `POST /session`:**
   ```python
   rules = [
       {"permission": "*", "pattern": "*", "action": "allow"},
       {"permission": "task", "pattern": "*", "action": "deny"},      # Only ULTRON PRIME spawns agents
       {"permission": "question", "pattern": "*", "action": "deny"},  # Headless: never hang on user prompts
   ]
   if ctx["read_only"]:
       rules += [
           {"permission": "edit", "pattern": "*", "action": "deny"},
           {"permission": "write", "pattern": "*", "action": "deny"},
           {"permission": "apply_patch", "pattern": "*", "action": "deny"},
       ]
   # Prime-only CLI command guard in bash
   for cmd in ("spawn-team", "stop-team", "create-team", "remove-team", "add-role", "activate-team", "disable-team", "set-model"):
       rules.append({"permission": "bash", "pattern": f"*{cmd}*", "action": "deny"})
   ```
   *(Note: verify during implementation whether OpenCode's `bash` permission pattern matches substring `*cmd*` reliably without false positives on normal `git` / `python` commands; if needed, scope pattern to `*core.py*<cmd>*`.)*
3. **Working directory & `--target-repo`:**
   - Session is created with `?directory=<abs_role_dir>` (matching `ClaudeCodeAdapter`'s `role_paths()`).
   - `core_cmd` uses the absolute path `python3 "<ultron_root>/ultron/core/core.py"` (same as `ClaudeCodeAdapter`) so board/doorbell commands work regardless of `cwd`.
   - `target_repo_summary` gives the Dual-Directory Execution Rule (`cd "<target_repo_abs>" && ...` for builds/tests/git, absolute paths for `read`/`edit`/`write`/`grep`/`glob`).

### 2.4 Doorbell & Session Binding (`sessions.json`)
- **Doorbell address:** The OpenCode session ID (`ses_...`) returned by `POST /session`.
- **`HARNESS_TOOLS["opencode"]`:**
  ```python
  "opencode": {
      "shell": "bash", "read": "read", "write": "write", "edit": "edit",
      "grep": "grep", "find": "glob", "doorbell": "bash",
  }
  ```
- **Unified doorbell (both intra-team AND cross-harness!):**
  - OpenCode has no native inter-session messaging tool, so OpenCode roles doorbell **both** teammates and external teams using `core.py doorbell <target_agent_id> "<message>" --from <agent_id>` via `bash`!
  - `OpenCodeAdapter.doorbell_call()`:
    `'run `<core_cmd> doorbell <target_agent_id> "Doorbell: Posted on Thread <thread_id> (\'Title\')..." --from <your_agent_id>` via `bash`'`
  - `OpenCodeAdapter.shell_doorbell(address, text)` (called by `core.py doorbell` from **any** harness — Antigravity, Claude Code, or OpenCode):
    - Sends `POST /session/{address}/prompt_async` (with `?directory=<role_dir>` if recorded in `sessions.json`, and `model` if recorded) with `parts: [{"type": "text", "text": text}]`.
    - Returns immediately once HTTP `200`/`204` is received.
- **Session metadata in `.runtime/sessions.json`:**
  - Record `conversation_id: ses_id`, `session_id: ses_id`, `harness: "opencode"`, plus optional `role_dir` and `opencode_model` (so `shell_doorbell()` and `stop()` always pass the exact `?directory=` and `model` for that session!).
  - **Crucial detail:** Update `core.doorbell()` to pass the target agent's session entry (or `role_dir`/`model` context) or allow `shell_doorbell()` to look up `role_dir` cleanly. Simplest backwards-compatible approach: keep `shell_doorbell(self, address: str, text: str)` signature intact, and have `OpenCodeAdapter.shell_doorbell()` optionally accept `session_meta` OR resolve the session's `directory` from `GET /session/{address}` (which works even without extra parameters!).

### 2.5 Lifecycle Operations (`spawn`, `stop`, `probe`)
1. **`spawn(core, team, specs)` (`launches_from_cli = True`):**
   - Preflight: `GET /global/health` (fail loud if server unreachable).
   - Refuse `workspace_mode == "branch"` in Phase 1 (same as `ClaudeCodeAdapter`; can be wired to OpenCode's `/experimental/worktree` in Phase 2 once stabilized).
   - Write `<role_dir>/role_context.generated.md` for each role.
   - For each spec (lead first):
     - `POST /session?directory=<role_dir>` with `title`, `permission`, and optional `model`.
     - `POST /session/{sid}/prompt_async?directory=<role_dir>` with `system` (`role_context`), `tools` (`task: False, question: False`), optional `model`, and `parts: [{"type": "text", "text": boot_prompt}]`.
     - **Rollback on partial failure:** If any role fails to create/dispatch, `abort` + `DELETE` all already-created sessions for this team before raising `RuntimeError` (mirroring `ClaudeCodeAdapter`'s rollback guarantee!).
   - Call `core.activate_team(team["slug"], addresses, session_ids=session_ids, harness="opencode")`.
   - Return `{"harness": "opencode", "team_slug": ..., "status": "active", "sessions": [...], "next_steps": []}`.
2. **`stop(core, plan, sessions, cascade)`:**
   - For each agent in `plan["agents_to_kill"]`:
     - `POST /session/{sid}/abort?directory=<role_dir>` (best-effort; ignore 404 if already gone).
     - `DELETE /session/{sid}?directory=<role_dir>` (record any unexpected error in `stop_failures`).
   - Call `core.disable_team(plan["team_slug"], cascade=cascade)` (only if no `stop_failures`, matching `ClaudeCodeAdapter`).
3. **`probe(agents)`:**
   - Query `GET /global/health` + `GET /experimental/session` (and per-directory `GET /session/status?directory=<dir>` for busy/idle detail).
   - If the OpenCode server is unreachable, fail loud (or report all sessions `gone` with daemon-unreachable detail).
   - For each active agent: if its `session_id` exists in the server's session list, report `"alive"` (with `"busy"` / `"idle"` detail); otherwise report `"gone"`.

### 2.6 Safety Heartbeat & Harness Auto-Detection
- **Safety Cron (`cron_tool`):** OpenCode has no built-in recurring cron tool (`cron_tool = "none — monitored by ULTRON PRIME's Safety Cron"`). Update `role_context.md.tmpl` / `OpenCodeAdapter` so OpenCode roles don't try to call a nonexistent cron tool; Prime's Safety Cron handles liveness checks and unblocking via `core.py liveness` + `core.py doorbell`.
- **Auto-detection (`detect_harness()`):** Check `OPENCODE` / `OPENCODE_SESSION_ID` env markers (if present) alongside `ANTIGRAVITY_*` and `CLAUDE_CODE_SESSION_ID`, falling back to `ULTRON_HARNESS` or Prime's registered harness.

---

## 3. Practical Notes for Local GPU Models (Operational Guidance)

When running ULTRON teams on local open-weights models via OpenCode:
1. **Context budget matters:** Local 14B–32B models degrade faster under bloated prompts than frontier models. Keep team/role charters focused and use `--visibility personal|team|global` discipline so roles only `view` relevant threads.
2. **Tool-calling reliability:** Prefer models with strong native function-calling support (e.g., Qwen3-Coder, Qwen2.5-Coder, Devstral, GLM-4, Llama 3.3/4, DeepSeek-V3/R1-Distill with tool parser enabled in vLLM/Ollama).
3. **Hybrid Hive sweet spot:** Run **ULTRON PRIME** and **Team Lead / Spec / Reviewer** on a frontier model (Antigravity / Claude Code) while running high-volume **Dev / Benchmarker / Explorer** teams on local GPU OpenCode models — or run 100% local on multi-GPU servers with a strong 70B+ model for Lead/Review and fast 14B–32B models for parallel specialists.
4. **Concurrency / VRAM throttling:** On a single-GPU host, avoid spawning 4+ heavy OpenCode roles simultaneously if Ollama/vLLM serializes requests with short HTTP timeouts; configure generous server timeouts and right-size team role count to GPU throughput.

---

## 4. Files to Modify (Implementation Scope)

| File | Summary of Changes |
|---|---|
| `ultron/core/core.py` | Extend `MODEL_ID_RE` (allow `/`, `:`, `@`, up to 128 chars, rejecting `..`); add `HARNESS_TOOLS["opencode"]`, `OPENCODE_MODEL_FOR_TIER`, `OPENCODE_URL_ENV`, `resolve_opencode_model()`, `OpenCodeAdapter` (registered in `HARNESS_ADAPTERS`), `detect_harness()` marker, `render-spawn` CLI formatting for `opencode`. |
| `docs/HARNESSES.md` | Add `opencode` column to Actions table + "OpenCode requirements" section (native `opencode serve`, Docker bind-mount recipe, `opencode.json` local Ollama/vLLM provider snippet, `ULTRON_OPENCODE_URL` & Basic Auth env vars). |
| `docs/ARCHITECTURE.md` | Add `opencode` to §7.2 (Shell Doorbell table) and §8 (Harness Layer, mixed hives noting `launches_from_cli = True`). |
| `ultron/core/ULTRON_PRIME.md` | Mention `opencode` as a supported CLI-spawnable harness (`--harness opencode`) and `provider/model` syntax. |
| `tests/test_ultron_core.py` | Add `opencode` to `HarnessAdapterContractTestCase.FOREIGN_TOOL_NAMES` and `RenderSpawnGoldenTestCase`; add `OpenCodeLifecycleTestCase` using a lightweight stdlib `http.server` mock of `opencode serve` (zero GPU, zero Docker required for unit tests!). |
| `tests/golden/render_spawn_opencode.json` | New golden snapshot for `render_spawn(..., harness="opencode")`. |

---

## 5. Verification & Test Plan

1. **Automated Unit & Contract Tests (`python3 -W error -m unittest discover -s tests`):**
   - **Mock HTTP `opencode serve` test server** (Python `http.server.ThreadingHTTPServer` in `tests/test_ultron_core.py`, zero GPU / zero network):
     - `spawn-team` creates sessions with `?directory=<role_dir>`, hard `permission` ruleset (`task: deny`, `question: deny`, plus `edit`/`write`/`apply_patch: deny` for read-only roles), writes `role_context.generated.md`, dispatches `prompt_async` with `system` + `model` (`providerID`/`modelID`), and binds sessions via `activate-team`.
     - **Rollback test:** Simulated failure on the 2nd role aborts & deletes the 1st role's session and leaves team `disabled` (preserving `archived` state on ephemeral teams).
     - **Doorbell test (mixed hive):** `core.py doorbell` from an Antigravity or Claude Code Prime wakes an OpenCode role via `POST /session/{sid}/prompt_async` with `Doorbell from ...` prefix and optional Basic Auth header.
     - **Liveness test:** `probe_liveness` reports `alive` (`idle`/`busy`) for live sessions and `gone` (exit code 1) when a session disappears from `/experimental/session`.
     - **Stop test:** `stop-team` calls `abort` + `DELETE` for every role and marks the team `disabled`.
     - **Fail-loud test:** Unreachable `ULTRON_OPENCODE_URL` raises an actionable `RuntimeError`.
     - **Model parsing tests:** `ollama/qwen3-coder:32b`, `openrouter/qwen/qwen3-coder:free`, `ULTRON_OPENCODE_MODEL_*` tier overrides, rejection of missing `/` on explicit OpenCode models, rejection of `..` and shell metacharacters.
   - **Contract tests:** `HarnessAdapterContractTestCase` verifies `opencode` implements every required method, maps every tier, reports identical role identity fields, and leaks zero Antigravity/Claude Code tool names.
   - **Golden fixture:** `tests/golden/render_spawn_opencode.json` matches byte-for-byte.
2. **CPU-Only Docker Integration Smoke Test (Post-Implementation, Zero GPU):**
   - Launch `ghcr.io/anomalyco/opencode:latest serve --hostname 0.0.0.0 --port 14096` with a temp ULTRON hive mounted at matching paths.
   - Verify `core.py spawn-team`, `core.py liveness`, `core.py doorbell`, and `core.py stop-team` against the real OpenCode `1.19.6` HTTP server (using a mock OpenAI-compatible stub endpoint on localhost if testing a full LLM turn without GPU).

---

## 6. Roadmap & Decoupled Follow-Up Modules

Aligned with ULTRON's modular, harness-agnostic philosophy:
1. **CLI-Launched Antigravity Teams (`agentapi new-conversation`):** Explore using Antigravity's `agentapi new-conversation [--model=<model_id>]` CLI command to enable `AntigravityAdapter.launches_from_cli = True`, completing the full **any-Prime × any-Team** matrix (so OpenCode Prime and Claude Code Prime can spawn Antigravity teams directly from the CLI).
2. **Layer 1 — Inference Server Provisioning (separate module):** Optional ULTRON tooling to start/manage local `llama.cpp` or `vLLM` inference servers with explicit model selection (while keeping external/remote endpoints first-class).
3. **Layer 2 — Harness Daemon Provisioning (separate module):** Optional ULTRON tooling to configure and launch `opencode serve` (port, auth, `opencode.json` provider wiring) and Prime TUI attach wrappers.
4. **Additional Harnesses:** Extend the same connect-only server-adapter pattern to **Pi** and **DeepSeekHarness** when prioritized.
