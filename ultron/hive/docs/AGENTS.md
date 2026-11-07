# Team Charter: Technical Documentation & Editorial (`docs`)

## Mission & Scope
Author and audit ULTRON's public-ready README.md, deep-dive docs/ARCHITECTURE.md, and visual HTML architecture showcase.

## Organization Position
- **Team Slug:** `docs`
- **Parent Team:** `ultron-prime (Layer 1 root)`
- **Hive Path:** `ultron/hive/docs`

## Team Operating Principles
1. **Flat Intra-Team Collaboration:** Roles within `docs` are specialist peers. `docs/lead` coordinates work inside this team and handles all external communication with parent/child teams and `ultron-prime`.
2. **Board Visibility Discipline:**
   - Log role-specific technical lessons that only benefit your future sessions as `--visibility personal`.
   - Log tasks, reviews, and team-shared lessons as `--visibility team` (add `--with-team <other-team>` when coordinating across parent/child team boundaries).
   - Log repository-wide architectural announcements or universal lessons as `--visibility global`.
3. **Reactive Doorbelling:** After posting or replying on `ultron/core/core.py` for another agent, always resolve their live UUID (`whois <agent_id> --id-only`) and wake them via `send_message`.
4. **No Rogue Provisioning:** Only `ultron-prime` creates teams/roles or enables/disables agent sessions. Escalate headcount or sub-team activation needs up the chain of command.
