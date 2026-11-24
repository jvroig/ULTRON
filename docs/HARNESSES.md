# Harnesses

The operator's per-harness reference. The design (harness selection, adapter contract, role context
delivery, mixed hives, shell doorbell) is in [ARCHITECTURE.md §7.2 and §8](ARCHITECTURE.md#8-harness-layer).

## Actions per harness

| Action | `claude-code` | `antigravity` |
|---|---|---|
| Prime's doorbell address | its session name (`ListAgents` prints "This session is …") | its Conversation ID from `<user_information>` (and `@coordinator` on the swarm board) |
| Doorbell, same harness | `SendMessage` with `to` = address | `post_message(text="@<swarm_name> ...")` (resolve handle via `whois <agent> --swarm-name`; `@coordinator` for Prime) |
| Doorbell, any harness | `core.py doorbell <agent> "<msg>" --from <you>` | same (`agentapi send-message <conversation_id>`) |
| Spawn a team | `spawn-team` launches and binds every role | `spawn-team` writes `role_context.generated.md` and prints a plan: `swarm(**spec['swarm_add'])` per spec, then `activate-team` with the returned `conversation_id` UUIDs |
| Stop a team | `stop-team` stops every session and disables the team | `stop-team` prints a plan: `swarm(action="kill", name=...)` per worker, then `disable-team`; the team stays active until then |
| Check roles are running | `liveness [team]` checks `claude agents --json`; exits 1 if a role is gone | `liveness` prints a plan: `swarm(action="status")` |
| Safety heartbeat | `CronCreate` | `schedule` |
| Model tiers `small` / `medium` / `large` | haiku / sonnet / opus | `gemini-4-hydrogen-medium` / `inherit` / `gemini-4-argon-medium` (plus any explicit `swarm` model ID via `--model` or `set-model`) |

## Claude Code requirements

- **The ULTRON folder is trusted** in Claude Code. Role folders inherit that trust.
- **No `CLAUDE.md` or `CLAUDE.local.md`** in any role folder or above it. Either one makes Claude
  Code ignore every `AGENTS.md`. `spawn-team` refuses to launch if one exists.
- **Prime runs with permissions bypassed**, like the roles. Messages between sessions in different
  permission modes are held for approval.
- **Signed in:** every role and every Claude Code shell doorbell is a Claude call. `spawn-team`
  validates login status via `claude auth status` and warns if login expiry is within 48 hours.
  Renew with `claude auth login`, or use `claude setup-token` for unattended hives.
- `workspace_mode: branch` is not supported yet.

Sessions are named `ultron--<team>--<role>`; that name is the role's doorbell address.

## Antigravity requirements

- **Shell doorbell:** `agentapi` on `PATH` or at `~/.gemini/antigravity/bin/agentapi`, and a running
  Antigravity (a `~/.gemini/antigravity/daemon/hub_*.json` with a live `pid`).
- **Liveness probing:** Shell-based probes (`core.py liveness`, `core.py directory`) report `unknown`
  for Antigravity roles because `agentapi` does not expose a conversation/subagent listing command
  (it only supports `get-conversation-metadata`, `new-conversation`, and `send-message`). Within an
  Antigravity Prime conversation, live worker status (`waiting`, `working`, `stopped`, `killed`) is
  inspected using `swarm(action="status")`.
- An Antigravity team is spawned by an Antigravity Prime only.
- **Swarm roster names & role context:** Each role maps deterministically to a `<= 24`-char
  `swarm` roster name (`@<swarm_name>`, surfaced in `whois --swarm-name` and `directory`). Full
  charters are written to `<role_dir>/role_context.generated.md` so public swarm briefs stay short.
- **Model mapping & explicit IDs:** Antigravity's `swarm` adapter maps portable tiers to
  `small -> gemini-4-hydrogen-medium`, `medium -> inherit` (omits `model` so workers follow Prime's
  active model), and `large -> gemini-4-argon-medium`. Any explicit model ID from
  `swarm(action="models", all=true)` (e.g. `gemini-4-argon-high`, `gemini-4-neon-xhigh`,
  `claude-opus-5-5-high`) can also be passed via `--model` or updated with `core.py set-model`.
  Live waiting workers can be hot-switched via `swarm(action="model", name=..., model=...)`.

## Mixed hives

Both harnesses on one machine. Before spawning Claude Code roles from an Antigravity shell, check
`ps eww` for a `claude daemon`: one started from that shell passes its `ANTIGRAVITY_*` variables to
every role.
