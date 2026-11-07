# ULTRON Technical Architecture Specification

**Universal Layered Team and Role Orchestration Network (ULTRON)**  
*Document Version:* 1.0.0 · *Status:* As-Implemented Specification · *Storage Engine:* Pure Git-Native (Zero SQLite)

---

## 1. Executive Summary & Design Philosophy

Autonomous agent systems operating in complex software engineering repositories face fundamental scaling bottlenecks:
1. **Context Dilution & Distraction:** Flat multi-agent networks broadcast messages globally or rely on monolithic conversation histories, rapidly consuming token context windows with irrelevant chatter.
2. **Unconstrained Spawning Chaos:** Allowing arbitrary subagents to spawn child subagents leads to uncontrolled recursion, runaway token burn, and non-deterministic process trees.
3. **Database Fragility & Merge Friction:** Conventional multi-agent frameworks rely on external databases (SQLite, Redis, Postgres) or server daemons. These fail to track Git branch changes, suffer corruption during branch checkouts, and cannot be merged across concurrent branches.
4. **Polling Overhead:** Agents operating in continuous polling loops waste computational cycles, rate limits, and tokens waiting for asynchronous task completions.

**ULTRON** solves these challenges through an opinionated, pure Git-native architecture:
- **Centralized Orchestration Authority:** Single User point-of-contact and lifecycle provisioning authority vested exclusively in **ULTRON PRIME** (*Ultimate Leader of Teams, Roles, and Operational Nodes*).
- **Arbitrary N-Layer Hive:** A hierarchical organization tree (`ultron/hive/`) where teams are the fundamental unit of work, structured into flat peer roles governed by a dedicated Team Lead.
- **Log-Structured Git-Native Storage:** Zero SQLite. Git-tracked JSON manifests (`team.json`, `role.json`), gitignored ephemeral session bindings (`.runtime/sessions.json`), and append-only JSONL thread event logs (`ultron/core/threads/*.jsonl`) configured with `*.jsonl merge=union` for conflict-free cross-branch merges.
- **Strict Three-Tier Visibility:** Scoped visibility (`personal`, `team` / `--with-team`, `global`) enforced with mandatory caller identification (`--as <agent_id>`).
- **Reactive Doorbell Protocol:** Event-driven waking (`whois --id-only` + `send_message`) completely eliminating polling loops.

---

## 2. System Topology & Trust/Privilege Hierarchy

```
                                  +-------------------+
                                  |       USER        |
                                  +---------+---------+
                                            |
                                            v (Direct Conversation)
                                  +-------------------+
                                  |   ULTRON PRIME    |
                                  |   (Root Leader)   |
                                  +---------+---------+
                                            |
                      +---------------------+---------------------+
                      |                                           |
                      v (Layer 1 Delegation)                      v (Layer 1 Delegation)
            +-------------------+                       +-------------------+
            |    Team A: Lead   |                       |    Team B: Lead   |
            +---------+---------+                       +---------+---------+
                      |                                           |
     +----------------+----------------+                 +--------+--------+
     |                |                |                 |                 |
     v                v                v                 v                 v
+---------+   +---------------+   +---------+   +-----------------+   +-----------------+
| Team A: |   | Team A1: Lead |   | Team A: |   | Team B: Writer  |   | Team B: Auditor |
|  Coder  |   |   (Subteam)   |   | Reviewer|   +-----------------+   +-----------------+
+---------+   +-------+-------+   +---------+
                      |
                      v (Layer 2 Intra-Team)
              +-----------------+
              | Team A1: Worker |
              +-----------------+
```

### 2.1 The Tripartite Role Architecture

ULTRON defines three distinct tiers of agent responsibility:

| Role Tier | Identifier (`agent_id`) | Scope of Authority | Primary Duties |
| :--- | :--- | :--- | :--- |
| **Root Orchestrator** | `ultron-prime` | Global across the entire Hive | Converses with the User; sole authority to create/remove teams, add roles, spawn sessions, and kill sessions; curates global architecture and resolves escalations. |
| **Team Leader** | `<team-slug>/lead` | Team boundary + direct child teams | Deconstructs team missions into discrete tasks; assigns work to team specialists; enforces Tier-2 skeptical reviews; acts as sole external spokesperson upward to superior and downward to child leads. |
| **Domain Specialist** | `<team-slug>/<role-slug>` | Intra-team role workspace | Autonomous domain execution (`coder`, `designer`, `tester`, `writer`); reports strictly to `<team-slug>/lead`; records private lessons in `personal` memory. |

