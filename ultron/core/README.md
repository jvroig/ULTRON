# ULTRON Core & Hive Reference (`ultron/`)

`ultron/` is the self-contained, **pure Git-native** coordination engine (`ultron/core/`) and organization tree (`ultron/hive/`) for **ULTRON** (*Universal Layered Team and Role Orchestration Network*). Zero SQLite or third-party dependencies are required.

---

## 1. Directory & Storage Architecture

```text
ultron/
├── core/
│   ├── ULTRON_PRIME.md          # Boot persona & operational manual for ULTRON PRIME
│   ├── README.md                # This reference guide
│   ├── core.py                  # Pure Git-native org registry, Hive scaffolder & JSONL board CLI
│   ├── .gitignore               # Ignores ephemeral .runtime/ session UUIDs & lockfiles
│   ├── templates/               # Scaffolding templates for teams, roles & spawn prompts
│   ├── .runtime/                # GITIGNORED ephemeral runtime state (sessions.json, .lock)
│   └── threads/                 # Git-tracked append-only JSONL threads
│       ├── .gitattributes       # `*.jsonl merge=union` for conflict-free Git branch merges
│       └── t-YYYYMMDD-xxxxxxxx.jsonl
└── hive/
    └── <team-slug>/             # Layer-1 team
        ├── team.json            # Git-tracked persistent team definition
        ├── AGENTS.md            # Team charter & shared operating rules
        ├── roles/               # Flat peer roles (always includes lead/)
        │   ├── lead/
        │   │   ├── role.json    # Git-tracked persistent role definition
        │   │   ├── AGENTS.md
        │   │   └── workspace/   # Private scratch directory for <team>/lead
        │   └── <role-slug>/
        │       ├── role.json
        │       ├── AGENTS.md
        │       └── workspace/   # Private scratch directory for <team>/<role>
        └── teams/               # Recursive child teams (arbitrary Layer 2..N depth)
            └── <subteam-slug>/
```

### Why This Is Natively Git-Friendly
1. **Single Source of Truth:** On-disk files *are* the database—switching Git branches or copying `ultron/` into any repository reflects the exact state immediately with zero sync/restore ceremony.
2. **Conflict-Free Branch Merges (`merge=union`):** Every thread (`t-YYYYMMDD-xxxxxxxx.jsonl`, collision-free IDs; CLI accepts full IDs or short suffixes like `xxxxxxxx`) is an **append-only event log** (`thread`, `post`, `status`, `reclassify`). With `*.jsonl merge=union` in `threads/.gitattributes`, concurrent replies or status updates across Git branches merge cleanly with zero conflicts and replay deterministically by timestamp.
3. **Clean Working Trees on Team Wake/Sleep:** Ephemeral Antigravity `conversation_id` bindings live in gitignored `ultron/core/.runtime/sessions.json`, so `activate-team` and `disable-team` never dirty `git status`.

---

## 2. Visibility Model (Preventing Information Overload)

Every thread carries an explicit `visibility` scope enforced on `list`, `view`, `search`, `reply`, and `set-status`:

| Visibility | Flags | Who Can Read & Reply | Primary Use Case |
| :--- | :--- | :--- | :--- |
| **`personal`** | `--visibility personal` | Only `<team>/<role>` (keyed to canonical `agent_id`, surviving session kills/respawns) + `ultron-prime` | Role-specific technical lessons and private working notes |
| **`team`** | `--visibility team` (optional `--with-team <other>`) | All roles in `team_slug` (plus `with_team` when set) + `ultron-prime` | Intra-team tasks, code reviews, team lessons, and parent↔child team handoffs/escalations |
| **`global`** | `--visibility global` | Every agent in the Hive | Network-wide architectural standards and cross-org announcements |

- **Mandatory Caller Identity on Reads:** Always pass `--as <team>/<role>` (or set `ULTRON_AGENT_ID`). `--all` is reserved for `ultron-prime` / board curation.
- **Reclassification:** `ultron-prime` can promote, narrow, or re-scope any thread via `reclassify`.

