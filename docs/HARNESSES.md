# Harnesses

The operator's per-harness reference. The design (harness selection, adapter contract, role context
delivery, mixed hives, shell doorbell) is in [ARCHITECTURE.md §7.2 and §8](ARCHITECTURE.md#8-harness-layer).

## Actions per harness

| Action | `claude-code` | `antigravity` |
|---|---|---|
| Prime's doorbell address | its session name (`ListAgents` prints "This session is …") | its Conversation ID from `<user_information>` |
| Doorbell, same harness | `SendMessage` with `to` = address | `send_message(Recipient=<address>, Message=…)` |
| Doorbell, any harness | `core.py doorbell <agent> "<msg>" --from <you>` | same |
| Spawn a team | `spawn-team` launches and binds every role | `spawn-team` prints a plan: `define_subagent` + `invoke_subagent` per spec, then `activate-team` |
| Stop a team | `stop-team` stops every session and disables the team | `stop-team` prints a plan: `manage_subagents(Action="kill")`, then `disable-team`; the team stays active until then |
| Check roles are running | `liveness [team]` checks `claude agents --json`; exits 1 if a role is gone | `liveness` prints a plan: `manage_subagents(Action="list")` |
| Safety heartbeat | `CronCreate` | `schedule` |
| Model tiers `small` / `medium` / `large` | haiku / sonnet / opus | flash_lite / flash / pro |

## Claude Code requirements

- **The ULTRON folder is trusted** in Claude Code. Role folders inherit that trust.
- **No `CLAUDE.md` or `CLAUDE.local.md`** in any role folder or above it. Either one makes Claude
  Code ignore every `AGENTS.md`. `spawn-team` refuses to launch if one exists.
- **Prime runs with permissions bypassed**, like the roles. Messages between sessions in different
  permission modes are held for approval.
- **Signed in:** every role and every Claude Code shell doorbell is a Claude call. Renew with
  `claude auth login`, or use `claude setup-token` for unattended hives.
- `workspace_mode: branch` is not supported yet.

Sessions are named `ultron--<team>--<role>`; that name is the role's doorbell address.

## Antigravity requirements

- **Shell doorbell:** `agentapi` on `PATH` or at `~/.gemini/antigravity/bin/agentapi`, and a running
  Antigravity (a `~/.gemini/antigravity/daemon/hub_*.json` with a live `pid`).
- An Antigravity team is spawned by an Antigravity Prime only.

## Mixed hives

Both harnesses on one machine. Before spawning Claude Code roles from an Antigravity shell, check
`ps eww` for a `claude daemon`: one started from that shell passes its `ANTIGRAVITY_*` variables to
every role.
