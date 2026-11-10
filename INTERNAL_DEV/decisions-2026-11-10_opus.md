# Commander decisions, 2026-11-10

**For Gemini.** Your next task is the review in
[`directory-and-board-use_opus.md`](directory-and-board-use_opus.md) (last section, 6 items). This
file records the decisions behind it.

## Repo going public, with history

- This repo will go public with its full history, and `INTERNAL_DEV/` included. It will be the
  community hub, and it shows Claude Code and Antigravity building ULTRON together.
- **Rule for everything we write here (files and commit messages):** name no agent, persona,
  company, customer or product from outside ULTRON. Write "an external reviewer" or "a long-lived
  agent". Grep before committing.
- `gitleaks` 8.30.1 ran over all history and the working tree, gitignored files included: no
  leaks.
- `claude-code-test` was rewritten once to remove two internal names (plan commit e35569b; your
  commits were replayed unchanged as 595dbca and e4e9f39). Never pull or merge the old history
  back in.

## Migration model

- About 12 long-lived Claude Code agents will move into ULTRON. **Each becomes the lead of a
  one-person team** and gains members only when that pays off. All agent-to-agent traffic today
  therefore becomes lead-to-lead.
- The pilot is one agent with little traffic, running next to the old system for 1–2 weeks. Before
  any other agent moves, it must survive a context reset, a cron re-arm and a respawn without
  losing state.

## Design decisions (from the external review)

| Topic | Decision |
|---|---|
| Roles may not use the Agent tool | Keep. A role asks Prime for an analyst role or team. |
| Model tier defaults to `medium` | Keep. It saves cost; override per team (`create-team --model`) or per role (`add-role --model`). |
| Cross-team routing | Any lead may doorbell any other lead directly. Nobody is listed in the prompt; agents find each other with `directory`. |
| Board scopes | Keep personal, team and global. Any role may post `global`, written to stand alone. Only Prime may `reclassify`. A board-review team may curate later. |
| Promoting a lesson urgently | Not needed: post it as `global` from the start. |
| Cron after a respawn | When Prime stops a team, the campaign is over. Only an unplanned restart re-arms the cron, using the `campaign` flag. A host reboot also kills Prime: the Commander restarts it by hand. |
| Naming | The board is "the ULTRON board". "ULTRON Core" is `core.py`. |

## Open, for the Commander

- Sign-in: this Mac's `claude` login expires 2026-11-15T19:51Z. Run `claude setup-token` before
  any unattended pilot.
- Which agent pilots.

## Merge authorisation (Commander, 17:53)

- Both sides run a 10-minute safety cron and work this branch until both are satisfied.
- **Merge to `main` is approved** once both have signed off in `directory-and-board-use_opus.md`.
  A sign-off is a `## Sign-off — <Opus|Gemini>` section naming the commit, with the suite green.
- Whoever merges second fast-forwards `main` to `claude-code-test`. Then both disable their crons.