---

## 3. Reactive Doorbell Workflow

JSONL files are passive datastores—agents never poll in loops. Always follow the 3-step collaboration rule:

1. **Write to Board:** Post or reply via `python3 ultron/core/core.py new-thread ...` or `reply ...`.
2. **Resolve Live UUID:**
   ```bash
   python3 ultron/core/core.py whois <target-team>/<role> --id-only
   ```
   *(Exits non-zero to `stderr` with empty `stdout` if the target agent is currently `disabled`.)*
3. **Doorbell:** Wake the recipient immediately via Antigravity's `send_message(Recipient="<uuid>", Message="Doorbell: Posted on Thread <thread_id> ('Title')...")`.

---

## 4. CLI Quick Reference (`python3 ultron/core/core.py`)

Add `--json` to any command (before or after the subcommand) for structured JSON output. Thread commands accept either the full `t-YYYYMMDD-xxxxxxxx` ID or its unique short hex suffix (`xxxxxxxx`).

### Organization & Lifecycle Commands (ULTRON PRIME)
```bash
# Register ULTRON PRIME session
python3 ultron/core/core.py register-prime --id "<uuid>"

# Inspect full N-layer Hive org tree, integrity & stats
python3 ultron/core/core.py org-tree
python3 ultron/core/core.py verify
python3 ultron/core/core.py stats

# Create teams (Layer 1 or nested Layer 2..N via --parent) & specialist roles
python3 ultron/core/core.py create-team --slug api --name "API Team" --mission "REST & RPC endpoints"
python3 ultron/core/core.py add-role --team api --role coder --title "API Developer" --responsibilities "Implement endpoints"
python3 ultron/core/core.py create-team --slug auth --parent api --name "Auth Subteam" --mission "Token verification"

# Generate Antigravity define_subagent + invoke_subagent payloads
python3 ultron/core/core.py render-spawn api --json

# Bind spawned session UUIDs & mark team active (writes only to gitignored .runtime/sessions.json)
python3 ultron/core/core.py activate-team api --uuids '{"lead":"<uuid-1>","coder":"<uuid-2>"}'

# Prepare & execute team disable (kills sessions via manage_subagents first, preserves files/threads)
python3 ultron/core/core.py prepare-disable api --cascade --json
python3 ultron/core/core.py disable-team api --cascade
```

### Discovery & Chain-of-Command Commands (All Agents)
```bash
# Check allowed chain-of-command contacts (superior, teammates, child leads)
python3 ultron/core/core.py contacts api/lead

# Resolve active agent UUID
python3 ultron/core/core.py whois api/lead --id-only

# List registered roles
python3 ultron/core/core.py agents --team api
```

### Message Board Commands
```bash
# Create personal, team, cross-layer (with-team), or global JSONL threads
python3 ultron/core/core.py new-thread \
  --author api/coder \
  --visibility personal \
  --category lesson \
  --title "Append-Only JSONL Locking Note" \
  --content "Use fcntl.flock + fsync when appending JSONL event lines."

python3 ultron/core/core.py new-thread \
  --author api/lead \
  --visibility team \
  --with-team auth \
  --category task \
  --title "JWT Claims Contract" \
  --content "Align on token payload fields before endpoint integration."

# Reply, list, view, search, update status, and reclassify (accepts full ID or short suffix)
python3 ultron/core/core.py reply a3f91c4e --author auth/lead --content "Validated claims schema."
python3 ultron/core/core.py list --as api/coder
python3 ultron/core/core.py view a3f91c4e --as auth/lead
python3 ultron/core/core.py search "JWT" --as auth/lead
python3 ultron/core/core.py set-status a3f91c4e resolved --as api/lead
python3 ultron/core/core.py reclassify a3f91c4e --as ultron-prime --visibility global
```
