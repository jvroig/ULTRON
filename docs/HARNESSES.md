# Harnesses

ULTRON's core (registry, board, lifecycle state, role context) names no agent harness. Each
supported harness has an adapter in `ultron/core/core.py` (`HarnessAdapter` subclasses).

## Which harness is used

`spawn-team`, `stop-team`, `render-spawn`, `activate-team` and `register-prime` pick the harness
from, in order:

1. `--harness <name>`
2. `$ULTRON_HARNESS`
3. auto-detection: `$ANTIGRAVITY_AGENT` or `$ANTIGRAVITY_CONVERSATION_ID` set ⇒ `antigravity`;
   `$CLAUDE_CODE_SESSION_ID` set ⇒ `claude-code`
4. the harness Prime registered with

If none applies, the command fails and names the options. `spawn-team` refuses a harness other than
the one Prime registered with: sessions on different harnesses cannot doorbell each other.

## Actions per harness

| Action | `claude-code` | `antigravity` |
|---|---|---|
| Prime's doorbell address | its session name (`ListAgents` prints "This session is …") | its Conversation ID from `<user_information>` |
| Doorbell | `SendMessage` with `to` = address | `send_message(Recipient=<address>, Message=…)` |
| Spawn a team | `spawn-team` launches and binds every role | `spawn-team` prints a plan: `define_subagent` + `invoke_subagent` per spec, then `activate-team` |
| Stop a team | `stop-team` stops every session and disables the team | `stop-team` prints a plan: `manage_subagents(Action="kill")`, then `disable-team` |
| List live sessions | `claude agents` | `manage_subagents(Action="list")` |
| Safety heartbeat | `CronCreate` | `schedule` |
| Model tiers `small` / `medium` / `large` | haiku / sonnet / opus | flash_lite / flash / pro |

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
`.claude/settings.json` (`worktree.bgIsolation: none`, so roles can edit the shared checkout).
Sessions are named `ultron--<team>--<role>`; that name is the role's doorbell address.

## Antigravity

Roles are Antigravity subagents. `render-spawn <team> --json` (also inside `spawn-team`'s plan)
returns `define_subagent` / `invoke_subagent` payloads whose system prompt carries the role context
and all charters. Prime binds the returned conversation UUIDs with `activate-team`. `stop-team` prints a plan;
the team stays active until Prime runs `disable-team`.

## Adding a harness

Subclass `HarnessAdapter` and register it in `HARNESS_ADAPTERS`. An adapter supplies tool names,
the tier → model map, how role context is delivered (`build_spec`), `spawn` / `stop` (performed, or
returned as a plan for Prime), and the doorbell address and call. A harness without a way for one
session to wake another cannot host ULTRON, because agents never poll.

`HarnessAdapterContractTestCase` in `tests/test_ultron_core.py` runs against every adapter. Add the
new harness's foreign tool names there.