### 2.2 Chain-of-Command Routing Rules
The organizational graph enforces strict routing invariants verified by `python3 ultron/core/core.py contacts <agent_id>`:
1. **Specialist Boundary:** Specialists have `direct_peers_allowed: false`. They report exclusively to `<team-slug>/lead`. Specialists never directly message sibling specialists, external teams, or `ultron-prime`.
2. **Team Lead Spokesperson:** The Team Lead is the team's sole communication bridge:
   - **Upward:** Reports progress, blockers, and headcount/subteam requests to its superior (either parent `<parent-slug>/lead` or `ultron-prime`).
   - **Downward:** Delegates tasks to direct child team leads using `--visibility team --team <team-slug> --with-team <child-slug>`.
3. **Escalation Protocol:** If an unresolvable technical conflict, schema incompatibility, or lifecycle need arises, it escalates strictly upward along the chain of command until it reaches `ultron-prime`.

### 2.3 Harness Privilege Invariants & Sandboxing Nuance

```
                      +------------------------------------------+
                      |               ULTRON PRIME               |
                      |  EnableSubagentTools: True               |
                      |  EnableWriteTools:    True               |
                      |  Model Policy:        User Authorized    |
                      +--------------------+---------------------+
                                           |
                                           v Spawns Subagents
                      +------------------------------------------+
                      |         Team Leads & Specialists         |
                      |  EnableSubagentTools: False  <-- LOCKED   |
                      |  EnableWriteTools:    True   <-- NUANCE   |
                      |  Model Policy:        Default 'flash'    |
                      +------------------------------------------+
```

#### Invariant 1: Centralized Provisioning (`EnableSubagentTools = False`)
In the runtime harness (Google Antigravity), `EnableSubagentTools` allows an agent to call `define_subagent`, `invoke_subagent`, and `manage_subagents`. In ULTRON, **all** spawned agents (both Team Leads and Specialists) are generated with:
```json
"EnableSubagentTools": false
```
This hard invariant ensures that only `ultron-prime` can spawn or kill agent processes, eliminating runaway agent recursion and unbounded token consumption.

#### Invariant 2: Antigravity `EnableWriteTools` vs. `run_command` Nuance
In Google Antigravity, the headless bash tool `run_command` is permission-gated under `EnableWriteTools`. If a subagent is provisioned with `EnableWriteTools = False`, the harness strips `run_command` entirely.

However, all ULTRON agents—including read-only auditors—must be able to run `python3 ultron/core/core.py` to hydrate memory, list board threads, view specs, and append replies.

Therefore, ULTRON implements the following mechanism:
1. All rendered subagents specify `EnableWriteTools = True` in their Antigravity payload to preserve access to `run_command`.
2. For roles registered with `--read-only` (such as `reviewer` or `auditor`), the manifest records `"write_tools": false`.
3. The prompt compiler (`render_spawn`) injects a mandatory behavioural boundary into the subagent's system prompt:
   ```text
   - [READ-ONLY ROLE MODE]: Do NOT call write_file or edit_file on repository source code.
     Use run_command strictly for python3 ultron/core/core.py board operations and non-mutating inspection/test commands.
   ```
4. This guarantees that read-only auditors retain board and inspection capabilities while strictly barring repository source code mutations.

#### Invariant 3: Model Tiering & Cost Conservation
Spawned subagents default to **Gemini Flash** (`--model flash` or `"flash_lite"`). Flash provides high throughput and token economy for routine implementation, testing, and reviews. Heavyweight frontier models (`pro` or `inherit`) are strictly restricted to `ultron-prime` or granted only when explicitly authorized by the User for intricate architectural problems.

---

## 3. On-Disk Data Model & Schemas (The Zero-SQLite Engine)

ULTRON eliminates binary databases. The entire system state is stored directly within the Git working tree using plain text files.

### 3.1 Repository Layout & Relocation Invariant
All on-disk paths recorded inside manifests (`team.json` and `role.json`) are stored strictly as **relative POSIX paths** originating from the repository root (e.g., `ultron/hive/backend`, `ultron/hive/backend/roles/lead/workspace`).

> [!IMPORTANT]
> Because no absolute paths (`/Users/...` or `C:\...`) are ever written to Git-tracked files, the entire repository can be moved, cloned, renamed, or checked out on different operating systems without invalidating manifests or requiring data migration.

