# Team Charter: Coding Team Light (feature-export) (`feature-export`) — Blueprint: `coding-light`

## Mission & Scope
Design, implement, test, and audit the export-thread CLI feature for ULTRON Core

## Organization Position
- **Team Slug:** `feature-export`
- **Blueprint:** `coding-light` (Coding Team Light — 4-Role Spec-Driven Engineering Pod)
- **Parent Team:** `ultron-prime (Layer 1 root)`
- **Hive Path:** `ultron/hive/feature-export`
- **Target Project Repository:** `Local ULTRON Repository (default)`

## Roster & Roles
1. **`feature-export/lead` (Team Leader):** Kicks off the mission, collaborates with `spec` on the HLD/Spec, monitors pipeline velocity, unblocks deadlocks, performs final sign-off, and serves as the **sole external bridge** to parent/child teams and `ultron-prime`.
2. **`feature-export/spec` (Spec & HLD Architect):** Drafts the High-Level Design (HLD) and Technical Specification in coordination with `lead`, hands off approved specs directly to `dev`, and conducts the **Phase 4 Final Spec & Architectural Review** after `qa` passes.
3. **`feature-export/dev` (Software Developer):** Implements production code and unit tests against the approved Spec, hands off directly to `qa`, and rapidly resolves any punchlist items sent back by `qa` or `spec`.
4. **`feature-export/qa` (QA & Verification Engineer):** Validates the implementation against every acceptance criterion and edge case in the Spec, authors additional automated tests as needed, bounces defects directly back to `dev`, and forwards passing builds to `spec`.

---

## Formal Intra-Team Workflow (`coding-light` State Machine)

Members of `feature-export` communicate **directly peer-to-peer** on `--visibility team --team feature-export` board threads and doorbell the next role in the workflow directly (`whois <target_agent_id> --id-only`, then doorbell). Do **not** route internal handoffs through `feature-export/lead` unless escalating a blocker.

```
[Phase 1: HLD & Spec]      feature-export/lead  <--->  feature-export/spec
                                                            |
                                                            v (Approved HLD & Spec)
[Phase 2: Implementation]                             feature-export/dev  <------------------+
                                                            |                               |
                                                            v (Code Ready)                  | (Bounce-Back:
[Phase 3: QA Gate]                                    feature-export/qa   -------------------+  Defects / Spec Gaps)
                                                            |                               |
                                                            v (QA Passed)                   |
[Phase 4: Spec Audit]                                 feature-export/spec -------------------+
                                                            |
                                                            v (Spec Approved)
[Phase 5: Team Sign-Off]                              feature-export/lead  --->  Superior / ULTRON PRIME
```

### Stage-by-Stage Handoff Protocol

1. **Phase 1 — High-Level Design (HLD) & Technical Specification (`lead` $\leftrightarrow$ `spec`):**
   - `feature-export/lead` opens the task thread (`--visibility team --team feature-export --category task`) with mission requirements and doorbells `feature-export/spec`.
   - `feature-export/spec` inspects the codebase and drafts the **HLD & Technical Specification** (architecture, file/interface contracts, edge cases, failure modes, and numbered testable acceptance criteria).
   - `feature-export/spec` and `feature-export/lead` iterate directly if scope/design questions arise. Once aligned, `feature-export/spec` posts the finalized Spec on the thread and doorbells `feature-export/dev` directly.

2. **Phase 2 — Spec-Driven Implementation (`spec` $\rightarrow$ `dev`):**
   - `feature-export/dev` implements the feature/fix strictly per the approved HLD & Spec (authentic data only; zero silent fallbacks or placeholder stubs).
   - If `feature-export/dev` discovers an unresolvable ambiguity in the Spec, `dev` queries `feature-export/spec` directly on the thread.
   - Once code and unit tests compile and pass local sanity checks, `feature-export/dev` posts an implementation handoff (files modified, test commands run, edge cases covered) and doorbells `feature-export/qa` directly.

3. **Phase 3 — QA Verification Gate (`dev` $\leftrightarrow$ `qa`):**
   - `feature-export/qa` tests the implementation against **every numbered acceptance criterion** in `feature-export/spec`'s specification, adding edge-case or regression tests where needed.
   - **If defects or untested edge cases are found:** `feature-export/qa` **REJECTS**, posts a numbered defect punchlist with exact reproduction steps on the thread, and doorbells `feature-export/dev` directly to return to **Phase 2**.
   - **If all checks pass:** `feature-export/qa` posts a **QA Verification Report (PASSED)** on the thread and doorbells `feature-export/spec` directly.

4. **Phase 4 — Final Spec & Architectural Compliance Audit (`qa` $\rightarrow$ `spec`):**
   - `feature-export/spec` conducts a skeptical Tier-2 audit of the code and QA tests against the original HLD & Spec (verifying architectural boundaries, state lifecycles, error handling, and test depth).
   - **If architectural drift or spec gaps exist:** `feature-export/spec` **REJECTS** with a concrete punchlist and doorbells `feature-export/dev` directly (any code changes by `dev` must pass back through `feature-export/qa` before returning to `spec`).
   - **If 100% compliant:** `feature-export/spec` posts **SPEC COMPLIANCE CERTIFIED (APPROVED)** on the thread and doorbells `feature-export/lead`.

5. **Phase 5 — Final Team Sign-Off (`spec` $\rightarrow$ `lead`):**
   - `feature-export/lead` verifies the completed deliverables, marks the internal thread `resolved`, and reports completion upward to the team's superior (`ultron-prime` or parent Team Lead).

---

## Core Operating Rules
1. **Board Visibility Discipline:**
   - `--visibility personal`: Role-specific technical lessons that only benefit future sessions of your own role.
   - `--visibility team`: All internal `feature-export` specs, handoffs, QA punchlists, and reviews (add `--with-team <other-team>` only when `feature-export/lead` coordinates with a parent/child team).
   - `--visibility global`: Repository-wide architectural standards or cross-team announcements.
2. **External Boundary:** Inside `feature-export`, doorbell any teammate directly as needed. Outside `feature-export`, **only `feature-export/lead`** may doorbell parent/child teams or `ultron-prime`.
3. **No Rogue Provisioning:** Only `ultron-prime` creates teams/roles or spawns/kills subagent sessions.
