# Architectural & Technical Code Review: Multi-Harness Integration

**Target Branch:** `claude-code-test`  
**Reviewer:** ULTRON PRIME (Gemini 3.8 / Antigravity Lead)  
**Author / Audience:** Opus 5.5 & Core Development Team  
**Review Date:** 2026-11-10  
**Overall Status:** **Actionable Punchlist — Approved Pending Fixes**

---

## 1. Executive Summary & Commendations

The work done on branch `claude-code-test` represents a **major architectural advancement** toward making ULTRON genuinely harness-neutral. The abstraction cleanly separates core repository invariants (the organizational hierarchy, append-only JSONL threads, and role charters) from the execution harness.

### Key Strengths & Innovations:
1. **`HarnessAdapter` Hierarchy:**
   The abstraction in `ultron/core/core.py` cleanly encapsulates harness-specific tool names (`HARNESS_TOOLS`), doorbell addressing, and launch-spec compilation.
2. **Harness-Neutral Model Tiers:**
   Introducing `small`, `medium`, and `large` with transparent legacy aliases (`flash_lite`, `flash`, `pro`) maps cleanly to both Anthropic (`haiku`, `sonnet`, `opus`) and Google (`flash_lite`, `flash`, `pro`) models.
3. **Claude Code Lifecycle & Process Isolation:**
   Using `claude --bg` with per-role working directories, coupled with `.claude/settings.json` (`worktree.bgIsolation: none`), allows background roles to edit the shared checkout in place.
4. **Hard Invariant Enforcement in Claude Code:**
   Configuring `permissions.deny: ["Agent", "Bash(claude:*)", "Bash(claude *)"]` for worker roles preserves ULTRON's fundamental rule: **only ULTRON PRIME may spawn agent sessions**.
5. **Partial Launch Rollback Safety:**
   `ClaudeCodeAdapter.spawn()` safely terminates already-launched background sessions if a subsequent role fails to boot, avoiding orphaned zombie processes.
6. **Rigorous Golden Tests:**
   The addition of `HarnessAdapterContractTestCase` and golden fixture tests (`tests/golden/render_spawn_*.json`) establishes a reliable regression baseline.

---

## 2. Critical Defects & Actionable Punchlist

Despite these strengths, our audit and live runtime verification in Antigravity uncovered **1 Critical Blocker Regression** and **4 Architectural/UX Deficiencies** that should be resolved before merging to `main`.

---

### Defect P-1 (BLOCKER): Broken Out-of-the-Box Antigravity CLI (Auto-Detection Regression)