### 3.2 Persistent Team Manifest (`team.json`)
Located at: `ultron/hive/.../<team-slug>/team.json`  
Tracks the persistent organizational metadata for a team.

```json
{
  "created_at": "2026-11-07T10:08:13.469120Z",
  "default_model": "flash",
  "hive_path": "ultron/hive/docs",
  "layer": 1,
  "mission": "Author and audit ULTRON's public-ready README.md, deep-dive docs/ARCHITECTURE.md, and visual HTML architecture showcase.",
  "name": "Technical Documentation & Editorial",
  "parent_team": null,
  "slug": "docs",
  "updated_at": "2026-11-07T10:08:13.488310Z",
  "workspace_mode": "inherit"
}
```

#### Field Specifications:
- `slug` *(string, required)*: Unique team identifier matching `^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$`.
- `name` *(string, required)*: Human-readable team title.
- `mission` *(string, required)*: Core mandate and operational boundaries of the team.
- `layer` *(integer, required)*: Depth in the organizational hierarchy (1 for top-level teams reporting to Prime; `parent.layer + 1` for subteams).
- `parent_team` *(string | null, required)*: Slug of parent team, or `null` if attached to `ultron-prime`.
- `default_model` *(string, required)*: Default LLM tier (`flash_lite`, `flash`, `pro`, `inherit`).
- `workspace_mode` *(string, required)*: Antigravity subagent workspace isolation (`inherit`, `share`, `branch`).
- `hive_path` *(string, required)*: Relative POSIX directory path from repo root.
- `created_at` *(string, ISO-8601 UTC)*: Immutable timestamp of team creation.
- `updated_at` *(string, ISO-8601 UTC)*: Timestamp of last structural update (e.g., adding a role).

### 3.3 Persistent Role Manifest (`role.json`)
Located at: `ultron/hive/.../<team-slug>/roles/<role-slug>/role.json`  
Tracks the domain charter and tool privileges for a specific specialist role.

```json
{
  "agent_id": "docs/writer",
  "mcp_tools": true,
  "model": "flash",
  "registered_at": "2026-11-07T10:08:13.488100Z",
  "responsibilities": "Author public-ready README.md and comprehensive as-implemented docs/ARCHITECTURE.md grounded strictly in ultron/core/core.py, ultron/core/ULTRON_PRIME.md, and templates.",
  "role": "writer",
  "role_path": "ultron/hive/docs/roles/writer",
  "team_slug": "docs",
  "title": "Technical Writer",
  "write_tools": true
}
```

#### Field Specifications:
- `agent_id` *(string, required)*: Canonical role ID (`<team-slug>/<role-slug>`).
- `role` *(string, required)*: Role slug (e.g., `lead`, `coder`, `reviewer`, `writer`).
- `team_slug` *(string, required)*: Slug of enclosing team.
- `title` *(string, required)*: Descriptive professional title.
- `responsibilities` *(string, required)*: Explicit domain directives and expectations.
- `model` *(string, required)*: LLM tier assigned to this specific role.
- `write_tools` *(boolean, required)*: `true` for general roles; `false` for read-only auditor roles.
- `mcp_tools` *(boolean, required)*: Flag enabling Model Context Protocol extensions.
- `role_path` *(string, required)*: Relative POSIX directory path from repo root.
- `registered_at` *(string, ISO-8601 UTC)*: Timestamp of role addition.

### 3.4 Ephemeral Runtime State (`.runtime/sessions.json`)
Located at: `ultron/core/.runtime/sessions.json`  
**Gitignored** via `ultron/core/.gitignore`. Never committed to version control.

```json
{
  "agents": {
    "docs/lead": {
      "conversation_id": "04069c63-eb91-4c7e-8f7b-c428887f3a38",
      "last_seen": "2026-11-07T10:13:12.180210Z",
      "registered_at": "2026-11-07T10:08:13.471238Z",
      "status": "active"
    },
    "docs/writer": {
      "conversation_id": "6dc4dd42-c318-4bb1-916f-cf3f31bfe9e7",
      "last_seen": "2026-11-07T10:11:19.459012Z",
      "registered_at": "2026-11-07T10:08:13.488100Z",
      "status": "active"
    },
    "ultron-prime": {
      "conversation_id": "abcb720d-b0b0-4df0-bf89-5f6094b341cd",
      "last_seen": "2026-11-07T10:11:12.000000Z",
      "registered_at": "2026-11-07T10:05:01.120300Z",
      "status": "active"
    }
  }
}
```

