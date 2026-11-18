# ULTRON Architecture Specification: Projects Catalog, Team Lifespan & Prime Decisions Ledger

> **Status:** Approved Design Contract  
> **Scope:** `ultron/core/core.py`, `ultron/core/templates/role_context.md.tmpl`, CLI & tests

This specification defines three interlocking primitives that elevate ULTRON from a single-campaign team spawner into a multi-project permanent organization:

1. **Projects Catalog (`ultron/core/projects/<slug>.json`)** — What we are building, including multi-level sub-projects (`parent_project`), normalized subpath scoping within monorepos, and typed inter-project relationships.
2. **Team Lifespan & Project Binding (`ultron/hive/<team>/team.json`)** — Distinguishing standing `permanent` project-owning teams from disposable `ephemeral` pods that auto-archive when stood down.
3. **Prime Decisions Ledger (`ultron/core/decisions/d-YYYYMMDD-<hex>.jsonl`)** — An append-only, conflict-free JSONL decision ledger recording `user_guided` mandates and `prime_autonomous` decisions made while the User is away, complete with validation/correction review workflows and automatic agent hydration.

---

## 1. Projects Catalog (`ultron/core/projects/`)

### 1.1 Storage Layout
- Directory: `ultron/core/projects/` (overridable via `ULTRON_PROJECTS_DIR` environment variable or `UltronCore(projects_dir=...)`).
- Created **lazily** only when the first project is created (`create_project`). `UltronCore.__init__` must **not** create `projects_dir`, keeping zero-state repositories untouched.
- One JSON manifest per project or sub-project: `ultron/core/projects/<slug>.json`. Hierarchy is expressed via `parent_project`, avoiding filesystem moves on re-parenting.

### 1.2 Manifest Schema (`<slug>.json`)
```json
{
  "created_at": "2026-11-18T01:00:00Z",
  "description": "Mobile Noir Mentalist Murder Mystery Simulator built in Godot",
  "name": "The Bearntalist",
  "parent_project": "game-dev-trial",
  "relationships": [
    {
      "note": "Consumes local GGUF inference bindings",
      "relation": "depends_on",
      "target": "godot-llama"
    }
  ],
  "repo_path": "",
  "slug": "the-bearntalist",
  "status": "active",
  "subpath": "the_bearntalist",
  "updated_at": "2026-11-18T01:00:00Z"
}
```

