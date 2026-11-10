# Harnesses

ULTRON's core (registry, board, lifecycle state, role context) names no agent harness. Each
supported harness has an adapter in `ultron/core/core.py` (`HarnessAdapter` subclasses).

## Which harness is used

`render-spawn`, `register-prime` and `activate-team` pick the harness from, in order:

1. `--harness <name>`
2. `$ULTRON_HARNESS`
3. auto-detection: `$ANTIGRAVITY_AGENT` or `$ANTIGRAVITY_CONVERSATION_ID` set ⇒ `antigravity`;
   `$CLAUDE_CODE_SESSION_ID` set ⇒ `claude-code`
4. the harness Prime registered with

If none applies, the command fails and names the options. `spawn-team` uses the team's `harness`
first (see *Mixed hives*). `stop-team`, `liveness` and `doorbell` use the harness each agent was
activated on.

## Actions per harness

| Action | `claude-code` | `antigravity` |
|---|---|---|
| Prime's doorbell address | its session name (`ListAgents` prints "This session is …") | its Conversation ID from `<user_information>` |
| Doorbell | `SendMessage` with `to` = address | `send_message(Recipient=<address>, Message=…)` |
| Spawn a team | `spawn-team` launches and binds every role | `spawn-team` prints a plan: `define_subagent` + `invoke_subagent` per spec, then `activate-team` |
| Stop a team | `stop-team` stops every session and disables the team | `stop-team` prints a plan: `manage_subagents(Action="kill")`, then `disable-team` |
| Check roles are running | `liveness [team]` checks `claude agents --json`; exits 1 if a role is gone | `liveness` prints a plan: `manage_subagents(Action="list")` |
| Safety heartbeat | `CronCreate` | `schedule` |
| Model tiers `small` / `medium` / `large` | haiku / sonnet / opus | flash_lite / flash / pro |

## Mixed hives

Teams can run on different harnesses (`create-team --harness`, `set-harness <team> <harness>`; no
harness means Prime's). Requirements:
- **One machine.** Both shell doorbells are local (a local socket for Claude Code, `localhost` for
  Antigravity).
- **Prime can launch the team's harness.** A Claude Code team can be spawned by any Prime, since it starts
  from the CLI. An Antigravity team needs an Antigravity Prime.
- `stop-team --cascade` refuses a subtree that spans harnesses; stop the child teams first.

`doorbell <agent_id> "<msg>" [--from <id>]` wakes an agent on any harness from a shell:

| Target harness | Delivery |
|---|---|
| `claude-code` | headless `claude -p --tools SendMessage --model haiku` (~5 s, one small model call; fails unless it confirms `sent`) |
| `antigravity` | `agentapi send-message <uuid> <msg>`, with the daemon address and token from the newest `~/.gemini/antigravity/daemon/hub_*.json` whose pid is alive (passed in env, never argv) |

Roles use their native doorbell inside their team and `doorbell` for anyone outside it.

## Claude Code

Each role is a background session (`claude --bg`) whose working directory is its role folder.
Its charters arrive through the `AGENTS.md` chain (root → team → role); its identity, routing and
CLI path arrive through `role_context.generated.md`, imported by the role's `AGENTS.md`.

Requirements:
- **The ULTRON folder is trusted** in Claude Code. Role folders inherit that trust.
- **No `CLAUDE.md` or `CLAUDE.local.md`** in any role folder or above it. Either one makes Claude
  Code ignore every `AGENTS.md`. `spawn-team` refuses to launch if one exists.
- **Prime runs with permissions bypassed**, like the roles. Messages between sessions in different
  permission modes are held for approval.
- `workspace_mode: branch` is not supported yet.

`spawn-team` writes two gitignored files into each role folder: `role_context.generated.md` and
`.claude/settings.json` (`worktree.bgIsolation: none`, so roles can edit the shared checkout; the
`Agent` / `claude` deny rules; `env` with the role's `ULTRON_AGENT_ID` and `ULTRON_HARNESS`).
Sessions are named `ultron--<team>--<role>`; that name is the role's doorbell address.

## Antigravity

Roles are Antigravity subagents. `render-spawn <team> --json` (also inside `spawn-team`'s plan)
returns `define_subagent` / `invoke_subagent` payloads whose system prompt carries the role context
and all charters. Prime binds the returned conversation UUIDs with `activate-team`. `stop-team` prints a plan;
the team stays active until Prime runs `disable-team`.

## Adding a harness

Subclass `HarnessAdapter` and register it in `HARNESS_ADAPTERS`. An adapter supplies tool names,
the tier → model map, how role context is delivered (`build_spec`), `spawn` / `stop` / `probe`
(performed, or returned as a plan for Prime), `shell_doorbell`, `launches_from_cli`, and the doorbell address and call. A harness without a way for one
session to wake another cannot host ULTRON, because agents never poll.

`HarnessAdapterContractTestCase` in `tests/test_ultron_core.py` runs against every adapter. Add the
new harness's foreign tool names there.
