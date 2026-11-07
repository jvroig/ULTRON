# ULTRON

**Universal Layered Team and Role Orchestration Network (ULTRON)** is a custom orchestration framework for agentic AI, geared towards high autonomy.

ULTRON is designed to work on top of agentic harnesses such as Google's Antigravity CLI (`agy`) and Claude Code.

## Architecture

*(See [`ultron-architecture.html`](ultron-architecture.html) for the visual architecture summary and [`ultron/core/README.md`](ultron/core/README.md) for the CLI & schema reference.)*

| Concept | Role in ULTRON |
| :--- | :--- |
| **ULTRON PRIME** | *Ultimate Leader of Teams, Roles, and Operational Nodes.* Single point of contact with the User; sole authority to create, enable (spawn), and disable (stand down) teams and roles. |
| **Teams as Unit of Work** | Work is organized into structured teams rather than ad-hoc individual agents. |
| **Flat Intra-Team Roles** | Each team contains peer specialist roles (`coder`, `designer`, `reviewer`, etc.) plus a mandatory `lead` role responsible for internal coordination and external communication. |
| **Arbitrary `N`-Layer Hive** | Teams arrange into an arbitrary-depth org tree (`Layer 1..N`) under `ultron/hive/`. Reporting, blockers, and lifecycle requests escalate upward along the chain of command. |
| **Visibility-Scoped Board** | Shared SQLite + Git-backed JSON message board (`ultron/core/core.py`) with `personal` (role-persistent across respawns), `team` (intra-team & `--with-team` parent/child handoffs), and `global` visibility tiers to prevent context overload. |
| **Dynamic Lifecycle Conservation** | Idle teams with no immediate tasks can be cleanly stood down by ULTRON PRIME (`manage_subagents` kill + `disable-team`) while preserving their Hive charters and board memory on disk for instant future re-activation. |

### Repository Layout

```text
ULTRON/
├── AGENTS.md                    # Neutral workspace engineering rules
├── ultron-architecture.html     # Visual architecture overview
├── ultron/                      # Portable drop-in ULTRON framework folder
│   ├── core/                    # Registry, scaffolder, message board CLI & ULTRON_PRIME.md
│   └── hive/                    # Recursive N-layer organization tree of teams & roles
└── tests/
    └── test_ultron_core.py      # Automated unit & integration test suite
```

## Quickstart (Antigravity)

1. Launch `agy` in this repository.
2. To operate as **ULTRON PRIME**, instruct the session:
   ```text
   load ultron/core/ULTRON_PRIME.md
   ```
3. Run the automated verification suite anytime:
   ```bash
   python3 -W error -m unittest discover -s tests -v
   ```
