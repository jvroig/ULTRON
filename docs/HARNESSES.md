# Harnesses

The operator's per-harness reference. The design (harness selection, adapter contract, role context
delivery, mixed hives, shell doorbell) is in [ARCHITECTURE.md §7.2 and §8](ARCHITECTURE.md#8-harness-layer).

## Actions per harness

| Action | `claude-code` | `antigravity` | `opencode` |
|---|---|---|---|
| Prime's doorbell address | its session name (`ListAgents` prints "This session is …") | its Conversation ID from `<user_information>` (and `@coordinator` on the swarm board) | its OpenCode session ID (`ses_...`, from `opencode session list --format json` or `GET /session`) |
| Doorbell, same harness | `SendMessage` with `to` = address | `post_message(text="@<swarm_name> ...")` (resolve handle via `whois <agent> --swarm-name`; `@coordinator` for Prime) | `core.py doorbell <agent> "<msg>" --from <you>` (`POST /session/{sid}/prompt_async`) |
| Doorbell, any harness | `core.py doorbell <agent> "<msg>" --from <you>` | same (`agentapi send-message <conversation_id>`) | same (`POST /session/{sid}/prompt_async`) |
| Spawn a team | `spawn-team` launches and binds every role | `spawn-team` writes `role_context.generated.md` and prints a plan: `swarm(**spec['swarm_add'])` per spec, then `activate-team` with the returned `conversation_id` UUIDs | `spawn-team` writes `role_context.generated.md`, creates sessions via `POST /session` + `prompt_async`, and binds every role |
| Stop a team | `stop-team` stops every session and disables the team | `stop-team` prints a plan: `swarm(action="kill", name=...)` per worker, then `disable-team`; the team stays active until then | `stop-team` aborts & deletes every session (`POST /abort` + `DELETE`) and disables the team |
| Check roles are running | `liveness [team]` checks `claude agents --json`; exits 1 if a role is gone | `liveness` prints a plan: `swarm(action="status")` | `liveness [team]` checks `GET /experimental/session` + `/session/status`; exits 1 if a role is gone |
| Safety heartbeat | `CronCreate` | `schedule` | host-side cron/timer calling `core.py doorbell ultron-prime "..."` (roles monitored by Prime's Safety Cron) |
| Model tiers `small` / `medium` / `large` | haiku / sonnet / opus | `gemini-4-hydrogen-medium` / `inherit` / `gemini-4-argon-medium` (plus any explicit `swarm` model ID via `--model` or `set-model`) | explicit `provider/model` (e.g. `ollama/qwen3-coder:32b`), `inherit` (`opencode.json` default), or `ULTRON_OPENCODE_MODEL_{SMALL,MEDIUM,LARGE}` (fails loud if unset) |

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

## OpenCode requirements

- **Connect-only headless server (`opencode serve`):** ULTRON connects to an already-running OpenCode
  HTTP server at `ULTRON_OPENCODE_URL` (default `http://127.0.0.1:4096`) and fails loud if
  unreachable. Start it natively (`opencode serve --port 4096`) or via Docker with **identical
  host/container mount paths** so role directories and `--target-repo` paths match 1:1:
  ```bash
  docker run -d --name ultron-opencode --network host \
    -v /home/$USER/Dev:/home/$USER/Dev \
    -v ~/.config/opencode:/root/.config/opencode \
    ghcr.io/anomalyco/opencode:latest serve --hostname 127.0.0.1 --port 4096
  ```
- **Optional Basic Auth:** If the server sets `OPENCODE_SERVER_PASSWORD`, export the same
  `OPENCODE_SERVER_PASSWORD` (and optional `OPENCODE_SERVER_USERNAME`, default `opencode`) in ULTRON's
  environment.
- **Explicit models (zero silent guessing):** Pass explicit `provider/model` strings (e.g.
  `ollama/qwen3-coder:32b`, `vllm/deepseek-r1:32b`) via `create-team --model`, `add-role --model`,
  or `set-model`; pass `inherit` to intentionally use the default model configured in
  `opencode.json`; or export `ULTRON_OPENCODE_MODEL_{SMALL,MEDIUM,LARGE}` to map blueprint tiers.
- **Hard permissions:** `spawn-team` attaches a `PermissionRuleset` to every session denying `task`
  (no rogue subagents), `question` (never hang headless), Prime-only `core.py` lifecycle commands,
  and `edit`/`write`/`apply_patch` on `read_only_mode` roles.
- **OpenCode as ULTRON PRIME:** Attach to `opencode serve` (`opencode attach http://127.0.0.1:4096`),
  load `ultron/core/ULTRON_PRIME.md`, discover your session ID (`opencode session list --format json`
  or `GET /session`), and run `core.py register-prime --id <ses_id> --harness opencode`. Pair with a
  host cron/timer calling `core.py doorbell ultron-prime "Safety Cron tick..."` for periodic wakeups.
- `workspace_mode: branch` is not supported yet.

## Mixed hives

All three harnesses (`antigravity`, `claude-code`, `opencode`) can coexist in one ULTRON Hive.
`claude-code` and `opencode` both launch from the CLI (`launches_from_cli = True`), so a Prime on
any harness can spawn and doorbell Claude Code and OpenCode teams directly. Before spawning Claude
Code roles from an Antigravity shell, check `ps eww` for a `claude daemon`: one started from that
shell passes its `ANTIGRAVITY_*` variables to every role.