#### Clean Git Tree Separation:
Because live harness session UUIDs change whenever an agent session is terminated and respawned, storing session bindings in `team.json` or `role.json` would cause continuous, noisy diffs in `git status`. By isolating session UUIDs inside gitignored `.runtime/sessions.json`:
- `activate-team`, `activate-agent`, `disable-team`, and `prepare-disable` mutate only `.runtime/sessions.json`.
- Running `git status --porcelain` remains 100% clean across all team wake/sleep cycles.

---

### 3.5 Append-Only JSONL Event Model (`ultron/core/threads/*.jsonl`)
Every message thread is an independent, Git-tracked file named `t-YYYYMMDD-xxxxxxxx.jsonl`.  
Threads are append-only event streams. The system defines exactly 4 event types:

```
  Line 1: {"type": "thread", "thread_id": "t-20261107-567656f5", "title": "...", ...}
  Line 2: {"type": "post", "post_id": "p-169cbf74", "content": "Assignment...", ...}
  Line 3: {"type": "post", "post_id": "p-99a12b44", "content": "Deliverables ready...", ...}
  Line 4: {"type": "status", "status": "resolved", "actor": "docs/lead", ...}
  Line 5: {"type": "reclassify", "visibility": "global", "actor": "ultron-prime", ...}
```

#### Event Type Schemas:

##### 1. Root Thread Event (`type: "thread"`)
The first line of every `.jsonl` file. Initializes thread metadata:
```json
{
  "author": "docs/lead",
  "author_id": "04069c63-eb91-4c7e-8f7b-c428887f3a38",
  "category": "task",
  "content": "Assignment from docs/lead to docs/writer: Author documentation...",
  "created_at": "2026-11-07T10:12:53.104200Z",
  "event_id": "e-b49a12f80c11",
  "owner_agent": "",
  "post_id": "p-169cbf74",
  "status": "open",
  "tags": "docs,architecture",
  "team_slug": "docs",
  "thread_id": "t-20261107-567656f5",
  "title": "Task: Author Public README.md and Comprehensive docs/ARCHITECTURE.md",
  "type": "thread",
  "visibility": "team",
  "with_team": ""
}
```

##### 2. Reply Post Event (`type: "post"`)
Appended when any authorized agent posts a message:
```json
{
  "author": "docs/writer",
  "author_id": "6dc4dd42-c318-4bb1-916f-cf3f31bfe9e7",
  "content": "Drafted initial architecture specification. Ready for Tier-2 review.",
  "created_at": "2026-11-07T10:14:02.891040Z",
  "event_id": "e-8f3b1901c0aa",
  "parent_post_id": "p-169cbf74",
  "post_id": "p-99a12b44",
  "tags": "",
  "thread_id": "t-20261107-567656f5",
  "type": "post"
}
```

##### 3. Status Transition Event (`type: "status"`)
Appended when an authorized agent updates thread progress (`open`, `in_progress`, `resolved`, `blocked`, `closed`):
```json
{
  "actor": "docs/lead",
  "created_at": "2026-11-07T10:16:11.512030Z",
  "event_id": "e-10fa32d4e8bb",
  "status": "resolved",
  "thread_id": "t-20261107-567656f5",
  "type": "status"
}
```

##### 4. Scope Reclassification Event (`type: "reclassify"`)
Appended exclusively by `ultron-prime` to promote or narrow visibility:
```json
{
  "actor": "ultron-prime",
  "created_at": "2026-11-07T10:18:00.120930Z",
  "event_id": "e-66ca9901ef23",
  "owner_agent": "",
  "team_slug": "docs",
  "thread_id": "t-20261107-567656f5",
  "type": "reclassify",
  "visibility": "global",
  "with_team": ""
}
```

---

### 3.6 Deterministic Event Folding Algorithm

Because Git merges across branches can interleave lines in non-chronological order, ULTRON evaluates threads using a deterministic event folding algorithm implemented in `UltronCore._fold_thread_jsonl`:

```python
# Deterministic Folding Algorithm Logic (core.py)
events = []
seen_event_ids = set()

for line in raw_lines:
    ev = json.loads(line)
    ev_id = ev.get("event_id")
    if ev_id in seen_event_ids:
        continue  # Deduplicate identical events from multi-branch merges
    seen_event_ids.add(ev_id)
    events.append(ev)

root = [e for e in events if e.get("type") == "thread"][0]
follow_ups = [e for e in events if e.get("type") != "thread"]

# DETERMINISTIC ORDERING KEY: (created_at, event_id)
follow_ups.sort(key=lambda e: (str(e.get("created_at") or ""), str(e.get("event_id") or "")))

# Materialize state by replaying sorted events sequentially
for ev in follow_ups:
    if ev["type"] == "post":
        posts.append(...)
    elif ev["type"] == "status":
        current_status = ev["status"]
    elif ev["type"] == "reclassify":
        current_visibility = ev["visibility"]
```

#### Why Git `merge=union` Guarantees Zero Conflicts
In [`ultron/core/threads/.gitattributes`](../ultron/core/threads/.gitattributes):
```text
*.jsonl merge=union
```
The Git union merge driver automatically combines lines from both branches on merge without generating conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`). Because:
1. Each event is a self-contained, valid JSON line.
2. Events possess unique `event_id` tokens (preventing duplicate insertion).
3. The folding engine sorts follow-ups strictly by `(created_at, event_id)`.

Two developers or agents working on separate Git branches can concurrently reply to the exact same thread and change its status. When their branches merge via `git merge`, the resulting JSONL file replays into the exact same deterministic materialized state on all machines.

---

## 4. Concurrency, Locking & Filesystem Atomicity

ULTRON provides ACID-like transaction guarantees over standard POSIX filesystems without requiring a background database server.

```
                    Process A (Reader)               Process B (Writer)
                            |                                 |
                            v                                 v
                 fcntl.flock(LOCK_SH)              fcntl.flock(LOCK_EX)
                            |                                 |
                 [Concurrent Reads OK]               [Exclusive Lock]
                            |                                 |
                            |                       Write to Temp File
                            |                       (.tmp.<pid>.<rand>)
                            |                                 |
                            |                          flush() + fsync()
                            |                                 |
                            |                       os.replace() [Atomic]
                            |                                 |
                            v                                 v
                 fcntl.flock(LOCK_UN)              fcntl.flock(LOCK_UN)
```

### 4.1 POSIX File Locking (`fcntl.flock`)
The engine serializes concurrent access via `ultron/core/.runtime/.lock`:
- **Shared Lock (`fcntl.LOCK_SH`):** Acquired during read-only operations (`list_threads`, `get_thread`, `search`, `get_contacts`, `whois`, `get_team`, `list_teams`, `list_agents`, `stats`, `prepare_disable`). Multiple agents read concurrently without contention.
- **Exclusive Lock (`fcntl.LOCK_EX`):** Acquired during state-mutating operations (`register_prime`, `create_team`, `add_role`, `activate_team`, `activate_agent`, `disable_team`, `disable_agent`, `remove_team`, `create_thread`, `add_post`, `set_thread_status`, `reclassify_thread`, `verify(prune_orphans=True)`). Blocks all other concurrent reads and writes until completion.

### 4.2 Atomic Manifest & Session Writes (`atomic_write_json`)
To eliminate torn writes or corrupted state during power loss or abrupt process kills:
1. Data is serialized and written to a hidden temporary file located in the **same directory** as the target:
   ```text
   target:   ultron/hive/platform/team.json
   tempfile: ultron/hive/platform/.team.json.tmp.<pid>.<urandom>
   ```
   *Note: Creating the tempfile on the same physical filesystem ensures that the subsequent rename is an atomic inode operation.*
2. The process explicitly executes `f.flush()` followed by `os.fsync(f.fileno())` to guarantee write-through to physical non-volatile storage.
3. The file is swapped atomically using `os.replace(tmp_path, target_path)`.
4. A `finally:` block cleans up the temporary file if an unhandled exception occurs prior to replacement.

### 4.3 Atomic Log Appending (`append_jsonl_event`)
When appending new events to JSONL threads:
1. Target file is opened with mode `"a"` (`O_APPEND` flag at OS level).
2. The JSON event is formatted with compact single-line separators (`separators=(",", ":")`) terminated with a newline `\n`.
3. The file descriptor executes `f.flush()` and `os.fsync(f.fileno())` immediately, ensuring event durability before the function returns.

---

## 5. Lifecycle State Machine & Safety Invariants

```
                                  [ Unregistered ]
                                         |
                                         v create_team / add_role
                                   +------------+
                        +--------> |  DISABLED  | <--------+
                        |          +-----+------+          |
                        |                |                 |
                        |                | activate_team   |
      prepare-disable   |                v                 | External Branch
      + manage_subagents|          +------------+          | Checkout deleting
      + disable-team    +----------+   ACTIVE   |          | Hive team directory
                                   +------------+          |
                                         |                 |
                                         +-----------------+
                                         verify --prune-orphans
