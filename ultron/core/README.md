# ULTRON Core & Hive Reference (`ultron/`)

`ultron/` is the self-contained coordination engine (`ultron/core/`) and organization tree (`ultron/hive/`) for **ULTRON** (*Universal Layered Team and Role Orchestration Network*).

---

## 1. Directory Structure

```text
ultron/
├── core/
│   ├── ULTRON_PRIME.md          # Boot persona & operational manual for ULTRON PRIME
│   ├── README.md                # This reference guide
│   ├── core.py                  # Org registry, N-layer Hive scaffolder & message board CLI
│   ├── .gitignore               # Ignores local SQLite runtime files (*.db*)
│   ├── templates/               # Scaffolding templates for teams, roles & spawn prompts
│   ├── teams.json               # Git-tracked N-layer org tree & team lifecycle states
│   ├── agents.json              # Git-tracked role definitions & live session UUIDs
│   └── threads/                 # Git-tracked message board threads (thread_XXXX.json)
└── hive/
    └── <team-slug>/             # Layer-1 team
        ├── team.json            # Team metadata & status (active / disabled)
        ├── AGENTS.md            # Team charter & shared operating rules
        ├── roles/               # Flat peer roles (always includes lead/)
        │   ├── lead/
        │   │   ├── AGENTS.md
        │   │   └── workspace/   # Private scratch directory for <team>/lead
        │   └── <role-slug>/
        │       ├── AGENTS.md
        │       └── workspace/   # Private scratch directory for <team>/<role>
        └── teams/               # Recursive child teams (arbitrary Layer 2..N depth)
            └── <subteam-slug>/
```

---

## 2. Visibility Model (Preventing Information Overload)

Every thread on the central message board carries an explicit `visibility` scope enforced on `list`, `view`, `search`, and `reply`:

| Visibility | Flags | Who Can Read & Reply | Primary Use Case |
| :--- | :--- | :--- | :--- |
| **`personal`** | `--visibility personal` | Only `<team>/<role>` (keyed to canonical `agent_id`, surviving session kills/respawns) + `ultron-prime` | Role-specific technical lessons and private working notes |
| **`team`** | `--visibility team` (optional `--with-team <other>`) | All roles in `team_slug` (plus `with_team` when set) + `ultron-prime` | Intra-team tasks, code reviews, team lessons, and parent↔child team handoffs/escalations |
| **`global`** | `--visibility global` | Every agent in the Hive | Network-wide architectural standards and cross-org announcements |

- **Mandatory Caller Identity on Reads:** Always pass `--as <team>/<role>` (or set `ULTRON_AGENT_ID`). `--all` is reserved for `ultron-prime` / board curation.
- **Reclassification:** `ultron-prime` can promote, narrow, or re-scope any thread via `reclassify`.

---

## 3. Reactive Doorbell Workflow

SQLite (`core.db`) and JSON files are passive datastores—agents never poll in loops. Always follow the 3-step collaboration rule:

1. **Write to Board:** Post or reply via `python3 ultron/core/core.py new-thread ...` or `reply ...`.
2. **Resolve Live UUID:**
   ```bash
   python3 ultron/core/core.py whois <target-team>/<role> --id-only
   ```
   *(Exits non-zero to `stderr` with empty `stdout` if the target agent is currently `disabled`.)*
3. **Doorbell:** Wake the recipient immediately via Antigravity's `send_message(Recipient="<uuid>", Message="Doorbell: Posted on Thread #X ('Title')...")`.

---

## 4. CLI Quick Reference (`python3 ultron/core/core.py`)

Add `--json` to any command (before or after the subcommand) for structured JSON output.

### Organization & Lifecycle Commands (ULTRON PRIME)
```bash
# Register ULTRON PRIME session
python3 ultron/core/core.py register-prime --id "<uuid>"

# Inspect full N-layer Hive org tree & stats
python3 ultron/core/core.py org-tree
python3 ultron/core/core.py stats

# Create teams (Layer 1 or nested Layer 2..N via --parent) & specialist roles
python3 ultron/core/core.py create-team --slug api --name "API Team" --mission "REST & RPC endpoints"
python3 ultron/core/core.py add-role --team api --role coder --title "API Developer" --responsibilities "Implement endpoints"
python3 ultron/core/core.py create-team --slug auth --parent api --name "Auth Subteam" --mission "Token verification"

# Generate Antigravity define_subagent + invoke_subagent payloads
python3 ultron/core/core.py render-spawn api --json

# Bind spawned session UUIDs & mark team active
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
# Create personal, team, cross-layer (with-team), or global threads
python3 ultron/core/core.py new-thread \
  --author api/coder \
  --visibility personal \
  --category lesson \
  --title "SQLite WAL Locking Note" \
  --content "Close sqlite3 connections explicitly in context managers to avoid Python 3.14 ResourceWarnings."

python3 ultron/core/core.py new-thread \
  --author api/lead \
  --visibility team \
  --with-team auth \
  --category task \
  --title "JWT Claims Contract" \
  --content "Align on token payload fields before endpoint integration."

# Reply, list, view, search, update status, and reclassify
python3 ultron/core/core.py reply 2 --author auth/lead --content "Validated claims schema."
python3 ultron/core/core.py list --as api/coder
python3 ultron/core/core.py view 2 --as auth/lead
python3 ultron/core/core.py search "JWT" --as auth/lead
python3 ultron/core/core.py set-status 2 resolved --as api/lead
python3 ultron/core/core.py reclassify 1 --visibility global
```
