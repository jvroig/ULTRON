# Agent Working Guidelines

> **Neutral Baseline:** Sessions in this workspace start as standard engineering assistants. Do **not** assume the persona of `ULTRON PRIME` unless the User explicitly instructs you to load [`ultron/core/ULTRON_PRIME.md`](ultron/core/ULTRON_PRIME.md) (or unless your session prompt contains an explicit `[ULTRON_ROLE_ASSIGNMENT]`).

## Core Principles

### 1. Frequent Small Commits and Pushes
* **Commit Early and Often:** Commit after every logical, verified unit of work (a fixed bug, a passing test/build, a completed component, or an updated document). Avoid large batch commits spanning unrelated subsystems.
* **Push Frequently:** Push committed work to the remote repository immediately (`git push origin <branch>`) to ensure code safety and avoid losing progress.
* **Clear Commit Messages:** Use concise, descriptive conventional commit messages (e.g., `feat:`, `fix:`, `docs:`, `perf:`, `refactor:`, `test:`).

### 2. Code Safety & Verification
* **Verify Before Committing:** Ensure code compiles, builds, or passes relevant sanity checks before staging and committing.
* **Keep Working Trees Clean:** Do not leave uncommitted changes or untracked intermediate files lingering across tasks.
* **Preserve Working Functionality:** Never break previously working builds or core systems when introducing new or experimental features.

### 3. Safety Cron & Campaign Liveness
* **Concept:** In long-running autonomous workflows or multi-stage campaigns, unexpected hangs, subshell deadlocks, or silent process terminations can stall progress indefinitely without triggering a reactive wake-up. A "Safety Cron" is a scheduled recurring heartbeat task that periodically wakes the agent to verify running background jobs, inspect process health, monitor log progress, and unblock stalled execution.
* **Frequency:** Standard default is every 30 minutes (`*/30 * * * *`). Tune the interval to match workload tempo (e.g., every 10–15 minutes for active benchmark suites or deployments; 30–60 minutes for prolonged background builds or data transfers).
* **Execution:** Initiate a recurring safety cron at the start of complex campaigns or background execution pipelines using your harness's scheduler, and cancel it once the campaign objectives are achieved and verified.

### 4. Authentic Data & Fail-Loud Integrity (Zero Fake Fallbacks)
* **No Silent Mock Fallbacks:** Never implement silent fake or deterministic fallbacks (e.g., hardcoded mock responses pretending a live service, model, or backend succeeded) when a critical subsystem or dependency is unavailable or uninitialized.
* **No Synthetic Placeholders:** Never generate or commit synthetic placeholder entries, numbered counters (`Variant #1`, `Item #2`), or templated boilerplate in production data or catalogs.
* **Fail Loud & Transparently:** If a required component, credential, or resource is missing or offline, surface the exact operational failure clearly in logs, UI, and telemetry rather than masking it.
* **Self-Healing Where Applicable:** When a recoverable dependency or service issue is detected, prefer explicit, observable recovery or repair flows over silent degradation.

### 5. Multi-Agent Collaboration via ULTRON Core & Reactive Doorbell
* **Shared Registry & Message Board (`ultron/core/`):** Use the ULTRON core CLI, `ultron/core/core.py` (your role assignment gives the exact command; see [`ultron/core/README.md`](ultron/core/README.md)) as the persistent source of truth for org hierarchy, team/role definitions, specs, reviews, and lessons learned.
* **Visibility Discipline (`personal` | `team` | `global`):** Scope board threads appropriately (`personal` for role-only lessons, `team` for intra-team or `--with-team` parent/child coordination, `global` for org-wide context) and always pass `--as <team>/<role>` when querying.
* **Reactive Doorbell Pattern:** Because JSON/JSONL board files are passive datastores and agents do not poll in loops, **always** resolve the recipient's doorbell address (`whois <agent_id> --id-only`) and doorbell them immediately ("Doorbell: Posted on Thread <thread_id> ('Title')..."). [`docs/HARNESSES.md`](docs/HARNESSES.md) names the doorbell tool for each harness.

### 6. Fail-Fast Execution & Process Hygiene
* **Bounded Subprocess Execution:** Ensure CLI scripts, test runners, and headless tools fail fast on unhandled errors and run under explicit timeouts rather than idling indefinitely.
* **Execution Hygiene:**
  - Give test suites and builds enough synchronous wait time to finish in the foreground instead of being backgrounded needlessly.
  - When a long-running process must run in the background, actively inspect its status or pair it with a safety heartbeat rather than relying on unbounded silent execution.

### 7. Rigorous, Skeptical Reviews (Zero Rubber-Stamping)
* **The Rubber-Stamping Anti-Pattern:** Never blindly accept or rubber-stamp work returned by peer agents solely because automated test suites report green. Automated tests only verify what the author thought to assert; they frequently miss state reset bugs, unhandled edge cases, resource/listener leaks, and broken lifecycle assumptions.
* **Two-Layer Review Structure (When Applicable):**
  - **Tier-1 UX & Design Review:** Focuses on visual hierarchy, layout ergonomics, usability, clarity, and qualitative user experience.
  - **Tier-2 Technical & Architectural Review Gate:** Focuses on deep code auditing, state persistence across cycles, resource/event lifecycles, edge-case failure modes, architectural invariants, and test suite rigor (verifying substantive behavioral invariants rather than superficial checks).
* **Mandatory Critical Punchlist on Rejection:** If an implementation exhibits logical gaps, unhandled edge cases, or broken invariants, sign-off **MUST** be held. Output a concrete, actionable punchlist detailing each defect, its impact, and the required fix.
* **Verification Before Advancing:** Trace state transitions and verify end-to-end behavior before certifying a milestone and unlocking subsequent phases.