#### Location:
[`ultron/core/core.py:552-563`](file:///Users/jvroig/Dev/ULTRON/ultron/core/core.py#L552-L563)

#### Symptoms & Impact:
In an Antigravity terminal session, running standard commands like `render-spawn`, `spawn-team`, or `stop-team` without explicit flags now **fails immediately with exit code 1**:
```bash
$ python3 ultron/core/core.py render-spawn docs
[ULTRON Error] Cannot tell which harness runs ULTRON. Pass --harness or set ULTRON_HARNESS (one of ['antigravity', 'claude-code']).
```
Prior to this branch, Antigravity was the default and required zero flags. This breaks out-of-the-box ergonomics for Antigravity operators.

#### Root Cause:
`resolve_harness()` only checks `os.environ.get("CLAUDE_CODE_SESSION_ID")` for auto-detection:
```python
def resolve_harness(explicit: Optional[str] = None) -> str:
    chosen = (explicit or os.environ.get(HARNESS_ENV, "")).strip()
    if not chosen and os.environ.get("CLAUDE_CODE_SESSION_ID"):
        chosen = "claude-code"
    if not chosen:
        raise ValueError(
            f"Cannot tell which harness runs ULTRON. Pass --harness or set {HARNESS_ENV} "
            f"(one of {sorted(HARNESS_ADAPTERS)})."
        )
    harness_adapter(chosen)
    return chosen
```
It completely ignores the environment variables present in every Antigravity session (`ANTIGRAVITY_AGENT`, `ANTIGRAVITY_CONVERSATION_ID`, `ANTIGRAVITY_APP_DATA_DIR`). Furthermore, it fails to consult `core.get_prime_harness()` from `.runtime/sessions.json` when Prime is already registered.

#### Why the Test Suite Missed It:
In `tests/test_ultron_core.py`, tests either explicitly passed `--harness antigravity` or mocked `ULTRON_HARNESS=claude-code`, never asserting the zero-config Antigravity runtime environment.

#### Required Fix:
Update `resolve_harness()` (and pass `core` where available) to:
1. Check `os.environ.get("ANTIGRAVITY_AGENT")` or `os.environ.get("ANTIGRAVITY_CONVERSATION_ID")` $\rightarrow$ `"antigravity"`.
2. Check `os.environ.get("CLAUDE_CODE_SESSION_ID")` $\rightarrow$ `"claude-code"`.
3. If still unresolved and ULTRON PRIME has registered a harness in `sessions.json`, fall back to `prime_harness`.

```python
def resolve_harness(explicit: Optional[str] = None, core: Optional["UltronCore"] = None) -> str:
    chosen = (explicit or os.environ.get(HARNESS_ENV, "")).strip()
    if not chosen:
        if os.environ.get("ANTIGRAVITY_AGENT") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID"):
            chosen = "antigravity"
        elif os.environ.get("CLAUDE_CODE_SESSION_ID"):
            chosen = "claude-code"
        elif core is not None:
            prime_harness = core.get_prime_harness()
            if prime_harness:
                chosen = prime_harness
    if not chosen:
        raise ValueError(
            f"Cannot tell which harness runs ULTRON. Pass --harness or set {HARNESS_ENV} "
            f"(one of {sorted(HARNESS_ADAPTERS)})."
        )
    harness_adapter(chosen)
    return chosen
```

---

### Defect P-2 (MEDIUM): Leaky `@role_context.generated.md` in Antigravity System Prompts

#### Location:
[`ultron/core/core.py:121-124`](file:///Users/jvroig/Dev/ULTRON/ultron/core/core.py#L121-L124) and [`ultron/core/core.py:317-321`](file:///Users/jvroig/Dev/ULTRON/ultron/core/core.py#L317-L321)

#### Symptoms & Impact:
In Antigravity, every subagent payload rendered by `render-spawn` contains the literal text `@role_context.generated.md` appended to the end of its `SystemPrompt` under `## Role Charter`:
```markdown
## Role Charter (`ultron/hive/docs/roles/writer/AGENTS.md`)
# Role Charter: Technical Writer (docs/writer)
...
@role_context.generated.md
```
- Antigravity does **not** support Claude Code's `@filename` syntax; it treats this as literal plain text.
- More importantly, `role_context.generated.md` **does not even exist on disk** during Antigravity execution (it is only created by `ClaudeCodeAdapter.spawn()`).
- This clutters the model's context and creates broken file references.

#### Required Fix:
In `AntigravityAdapter.charters_block()` (or during `build_spec`), strip the `ROLE_CONTEXT_IMPORT` line (`@role_context.generated.md`) from `ctx['role_charter']`:
```python
    def charters_block(self, ctx: Mapping[str, Any]) -> str:
        clean_charter = "\n".join(
            line for line in ctx["role_charter"].splitlines()
            if line.strip() != ROLE_CONTEXT_IMPORT
        ).strip()
        return (
            f"\n---\n\n## Inherited Team & Ancestor Charters\n{ctx['inherited_charters']}\n\n---\n\n"
            f"## Role Charter (`{ctx['role']['role_path']}/AGENTS.md`)\n{clean_charter}"
        )
```

---

### Defect P-3 (LOW-MEDIUM): Asymmetric `stop-team` Behavior

#### Location:
[`ultron/core/core.py:289-303`](file:///Users/jvroig/Dev/ULTRON/ultron/core/core.py#L289-L303) vs [`ultron/core/core.py:468-490`](file:///Users/jvroig/Dev/ULTRON/ultron/core/core.py#L468-L490)

#### Symptoms & Impact:
- On **Claude Code**, `stop-team` stops the sessions, calls `core.disable_team()`, and transitions the team to `disabled`.
- On **Antigravity**, `stop-team` prints a message telling Prime to call `manage_subagents` and `disable-team`, but leaves the team status as **`active`**.
- This creates semantic inconsistency: a command named `stop-team` actually stops/disables the team on one harness, but is a no-op dry-run on another.

#### Required Fix:
Make the distinction explicit or support a `--disable` flag on Antigravity:
1. Clarify in CLI output: `[ULTRON] Generated stop plan for Antigravity (Team remains active until disable-team is run).`
2. Or provide an optional `--force-disable` flag that disables the team in the registry while reminding the user to kill the subagents via `manage_subagents`.

---

### Defect P-4 (LOW): Missing Harness Attribution in `activate-team` CLI

#### Location:
[`ultron/core/core.py:3248-3258`](file:///Users/jvroig/Dev/ULTRON/ultron/core/core.py#L3248-L3258) and [`ultron/core/core.py:3725`](file:///Users/jvroig/Dev/ULTRON/ultron/core/core.py#L3725)

#### Symptoms & Impact:
`UltronCore.activate_team()` accepts a `harness: str = ""` parameter.
However, the CLI subparser `activate-team` does not take or resolve `--harness`. When Antigravity binds conversation UUIDs via `activate-team`, each role is saved into `.runtime/sessions.json` with `"harness": ""`.
This makes downstream queries (such as `get_prime_harness()` or team harness inspection) lose track of which harness powers those roles.

#### Required Fix:
Add `--harness` argument to the `activate-team` CLI subparser and resolve it via `resolve_harness(args.harness)`.

---

### Defect P-5 (LOW): Fragile Session ID Parsing (`BG_SESSION_ID_RE`)

#### Location:
[`ultron/core/core.py:65`](file:///Users/jvroig/Dev/ULTRON/ultron/core/core.py#L65)

#### Symptoms & Impact:
`BG_SESSION_ID_RE = re.compile(r"claude attach ([0-9a-f]{8})\b")` is hardcoded to expect exactly 8 hexadecimal characters. If a future Claude Code release or specific environment outputs a different session ID format (e.g. UUID, alphanumeric string, or prefixed ID), `spawn-team` will fail to match the session ID and trigger an unwanted rollback.

#### Required Fix:
Relax the regex to match general alphanumeric tokens:
```python
BG_SESSION_ID_RE = re.compile(r"claude attach\s+([a-zA-Z0-9_\-]+)")
```

---

## 3. Recommendations for Future Harness Extensibility (Codex, OpenCode, Aider, Cursor)

To ensure adding the next harness (e.g., OpenAI Codex or Aider) is seamless, consider these structural refinements to `HarnessAdapter`:

1. **Adapter Capability Flags:**
   Explicitly declare what the harness can perform directly:
   ```python
   class HarnessAdapter:
       can_direct_spawn: bool = False  # True for Claude Code / Codex CLI; False for Antigravity
       can_direct_stop: bool = False   # True for Claude Code / Codex CLI; False for Antigravity
   ```
2. **Session Liveness / Health Probing:**
   Add `probe_liveness(self, session_id: str) -> bool` to `HarnessAdapter`.
   For Claude Code, this can inspect `claude agents` or check process status so ULTRON Core can detect when a background role has crashed or terminated unexpectedly.
3. **Decouple Folder Charters from Harness Directives:**
   Avoid writing Claude-specific syntax (`@role_context.generated.md`) into shared, Git-tracked `AGENTS.md` files. Instead, let `ClaudeCodeAdapter.spawn()` dynamically inject the import or manage context strictly within gitignored files (`.claude/` or generated markdown).

---

## 4. Summary Table & Next Steps

| Defect | Impact Area | Priority | Recommendation |
| :--- | :--- | :--- | :--- |
| **P-1** | Antigravity CLI zero-config | **BLOCKER** | Add `ANTIGRAVITY_AGENT` / `ANTIGRAVITY_CONVERSATION_ID` detection and Prime fallback to `resolve_harness()`. |
| **P-2** | Prompt hygiene | **MEDIUM** | Strip `@role_context.generated.md` in `AntigravityAdapter.charters_block()`. |
| **P-3** | Lifecycle consistency | **LOW-MEDIUM** | Align `stop-team` semantics and CLI output messaging. |
| **P-4** | State completeness | **LOW** | Pass resolved harness in `activate-team` CLI. |
| **P-5** | Claude Code robustness | **LOW** | Broaden `BG_SESSION_ID_RE` regex. |

With these targeted fixes in place, the multi-harness architecture will be rock-solid, backwards-compatible with Antigravity, and ready for upstream merge!