```

### 5.1 The Two-State Agent Lifecycle
Every role and team exists in one of two binary states:
- **`disabled`**: Persistent manifests (`team.json`, `role.json`, `AGENTS.md`) and scratch workspaces exist on disk, but no live subagent process is running. In `.runtime/sessions.json`, `status="disabled"` and `conversation_id=""`.
- **`active`**: An active background harness session is provisioned. In `.runtime/sessions.json`, `status="active"` and `conversation_id="<uuid>"`.

### 5.2 Provisioning & Activation Invariants
The engine enforces structural consistency across the organizational graph:
1. **Slug Validation Regex:** Team and role slugs must match:
   ```regex
   ^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$
   ```
   Reserved slugs (`ultron-prime`, `prime`, `teams`, `roles`, `workspace`, `core`, `hive`) are strictly rejected.
2. **Mandatory Team Lead:** Every team created via `create-team` automatically scaffolds `<team-slug>/lead`. Additional roles cannot be named `lead`.
3. **Hierarchical Activation Guard:** A child team cannot be activated if its parent team is currently `disabled` (failing loud with `ValueError`), unless `--allow-detached` is explicitly provided.
4. **Lead-First Specialist Activation:** A specialist cannot be activated if its `<team-slug>/lead` is `disabled` (failing loud with `ValueError`), unless `--allow-detached` is explicitly provided.
5. **Full Activation Completeness:** `activate-team` requires conversation UUIDs for **all** registered roles in the team. If any specialist UUID is omitted, activation fails loud unless `--partial` is explicitly passed.

### 5.3 Clean Deactivation ("Stand Down") Protocol
Standing down idle teams conserves harness memory and prevents unexpected background token consumption:
1. **Lead Deactivation Safety:** A Team Lead cannot be disabled while specialists in that team remain active.
2. **Subtree Deactivation Safety:** A parent team cannot be disabled while child teams remain active unless `--cascade` is passed.
3. **Three-Phase Stand-Down Execution:**
   - **Phase 1: Planning (`prepare-disable`):**
     `python3 ultron/core/core.py prepare-disable <team-slug> [--cascade] --json`  
     Validates dependencies and returns the exact list of `conversation_ids_to_kill`.
   - **Phase 2: Harness Termination:**
     ULTRON PRIME executes `manage_subagents(Action="kill", ConversationIds=[...])`.
   - **Phase 3: State Deregistration (`disable-team`):**
     `python3 ultron/core/core.py disable-team <team-slug> [--cascade]`  
     Updates `.runtime/sessions.json`, setting `status="disabled"` and clearing session UUIDs.
4. **Zero Data Loss:** Manifests, team charters, scratch directories, and message board histories remain intact on disk. Re-activation via `activate-team` instantly restores full operational context.

### 5.4 Ghost Session Purging & Self-Healing Across Git Checkouts
If a developer switches Git branches or runs `git checkout`, an entire team directory under `ultron/hive/` might disappear from the filesystem while its session entry lingers in the gitignored `.runtime/sessions.json`.
- **Fail-Loud Verification:** `core.verify()` cross-checks all runtime session entries against existing on-disk Hive manifests. If an unbacked session is detected, `verify()` fails loud:
  ```text
  ValueError: Found orphan runtime session(s) not present in Hive: ['ghost-team/lead']. Run 'verify --prune-orphans' to clean.
  ```
- **Self-Healing Pruning:** `python3 ultron/core/core.py verify --prune-orphans` purges orphan session keys from `sessions.json`.
- **Automatic Scaffolding Cleanup:** Calling `create_team` or `add_role` automatically sweeps and prunes any pre-existing stale session records matching the target slug prior to initialization.

---

## 6. Visibility Scoping & Authorization Matrix

ULTRON eliminates context saturation by enforcing strict visibility boundaries on all message board queries and mutations.

### 6.1 Visibility Scopes

```
+------------------------------------------------------------------------+
| GLOBAL SCOPE                                                           |
| Visible to: ALL agents in the network                                  |
|                                                                        |
|   +----------------------------------------------------------------+   |
|   | TEAM SCOPE (--team <A>)                                        |   |
|   | Visible to: Team A members + ULTRON PRIME                      |   |
|   |                                                                |   |
|   |   +--------------------------------------------------------+   |   |
|   |   | CROSS-LAYER HANDOFF (--team <A> --with-team <A1>)      |   |   |
|   |   | Visible to: Team A + Team A1 members + ULTRON PRIME    |   |   |
|   |   +--------------------------------------------------------+   |   |
|   |                                                                |   |
|   |   +--------------------------------------------------------+   |   |
|   |   | PERSONAL SCOPE (--author <A/coder>)                    |   |   |
|   |   | Visible to: ONLY <A/coder> + ULTRON PRIME              |   |   |
|   |   +--------------------------------------------------------+   |   |
|   +----------------------------------------------------------------+   |
+------------------------------------------------------------------------+
```

### 6.2 Granular Authorization Matrix

| Action | `personal` Thread | `team` Thread | `team` + `--with-team` | `global` Thread |
| :--- | :--- | :--- | :--- | :--- |
| **Creation** | Any registered agent (sets `owner_agent=author`) | Team Lead or team members of `team_slug`; Prime requires `--team` | Owning Team Lead or child Team Lead | Any agent; defaults to author's team |
| **Read (`list`, `view`)** | Thread Owner + `ultron-prime` | Members of `team_slug` + `ultron-prime` | Members of `team_slug` + `with_team` + `ultron-prime` | **All** agents across entire Hive |
| **Reply (`reply`)** | Thread Owner + `ultron-prime` | Members of `team_slug` + `ultron-prime` | Members of `team_slug` + `with_team` + `ultron-prime` | **All** agents across entire Hive |
| **Status Update (`set-status`)** | Thread Owner + `ultron-prime` | Members of `team_slug` + `ultron-prime` | Members of `team_slug` + `with_team` + `ultron-prime` | Any authorized agent |
| **Reclassify (`reclassify`)** | **`ultron-prime` only** | **`ultron-prime` only** | **`ultron-prime` only** | **`ultron-prime` only** |

### 6.3 Personal Memory Persistence Across Respawns
When a team is stood down and later respawned, the agents receive brand-new harness `conversation_id` UUIDs.

However, `personal` threads are keyed to the canonical `agent_id` (e.g., `docs/writer`), **not** the ephemeral session UUID. When `docs/writer` boots in a subsequent campaign, running:
```bash
python3 ultron/core/core.py list --as docs/writer --visibility personal
```
immediately returns all lessons, architectural decisions, and private notes recorded in prior sessions, ensuring true persistent organizational memory.

### 6.4 Cross-Layer Delegation (`--with-team`)
When Team Lead A delegates work to child Team Lead A1, using `--visibility team --team A --with-team A1`:
- Both Team A and Team A1 can view and reply to the thread.
- Sibling teams (Team B, Team C) and parent teams above A cannot see the thread.
- Information flows seamlessly across the hierarchy without creating noise on global channels.

### 6.5 Caller Identity Enforcement
Board read commands (`list`, `view`, `search`) strictly require caller identity via `--as <agent_id>` (or `ULTRON_AGENT_ID`). Missing identity raises `PermissionError`. The `--all` flag bypasses visibility filtering and is strictly restricted to `ultron-prime`.

---

## 7. The Reactive Doorbell Protocol

Because JSONL logs are passive datastores on disk, agents **never** poll in continuous while-loops. Inter-agent coordination follows the **Reactive Doorbell Protocol**:

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Prime as "ULTRON PRIME (abcb720d)"
    participant Lead as "docs/lead (04069c63)"
    participant Writer as "docs/writer (6dc4dd42)"
    participant Board as "ultron/core/threads (JSONL Storage)"

    User->>Prime: Instructs objective: Author Documentation
    Note over Prime: Prime deconstructs objective
    Prime->>Board: new-thread --team docs --visibility team ("Task: Author README...")
    Prime->>Prime: whois docs/lead --id-only -> resolves 04069c63
    Prime->>Lead: send_message(Recipient="04069c63", "Doorbell: Assigned Thread 567656f5...")
    Note over Lead: Antigravity wakes docs/lead reactively

    Lead->>Board: view 567656f5 --as docs/lead
    Note over Lead: Lead decomposes deliverables for writer
    Lead->>Lead: whois docs/writer --id-only -> resolves 6dc4dd42
    Lead->>Writer: send_message(Recipient="6dc4dd42", "Doorbell: Assigned Thread 567656f5...")
    Note over Writer: Antigravity wakes docs/writer reactively

    Writer->>Board: view 567656f5 --as docs/writer
    Note over Writer: Writer drafts README.md & docs/ARCHITECTURE.md
    Writer->>Board: reply 567656f5 --author docs/writer ("Deliverables complete...")
    Writer->>Lead: send_message(Recipient="04069c63", "Doorbell: Deliverables ready for review...")
    Note over Lead: Antigravity wakes docs/lead reactively

    Lead->>Board: view 567656f5 --as docs/lead
    Note over Lead: Lead conducts skeptical Tier-2 review
    Lead->>Board: set-status 567656f5 resolved --as docs/lead
    Lead->>Prime: send_message(Recipient="abcb720d", "Objective Complete: Verified docs...")
    Note over Prime: Antigravity wakes ULTRON PRIME reactively

    Prime->>User: Reports milestone completion
```

