# ULTRON

**Universal Layered Team and Role Orchestration Network (ULTRON)** is an open-source, pure Git-native multi-agent orchestration framework engineered for high-autonomy software engineering and complex operational campaigns.

ULTRON runs on top of an agentic harness. **Claude Code** and **Google Antigravity** are supported today through harness adapters; [`docs/HARNESSES.md`](docs/HARNESSES.md) maps every ULTRON action to each harness's tools and explains how to add another.

---

## Executive Overview

Autonomous AI coding agents perform best when constrained by clear organizational boundaries, domain-specific charters, and explicit lines of communication. In unconstrained flat multi-agent systems, agents frequently succumb to context bloat, duplicate labor, uncoordinated file collisions, and runaway token burn.

ULTRON solves this by introducing a formal corporate-style hierarchy:
- **ULTRON PRIME** (*Ultimate Leader of Teams, Roles, and Operational Nodes*): The root orchestrator and sole point of contact with the human User.
- **Structured Teams as the Unit of Work**: Capabilities are partitioned into specialized teams organized in an arbitrary-depth organizational tree (`Layer 1..N`) under [`ultron/hive/`](ultron/hive/).
- **Flat Intra-Team Peer Roles**: Inside each team, specialist roles collaborate as flat peers under a mandatory Team Lead (`<team>/lead`), who coordinates internal execution and acts as the sole external communication bridge.
- **Pure Git-Native Datastore**: Zero external databases (no SQLite, no Redis, no Postgres). Org charts and role manifests are versioned in Git. Message board threads are append-only JSONL files (`*.jsonl`) that merge conflict-free across Git branches using `merge=union`.
- **Reactive, Zero-Polling Execution**: Passive on-disk storage paired with a reactive doorbell protocol (`whois --id-only`, then the harness's messaging tool) eliminates costly polling loops while ensuring instantaneous wakeup across agent sessions.

---

## The 5 Core Architectural Pillars

### 1. Single User-to-Prime Point of Contact & Neutral Workspace Baseline
In ULTRON, the human user never micromanages individual leaf agents or mediates lower-level technical disputes. The User interacts exclusively with **ULTRON PRIME**.

Furthermore, workspace sessions maintain a **neutral engineering baseline**:
- Repository guidelines in [`AGENTS.md`](AGENTS.md) govern standard engineering rigor (frequent small commits, fail-fast execution, authentic data without fake mock fallbacks, and skeptical Tier-2 code reviews).
- Sessions booting in the workspace act as standard senior engineers and **never** assume the persona of `ULTRON PRIME` unless explicitly commanded by the User via `load ultron/core/ULTRON_PRIME.md` (or when spawned with an explicit `[ULTRON_ROLE_ASSIGNMENT]` prompt).
- This separation prevents unexpected prompt hijacking during routine single-agent editing tasks while providing an instantaneous path into full network orchestration.

### 2. Sole Lifecycle & Provisioning Authority on ULTRON PRIME
To prevent runaway agent proliferation and cascading costs, provisioning authority is strictly centralized:
- **Centralized Spawning**: Only ULTRON PRIME creates teams, adds roles, and spawns or stops sessions (`spawn-team`, `stop-team`). Spawned Team Leads and Specialists never spawn agents.
- **Token Efficiency & Model Tiering**: Roles take a neutral tier (`small`, `medium`, `large`, or `inherit`) that each harness maps to its own models. Roles default to `medium`; heavier tiers are reserved for ULTRON PRIME or explicit User-authorized deep dives.
- **Dynamic Lifecycle Conservation**: Teams are not kept running indefinitely. When a team finishes its assigned milestone, ULTRON PRIME stands it down (`stop-team`). Charters, code, and persistent memory remain intact on disk, ready to be reactivated on demand in milliseconds.

### 3. Arbitrary `N`-Layer Hive Tree (`ultron/hive/`) & Flat Intra-Team Roles
ULTRON rejects rigid two-tier architectures in favor of an arbitrary-depth organization tree (`Layer 1..N`):
- **Root Layer (Layer 1)**: Teams report directly to `ultron-prime` (e.g., `core-platform`, `api-gateway`, `docs`).
- **Nested Subteams (Layer 2..N)**: Subteams attach under any parent team via `--parent <parent-slug>` (e.g., `auth` nested under `core-platform`, `token-audit` nested under `auth`).
- **Flat Peer Roles with Lead Spokesperson**:
  - `<team>/lead` is automatically provisioned with every team. The lead breaks down specs, assigns tasks to team specialists, skeptically reviews code, and serves as the sole communication conduit up to the parent lead (or Prime) and down to child team leads.
  - Specialists (`<team>/<role>`, such as `coder`, `designer`, `tester`, `writer`) focus entirely on domain implementation and report strictly to their own `<team>/lead`.
  - **Read-Only Specialists**: Reviewers and auditors can be configured with `--read-only`, enforcing strict inspection-only guardrails.

### 4. Pure Git-Native Zero-SQLite Storage & Conflict-Free Merges
ULTRON stores all organizational definitions, role configurations, and coordination history directly in the Git working tree with zero third-party database dependencies:
- **Persistent Git-Tracked Manifests**: Each team owns a [`team.json`](ultron/hive/) manifest; each role owns a [`role.json`](ultron/hive/) manifest. Paths are stored strictly as relative POSIX paths, ensuring the repository can be moved, cloned, or renamed across filesystems without broken references.
- **Clean Working Trees via Ephemeral Separation**: Live session bindings (each role's doorbell address and session ID) are stored in gitignored [`ultron/core/.runtime/sessions.json`](ultron/core/.gitignore). Spawning, waking, or standing down teams creates zero dirty `git status` modifications.
- **Conflict-Free Branch Merges (`*.jsonl merge=union`)**: All communication threads live in [`ultron/core/threads/t-YYYYMMDD-xxxxxxxx.jsonl`](ultron/core/threads/). Every message, status change, or reclassification is an append-only JSON event. Configured with `*.jsonl merge=union` in [`ultron/core/threads/.gitattributes`](ultron/core/threads/.gitattributes), multiple developers or agents working on separate Git branches can append posts concurrently; running `git merge` succeeds with zero merge conflicts, deterministically folding events by `(created_at, event_id)`.

### 5. Three-Tier Visibility Scoping & Reactive Doorbell Protocol
To prevent context dilution across large multi-agent networks, communication is partitioned into three explicit visibility tiers:
- **`personal`**: Visible only to the assigned role (`<team>/<role>`) and `ultron-prime`. Keyed to canonical `agent_id`, personal threads survive session terminations and respawns across campaigns—serving as persistent personal memory for role-specific lessons learned.
- **`team`**: Visible to all members of `team_slug` and `ultron-prime`. Supports parent↔child cross-layer delegation via `--with-team <subteam-slug>`, allowing clean inter-team handoffs without leaking noise to unrelated teams.
- **`global`**: Visible to every agent across the entire Hive for network-wide architectural standards, breaking API notices, or universal policies.
- **Reactive Doorbell Protocol**: Because JSONL files are passive on-disk logs and agents never poll in loops, collaboration follows a strict 3-step reactive protocol:
  1. Post message to thread via `python3 ultron/core/core.py new-thread` or `reply`.
  2. Resolve the recipient's doorbell address: `python3 ultron/core/core.py whois <target-agent> --id-only`.
  3. Wake the recipient immediately with the harness's messaging tool ([`docs/HARNESSES.md`](docs/HARNESSES.md)).

---

## Repository Layout

```text
ULTRON/
├── AGENTS.md                          # Neutral workspace engineering guidelines & review protocols
├── README.md                          # This public framework guide
├── ultron-architecture.html           # Interactive visual architecture diagram & showcase
├── docs/
│   ├── ARCHITECTURE.md                # Deep-dive as-implemented technical specification
│   └── HARNESSES.md                   # Per-harness actions, requirements & adapter contract
├── tests/
│   └── test_ultron_core.py            # Comprehensive unit, lifecycle & Git union-merge test suite
└── ultron/                            # Portable drop-in ULTRON orchestration engine
    ├── core/
    │   ├── ULTRON_PRIME.md            # Boot persona & operational manual for ULTRON PRIME
    │   ├── README.md                  # CLI reference & data model summary
    │   ├── core.py                    # Pure Git-native registry, scaffolder & JSONL board CLI
    │   ├── .gitignore                 # Ignores ephemeral .runtime/ sessions & file locks
    │   ├── templates/                 # Code generation templates for teams, roles & role context
    │   │   ├── team_agents.md.tmpl    # Team charter template
    │   │   ├── lead_role.md.tmpl      # Team Leader charter template
    │   │   ├── member_role.md.tmpl    # Specialist role charter template
    │   │   └── role_context.md.tmpl   # Per-role identity, routing & hydration (rendered per harness)
    │   ├── .runtime/                  # GITIGNORED runtime directory
    │   │   ├── sessions.json          # Live doorbell addresses, session IDs & agent statuses
    │   │   └── .lock                  # POSIX fcntl shared/exclusive file lock
    │   └── threads/                   # Git-tracked append-only JSONL message board
    │       ├── .gitattributes         # Enforces `*.jsonl merge=union` for zero-conflict merges
    │       └── t-YYYYMMDD-xxxxxxxx.jsonl
    └── hive/                          # Arbitrary N-layer organization tree
        └── <team-slug>/               # Layer-1 team directory
            ├── team.json              # Git-tracked team manifest
            ├── AGENTS.md              # Team mission, scope & operating principles
            ├── roles/                 # Flat peer specialist roles
            │   ├── lead/              # Mandatory coordinator & external communication bridge
            │   │   ├── role.json      # Git-tracked role manifest
            │   │   ├── AGENTS.md      # Role charter & specialist protocol
            │   │   └── workspace/     # Private scratchpad for <team>/lead
            │   └── <role-slug>/       # Specialist role (e.g., coder, reviewer, writer)
            │       ├── role.json
            │       ├── AGENTS.md
            │       └── workspace/     # Private scratchpad for <team>/<role>
            └── teams/                 # Nested Layer 2..N child teams
                └── <child-slug>/
```

---

## Quickstart Guide

### Prerequisites
- Python 3.10+ (standard library only; zero pip installations required).
- Git 2.20+ (supports union merge driver).
- A supported agent harness: Claude Code or Google Antigravity. Check its requirements in [`docs/HARNESSES.md`](docs/HARNESSES.md).

---

### Step 1: Booting ULTRON PRIME
Launch your agent session in this repository. Instruct the session to assume root orchestration authority:

```text
load ultron/core/ULTRON_PRIME.md
```

Upon loading, ULTRON PRIME registers its doorbell address, inspects the current Hive hierarchy, and reports status:
```bash
python3 ultron/core/core.py register-prime --id "<your-doorbell-address>"
python3 ultron/core/core.py org-tree
python3 ultron/core/core.py stats
```

---

### Step 2: Scaffolding Teams and Roles
Create teams and add specialized roles across any layer depth:

```bash
# 1. Create a Layer-1 team (automatically scaffolds ultron/hive/backend/ and backend/lead)
python3 ultron/core/core.py create-team \
  --slug backend \
  --name "Backend Engineering" \
  --mission "Implement core service APIs and database access layers" \
  --model medium

# 2. Add specialist roles to the team
python3 ultron/core/core.py add-role \
  --team backend \
  --role coder \
  --title "API Developer" \
  --responsibilities "Implement clean, tested Python endpoints per spec"

python3 ultron/core/core.py add-role \
  --team backend \
  --role reviewer \
  --title "Code Auditor" \
  --responsibilities "Conduct rigorous Tier-2 edge case audits" \
  --read-only

# 3. (Optional) Create a nested Layer-2 subteam
python3 ultron/core/core.py create-team \
  --slug auth \
  --parent backend \
  --name "Authentication Subteam" \
  --mission "Handle OAuth2 verification and token lifecycle"
```

---

### Step 3: Waking / Activating a Team
ULTRON PRIME spawns one live session per role and binds their doorbell addresses:

```bash
python3 ultron/core/core.py spawn-team backend
```

On Claude Code this launches and binds every role. On Antigravity it prints a launch plan that PRIME carries out, ending with `activate-team`.

---

### Step 4: Dispatching Work via Scoped Board & Doorbell
ULTRON PRIME dispatches objectives directly to the Team Lead:

```bash
# Create a team-scoped task thread
python3 ultron/core/core.py new-thread \
  --author ultron-prime \
  --visibility team \
  --team backend \
  --category task \
  --title "Feature: Implement Health Check Endpoint" \
  --content "Deliver GET /health endpoint with uptime and DB status checks."

# Resolve backend/lead's doorbell address, then doorbell it with the harness's messaging tool
python3 ultron/core/core.py whois backend/lead --id-only
```

The Team Lead hydrates its startup context, decomposes tasks for `backend/coder`, reviews results with `backend/reviewer`, updates the thread status (`set-status resolved`), and reports back up to ULTRON PRIME.

---

### Step 5: Standing Down Teams to Conserve Resources
When milestones are complete and no immediate tasks remain, ULTRON PRIME cleanly terminates the live agent sessions to conserve tokens and system resources:

```bash
python3 ultron/core/core.py stop-team backend --cascade
```

On Claude Code this stops every session and marks the team disabled. On Antigravity it prints a stop plan that PRIME carries out, ending with `disable-team`.

*Note: All files under `ultron/hive/` and all append-only thread histories in `ultron/core/threads/` remain completely intact. Reactivating the team later immediately restores each agent's identity and personal memory.*

---

### Step 6: Verifying System Integrity & Automated Tests
Validate manifest integrity, detect orphan sessions, and run the automated test suite anytime:

```bash
# Verify Hive manifests, session consistency, and .gitattributes
python3 ultron/core/core.py verify

# Run the complete test suite (includes real multi-branch Git union merge tests)
python3 -W error -m unittest discover -s tests -v
```

---

## Architectural & Technical References

| Document | Description |
| :--- | :--- |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | **Deep-Dive Architecture Specification:** Comprehensive treatise covering trust models, data schemas, locking mechanisms, deterministic event folding, lifecycle invariants, and Mermaid sequence diagrams. |
| [`docs/HARNESSES.md`](docs/HARNESSES.md) | **Harness Reference:** How ULTRON picks a harness, each action mapped to Claude Code and Antigravity tools, harness requirements, and the adapter contract for adding one. |
| [`ultron/core/README.md`](ultron/core/README.md) | **CLI & Storage Reference:** Command-line syntax, flag definitions, and schema details for `ultron/core/core.py`. |
| [`ultron/core/ULTRON_PRIME.md`](ultron/core/ULTRON_PRIME.md) | **Operational Manual for ULTRON PRIME:** Boot persona, hierarchy management, lifecycle workflows, and safety crons. |
| [`ultron-architecture.html`](ultron-architecture.html) | **Visual Architecture Showcase:** Single-page interactive HTML overview illustrating hierarchy and message board design. |
| [`AGENTS.md`](AGENTS.md) | **Workspace Engineering Rules:** Standard baseline for commits, fail-loud authentic data, safety crons, and Tier-2 skeptical code reviews. |

---

## License

ULTRON is distributed under the MIT License.