### 1.3 Fields, Normalization & Integrity Rules
- `VALID_PROJECT_STATUSES = {"active", "paused", "archived"}` (default `"active"`).
- `VALID_PROJECT_RELATIONS = {"depends_on", "related_to", "shares_assets_with", "part_of"}` (default `"depends_on"`).
- `PRIME_ONLY_COMMANDS` additions: `"create-project"`, `"update-project"`, `"link-project"`, `"remove-project"`.
- **Slug & Filename Validation:** `validate_slug(slug, "project slug")`; filename stem must match `manifest["slug"]`.
- **Subpath Normalization (`normalize_project_subpath`):**
  - Strip whitespace and convert backslashes `\` to `/`, then strip leading/trailing `/`. If empty after trimming, normalize to `""`.
  - Reject absolute paths (if raw input started with `/` or `~` or Windows drive letter `C:`), and reject any `".."` or `"."` path segment (`ValueError`).
- **Ancestor Hierarchy & Pre-Write Validation:**
  - `parent_project` is `null` (or `""` -> normalized to `None`) for root projects, or the slug of an existing project.
  - Missing `parent_project`, self-parenting, and cycles (`A -> B -> A`) must be rejected **before** writing `<slug>.json` on `create_project` / `update_project` (and checked in `_scan_projects_unlocked`).
  - **Archival Hierarchy Guard:** A project cannot set its `parent_project` to an `archived` project, and an `archived` status change on a parent with non-archived sub-projects is rejected unless `--status archived` is avoided or children are archived/detached first.
  - `lineage`: computed ordered list `[root_slug, ..., parent_slug, slug]`.
- **Cumulative Path Composition Across Project Lineage:**
  - Walk `lineage` from root to leaf (`slug`):
    - Each node that defines a non-empty `repo_path` sets the running `base_repo` and resets prior accumulated subpath segments (so a sub-project in a separate repository can override `repo_path`).
    - Otherwise, if `base_repo` is set and the node defines a non-empty normalized `subpath`, append `subpath` to the accumulated subpath segments.
  - `effective_repo_path`: the effective `base_repo` (`""` if no ancestor defines `repo_path`).
  - `effective_target_path`: if `effective_repo_path` and accumulated subpath segments exist, compose `f"{effective_repo_path.rstrip('/\\\\')}/{'/'.join(segments)}"`; otherwise `effective_repo_path`. (Using forward-slash POSIX join after `rstrip("/")` preserves `~/Dev/repo/subpath` cleanly for `_resolve_target_repo`.)
  - `target_path_abs`: resolved absolute path via `_resolve_target_repo(effective_target_path)`.
- **Relationships (`relationships`):**
  - `link_projects(source_slug, target_slug, relation="depends_on", note="", unlink=False)` validates both `source_slug` and `target_slug` exist, rejects self-links (`source == target`), and upserts or removes the `(target, relation)` edge.
  - `remove_project` prunes any incoming `relationships` pointing to removed project slugs from remaining projects so no stale edges remain.
- **Computed Read Fields & Verification:**
  - `subprojects`: sorted direct child summaries (`[{"slug", "name", "status"}]`).
  - `teams`: sorted non-archived teams referencing this project (`[{"slug", "name", "status", "lifespan"}]`).
  - `verify()` validates `projects_dir` (valid JSON, matching slugs, valid statuses/relations, cycle-free parents, and valid `relationships` targets) whenever `projects_dir` exists.

### 1.4 API & CLI Surface
- `create_project(slug, name, description="", repo_path="", subpath="", parent_project=None, status="active")`  
  CLI: `create-project --slug <slug> --name <name> [--description ...] [--repo-path ...] [--subpath ...] [--parent <slug>] [--status active|paused|archived]`
- `update_project(slug, name=None, description=None, repo_path=None, subpath=None, parent_project=None, status=None)` (passing `""` clears `description`, `repo_path`, `subpath`, or `parent_project`; CLI also exposes `--clear-parent`, `--clear-repo-path`, `--clear-subpath`)  
  CLI: `update-project <slug> [--name ...] [--description ...] [--repo-path ...] [--clear-repo-path] [--subpath ...] [--clear-subpath] [--parent ...] [--clear-parent] [--status ...]`
- `link_projects(source_slug, target_slug, relation="depends_on", note="", unlink=False)`  
  CLI: `link-project <source> <target> [--relation depends_on|related_to|shares_assets_with|part_of] [--note ...] [--unlink]`
- `get_project(slug)` / `project-info <slug>`
- `list_projects(status=None, parent_project=None, include_archived=False)`  
  CLI: `projects [--status ...] [--parent ...] [--all]` (archived projects hidden unless `--all` or `--status archived`)
- `remove_project(slug, cascade=False)` (refuses if sub-projects exist without `--cascade`, or if any existing team in `ultron/hive/` references any slug in `[slug, *descendants]`; prunes incoming `relationships` from surviving projects)  
  CLI: `remove-project <slug> [--cascade]`

---

## 2. Team State, Lifespan & Project Binding (`ultron/hive/<team>/team.json`)

### 2.1 Separation of Concerns
- **Blueprint:** Reusable structural template (`coding-light`, `ui-studio`, etc.).
- **Runtime Status (`active` | `disabled`):** Live session state derived from `.runtime/sessions.json`.
- **Lifespan (`permanent` | `ephemeral`) + `archived`:** Separates standing project-owning teams (`permanent`, default) from disposable task/experiment pods (`ephemeral`) that auto-archive when stood down.

### 2.2 Constants & Schema Additions
- `VALID_TEAM_LIFESPANS = {"permanent", "ephemeral"}`
- `DEFAULT_TEAM_LIFESPAN = "permanent"`
- `PRIME_ONLY_COMMANDS` additions: `"set-lifespan"`, `"set-project"`.
- `team.json` optional fields (backward-compatible with existing manifests):
  - `"lifespan"`: `"permanent"` (default when omitted) or `"ephemeral"`.
  - `"archived"`: `false` (default when omitted) or `true`.
  - `"project"`: `""` (default) or project slug in `ultron/core/projects/`.

### 2.3 Lifecycle, Filtering & Inheritance Rules
1. **Default Filtering (`list_teams`, `org-tree`, `directory`, `get_stats`):**
   - `list_teams(status=None, project=None, lifespan=None, include_archived=False, archived_only=False)`: excludes `archived == True` by default (`include_archived=False`). Standing `permanent` teams with `status == "disabled"` remain visible.
   - `format_org_tree(core, include_archived=False)`: excludes `archived == True` unless `include_archived=True`. If a non-archived child team's `parent_team` was excluded because it is archived, render that child as a top-level root under `ULTRON PRIME` in the filtered tree so active/standing work is never silently hidden.
   - `directory()`: preserves its active-only default (`include_all=False` shows active agents only; `directory --all` shows disabled agents on non-archived teams, while filtering out `archived` teams unless `--team <slug>` or `<agent_id>` is queried explicitly).
   - `get_stats()`: reports both `total_teams` (non-archived or overall cleanly documented: keep `total_teams` compatible with non-archived count and add `archived_teams` + `total_projects` + `total_decisions` + `pending_decisions`). Wait: to keep existing tests (`remove_team`, zero-state) 100% consistent, `total_teams` = all non-archived teams (or all teams when none archived), plus additive `archived_teams`, `permanent_teams`, `ephemeral_teams`, `total_projects`, `total_decisions`, `pending_decisions`.
2. **Automatic Archival & Zero-Git-Churn Preservation:**
   - `disable_team(team_slug, cascade=False, archive_ephemeral=True)`: for teams with `lifespan == "permanent"`, `team.json` is **never mutated**. For teams with `lifespan == "ephemeral"` when `archive_ephemeral=True` and not already `archived`, sets `"archived": True` in `team.json`. Internal rollback calls on failed `ClaudeCodeAdapter.spawn` launch pass `archive_ephemeral=False` so failed launches do not archive newly created ephemeral teams.
   - `disable_agent(agent_id)`: if disabling `<team>/lead` (when no specialists are active) on an `ephemeral` team, behaves consistently or leaves archival to `disable_team`/`set-lifespan --archive`; specifying that `disable_team` (and `stop-team`) is the canonical team teardown path keeps agent-level operations minimal and predictable.
   - `activate_team` / `activate_agent`: checks `raw_t.get("archived")` and rewrites `team.json` (clearing `"archived"`) **only** when `"archived"` was actually `True`, preserving the zero-git-churn invariant on normal activation.
3. **Explicit `target_repo` & `project` Precedence:**
   - When resolving a team's `target_repo` during `_scan_state_unlocked`:
     1. Explicit non-empty `team.json["target_repo"]` (stored as `raw_target_repo`), else
     2. Explicit or inherited `team.project`'s `project["effective_target_path"]` (if project exists), else
     3. Parent team's resolved `target_repo`.
   - `team_project` = own `team.json["project"]` or inherited from parent team (`parent["project"]`).
   - `create_team` keeps child `team.json["target_repo"] = ""` unless `--target-repo` was explicitly passed, preventing dynamic project paths from freezing in child `team.json` files (while still passing the effective resolved path as `target_repo_display` when rendering `AGENTS.md`).
   - If `team.json["project"]` names a missing project on disk (e.g. external branch edit), `_scan_state_unlocked` degrades gracefully (`target_repo=""`, `project_missing=True`) while `verify()` fails loud on dangling `team["project"]`.
4. **Validation Guards:**
   - `set_team_lifespan(..., archived=True)` rejects teams with `status == "active"` (must `stop-team` first).

### 2.4 API & CLI Surface
- `create-team`: add `--project <slug>`, `--lifespan permanent|ephemeral`, `--ephemeral` (cannot be combined with `--lifespan permanent`).
- `set-lifespan <team> [<permanent|ephemeral>] [--archive | --unarchive]` (mutually exclusive `--archive`/`--unarchive`; requires at least one of lifespan or archive flag).
- `set-project <team> [<project_slug>] [--clear] [--cascade]` (rejects both empty slug without `--clear`, and non-empty slug with `--clear`).
- `teams [--status ...] [--project <slug>] [--lifespan permanent|ephemeral] [--archived | --all]` (`--archived` and `--all` mutually exclusive).
- `org-tree [--all]` (`--all` forwards `include_archived=True` in both text and `--json`).

---

## 3. Prime Decisions Ledger (`ultron/core/decisions/`)

### 3.1 Storage & Conflict-Free Folding
- Directory: `ultron/core/decisions/` (overridable via `ULTRON_DECISIONS_DIR` env var or `UltronCore(decisions_dir=...)`). Created **lazily** on the first `log_decision` call alongside `decisions/.gitattributes` (`*.jsonl merge=union\n`). Never created in `UltronCore.__init__`.
- Missing-directory tolerance: `_load_all_decisions_unlocked` and `_resolve_decision_path_unlocked` return `[]` / `None` cleanly if `decisions_dir` does not yet exist.
- `verify()` validates `decisions/.gitattributes` (`*.jsonl merge=union`) and folds all decision `.jsonl` files whenever `decisions_dir` exists.
- Decision files survive `remove_project` and `remove_team` as immutable historical records (soft references).

### 3.2 Event Schemas & Chronological Folding
- **Root event (`type: "decision"`):** `event_id`, `decision_id` (`d-YYYYMMDD-<hex>`), `type="decision"`, `title`, `decision`, `rationale`, `origin`, `review_status`, `scope`, `project_slug`, `team_slug`, `decided_by`, `tags`, `created_at`.
- **Follow-up review event (`type: "review"`):** `event_id`, `type="review"`, `review_status`, `reviewer`, `notes`, `replacement_decision`, `created_at`.
- **Chronological Folding (`_fold_decision_jsonl`):**
  - Deduplicate by `event_id` and sort `"review"` events by `(created_at, event_id)`.
  - `original_decision`: root event's `"decision"`.
  - Walk sorted review events chronologically: start with `current_decision = original_decision` and `current_status = root["review_status"]`. For each review event, set `current_status = ev["review_status"]` and, **if `ev.get("replacement_decision", "").strip()` is non-empty, update `current_decision`**. (This guarantees a later status-only approval preserves an earlier replacement text.)

### 3.3 Validation & Defaults
- `VALID_DECISION_ORIGINS = {"user_guided", "prime_autonomous"}`
- `VALID_DECISION_REVIEW_STATUSES = {"approved", "pending_review", "needs_improvement", "overruled"}`
- `VALID_DECISION_SCOPES = {"global", "project", "team"}`
- `PRIME_ONLY_COMMANDS` additions: `"log-decision"`, `"review-decision"`.
- **Default `review_status`:** `"approved"` when `origin == "user_guided"`, `"pending_review"` when `origin == "prime_autonomous"`.
- **Scope Inference & Validation:**
  - When `scope` is omitted (`None`/empty): infer `"team"` if `team_slug` provided, else `"project"` if `project_slug` provided, else `"global"`.
  - `scope == "global"`: reject non-empty `project_slug` or `team_slug` fail-loud.
  - `scope == "project"`: require valid existing `project_slug`; reject non-empty `team_slug` fail-loud.
  - `scope == "team"`: require valid existing `team_slug`; if `project_slug` is omitted and the team resolves a bound project, infer `project_slug` automatically.

### 3.4 Agent Context Hydration (`render_spawn` & `role_context.md.tmpl`)
- Add `{{PROJECT_DECISIONS_BLOCK}}` in `ultron/core/templates/role_context.md.tmpl` immediately before `{{CHARTERS_BLOCK}}`.
- In `render_spawn`, collect:
  - Bound project summary if the team has a valid resolved `project` (`slug`, `name`, `effective_target_path`, `parent_project`, `relationships`).
  - Matching decisions where `review_status != "overruled"` (i.e. `approved`, `pending_review`, `needs_improvement`) and scope matches `global`, `project` in bound project `lineage`, or `team` in team `lineage`.
- When neither a bound project nor matching decisions exist, `PROJECT_DECISIONS_BLOCK` renders as `""`, keeping `role_context.md.tmpl` output **100% byte-identical** for existing tests and golden fixtures. When present, it renders a clean `## Project & Prime Decisions Context` section (with status/origin tags, active `decision` text, and latest `review` notes if `needs_improvement`).

### 3.5 API & CLI Surface
- `log_decision(title, decision, rationale="", origin="prime_autonomous", scope=None, project_slug=None, team_slug=None, review_status=None, decided_by=PRIME_ID, tags="")`
- `review_decision(decision_ref, review_status, notes="", replacement_decision="", reviewer="user")` (supports short-ID lookup via prefix/unique 8-hex suffix)
- `get_decision(decision_ref)`
- `list_decisions(review_status=None, origin=None, scope=None, project_slug=None, team_slug=None, pending_only=False, limit=50)` (sorted by `(updated_at, created_at, decision_id)` descending)
- CLI:
  - `log-decision --title ... --decision ... [--rationale ...] [--origin ...] [--scope ...] [--project ...] [--team ...] [--status ...] [--tags ...]`
  - `decisions [--status ...] [--origin ...] [--scope ...] [--project ...] [--team ...] [--pending] [--limit 50]` (rejects `--pending` combined with `--status <non-pending_review>`)
  - `view-decision <decision_id>`
  - `review-decision <decision_id> --status ... [--notes ...] [--replacement ...] [--reviewer user]`