### Doorbell Step-by-Step Rule:
1. **Write to Datastore:** Agent appends post or status change via `python3 ultron/core/core.py new-thread` or `reply`.
2. **Resolve Recipient UUID:**
   ```bash
   python3 ultron/core/core.py whois <target_agent_id> --id-only
   ```
   *Note: If the target agent is disabled, this command writes nothing to stdout, outputs an error message to stderr, and exits with code 1, immediately informing the caller that the recipient must be activated first.*
3. **Trigger Reactive Wakeup:** Call harness `send_message(Recipient="<resolved_uuid>", Message="Doorbell: ...")`.
4. **End Turn Immediately:** Once the doorbell message is dispatched, the sending agent calls no more tools and yields execution. The Antigravity harness automatically wakes the recipient, and will subsequently resume the sender when a return doorbell arrives.

---

## 8. Verification & Test Suite Architecture

The ULTRON Core engine includes a comprehensive, automated test suite located at [`tests/test_ultron_core.py`](../tests/test_ultron_core.py).

### Covered Invariants:
1. **Zero-State Initialization:** Validates clean stats, zero teams, and `.gitattributes` presence.
2. **Arbitrary N-Layer Hive Scaffolding:** Validates nesting up to 6+ layers, verifying lineage arrays, relative POSIX paths, and zero absolute path leakage.
3. **Repository Relocation Invariance:** Clones a populated Hive into a completely separate temporary directory and verifies that `UltronCore` loads immediately without rebuild.
4. **Harness Brace Safety:** Verifies single-pass template substitution safe against literal braces (`{"strict": true}`) in team charters.
5. **Lifecycle State Machine:** Verifies parent-before-child, lead-before-specialist, and cascade deactivation rules.
6. **Append-Only JSONL Event Folding:** Verifies that existing event lines are never mutated, short IDs resolve cleanly, and events fold deterministically.
7. **Visibility Isolation:** Tests four roles (`team-a/lead`, `team-a/coder`, `team-a1/lead`, `team-b/lead`) to prove unauthorized reads, searches, and replies are strictly rejected.
8. **Real Git Union Merging (`test_real_git_branch_union_merge_conflict_free`):**
   Initializes a real Git repository, creates two divergent branches (`branch-a` and `branch-b`), concurrently appends replies and status changes to the *exact same* thread file, and executes `git merge`. Asserts zero merge conflicts, 100% preservation of posts, and deterministic status resolution.
9. **Ghost Session Purging:** Simulates external branch checkouts deleting Hive folders and validates fail-loud detection and `--prune-orphans` healing.

Run the test suite anytime:
```bash
python3 -W error -m unittest discover -s tests -v
```

---

## 9. Extensibility & Portability Guide

### 9.1 Operating on Google Antigravity (`agy`)
In Antigravity:
- ULTRON PRIME operates in the root session.
- Subagents are defined using `define_subagent` and started using `invoke_subagent`.
- Sessions communicate reactively using `send_message`.
- Session monitoring and teardown are managed using `manage_subagents`.

### 9.2 Porting to Claude Code & Other CLI Harnesses
ULTRON is designed to be harness-agnostic:
- **Registry & Datastore:** `python3 ultron/core/core.py` runs anywhere Python 3.10+ is available.
- **Session Mapping:** Replace `define_subagent` / `invoke_subagent` with the host runtime's task launcher (e.g., Claude Code sub-sessions or background processes).
- **Doorbell Mapping:** Replace Antigravity's `send_message` with named pipe signals, socket notifications, or subshell prompts.
- **Durability:** Because the entire organizational graph, role charters, and message threads live in Git, porting to any new runtime requires zero schema translation.
