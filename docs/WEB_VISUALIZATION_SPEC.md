# ULTRON Mission Control — Web Visualization MVP Specification

> **Status:** Authoritative As-Designed Specification · **Mode:** Strictly Read-Only MVP · **Dependencies:** Python 3.10+ Stdlib & Offline Browser Assets Only

---

## 1. Goals & Architectural Invariants

1. **Zero-Dependency Local Server:** Served by a standalone module `ultron/core/web.py` using Python's standard-library `ThreadingHTTPServer` and `BaseHTTPRequestHandler` (`zero pip`, `zero npm`, `zero build step`). Launched via `python3 ultron/core/core.py ui [--host 127.0.0.1] [--port 8420] [--no-open]` (respecting `--root <path>` to inspect any ULTRON workspace such as `/Users/jvroig/Dev/ULTRON_IMPERATIVE`).
2. **Strictly Read-Only MVP:**
   - Only `GET` and `HEAD` HTTP methods are accepted. Any `POST`, `PUT`, `PATCH`, `DELETE`, or `OPTIONS` request fails with `405 Method Not Allowed` (`Allow: GET, HEAD`) and JSON `{"ok": false, "error": "ULTRON Web UI is strictly read-only."}`.
   - No HTTP request may mutate `ultron/hive/`, `ultron/core/projects/`, `ultron/core/decisions/`, `ultron/core/threads/`, or `.runtime/sessions.json`.
   - **Zero Lazy-Directory Side Effects:** Scanning state or computing ETags must check `.exists()` / `.is_dir()` before inspecting `projects/`, `decisions/`, `threads/`, or `hive/` and must **never** call `mkdir()` as a side effect of viewing the UI.
   - **Prime-Only Launch Guard:** `ui` is listed in `PRIME_ONLY_COMMANDS` in `ultron/core/core.py` so spawned specialist shells (`ULTRON_AGENT_ID != ultron-prime`) cannot launch background servers.
3. **Single Source of Truth (`UltronCore`):** All manifest parsing, project path composition, team lifespan resolution, chronological JSONL event folding, and permission/state computation happen in `UltronCore` in Python—never duplicated in client JavaScript.
4. **Loopback Default & Hardening:**
   - Default bind host is `127.0.0.1` (`DEFAULT_PORT = 8420`). Binding a non-loopback address (`!= "127.0.0.1"`, `"::1"`, `"localhost"`) prints a clear warning on `stderr`.
   - Security headers on every response: `X-Content-Type-Options: nosniff`.
   - Strict CSP on `index.html`: `default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'`.
   - Zero `innerHTML` / `outerHTML` / `insertAdjacentHTML` on dynamic data in client JavaScript (`document.createElement` + `textContent` and `createElementNS` from static sprite definitions only).
5. **Decoupled Visual Layer for Future `ui-studio` Polish:**
   - Design tokens (`ultron/core/web/tokens.css`) and pixel-art SVG sprite engine (`ultron/core/web/sprites.js`) live in dedicated, swappable files separate from layout CSS (`styles.css`), controller logic (`app.js`), and server API (`web.py`).

---

## 2. Live Transport: `ETag` Conditional Polling (Future-Proofed for SSE)

- **Server ETag (`compute_state_etag(core)`):**
  - Walks existing state locations (`sessions.json` plus existing `hive/`, `projects/`, `decisions/`, `threads/`) collecting sorted `(rel_posix, st_mtime_ns, st_size)` for `*.json`, `*.jsonl`, and `AGENTS.md` (ignoring hidden files `.lock`, `.tmp.*`, `.gitattributes`, `.gitkeep`).
  - Hashes tuples with SHA-256 (`hexdigest()[:24]`) and formats a strong quoted entity tag `'"<hex>"'`.
  - Executes only `stat()` syscalls (<1ms when idle) without reading JSON/JSONL file bodies unless the ETag misses.
- **Snapshot Cache:** `UltronWebServer` caches `(etag, encoded_snapshot_bytes)` under a `threading.Lock()`. Multiple rapid browser requests with the same `If-None-Match` (handling optional `W/` weak prefix or comma-separated ETag lists per RFC 9110) receive `304 Not Modified` with empty body and `ETag`.
- **Client `LiveSync` Abstraction (`app.js`):** Isolates the refresh trigger (`setInterval` at `2500ms`, automatically paused when `document.hidden` and immediately triggered on `visibilitychange` return) behind one small transport object so optional SSE invalidation pings (`event: changed`) can be swapped in later with zero changes to API schemas or view renderers.

---

## 3. Read-Only HTTP & JSON API Contract

All JSON routes set `Content-Type: application/json; charset=utf-8` and `Cache-Control: no-cache`.

| Route | Behavior & Response |
| :--- | :--- |
| `GET /`, `GET /index.html` | Serves `ultron/core/web/index.html` (`text/html; charset=utf-8`) with CSP header. |
| `GET /assets/<name>` | Strict allowlist (`ALLOWED_ASSETS = {"tokens.css", "styles.css", "sprites.js", "app.js"}`). Decodes URL path, rejects `/` or `\` or traversal segments, verifies resolved path stays directly inside `assets_dir`, returns `404` otherwise. |
| `GET /api/health` | `200` `{"ok": true, "read_only": true, "repo_name": "<name>"}` |
| `GET /api/snapshot` | Supports `If-None-Match` -> `304 Not Modified`. Otherwise `200` with `ETag`:<br>`{generated_at, repo_name, repo_root, stats, prime, teams, projects, decisions, threads, blueprints}`.<br>- `teams`: `core.list_teams(include_archived=True)` (UI handles default hide/show archived & parent promotion).<br>- `projects`: `core.list_projects(include_archived=True)`.<br>- `decisions`: `core.list_decisions(limit=500)`.<br>- `threads`: `core.list_threads(show_all=True, limit=500)`.<br>- `prime`: `core.get_agent("ultron-prime")` or normalized unregistered placeholder `{agent_id: "ultron-prime", status: "unregistered", conversation_id: "", harness: "", title: "ULTRON PRIME"}`. |
| `GET /api/threads/<ref>` | Calls `core.get_thread(ref, show_all=True)` (supports full ID or short suffix). `200` folded thread object with full `posts[]`, `404` if not found, `400` on `ValueError` (e.g. ambiguous short ID). |
| `GET /api/decisions/<ref>` | Calls `core.get_decision(ref)`. `200` folded decision object with `original_decision`, `rationale`, `reviews[]`; `404` if not found; `400` on `ValueError`. |
| `GET /api/verify` | Explicit on-demand integrity check calling `core.verify(prune_orphans=False)` (never mutating). Returns `200` `{"ok": true, ...}` on clean repo or `200` `{"ok": false, "error": "..."}` on integrity errors (fail loud visibly in UI). |
| `GET /api/liveness[?team=<slug>]` | Explicit on-demand check calling `core.probe_liveness(team_slug=team)` (**never** invoked on background polling loop). Returns `200` `{"ok": true, ...}` or `200` `{"ok": false, "error": "..."}` when harness binaries/daemons are offline. |

*(Unknown routes return `404` JSON `{"ok": false, "error": "Not found"}`; internal exceptions return `500` JSON `{"ok": false, "error": "..."}`.)*

---

## 4. UI Architecture & Pixel-Art Bot Visual Language

1. **Command Top Bar & Telemetry Ribbon:**
   - ULTRON PRIME pixel crest + workspace name (`repo_name`), Live Sync pill (active/paused + ETag hash + manual refresh), `pending_review` alert badge (clicks straight to Decisions pending queue), `Show Archived` toggle, `Verify`, and `Liveness` buttons.
   - 6 compact KPI tiles: Active Teams, Standing Permanent Teams, Archived Pods, Registered Projects, Pending Decisions, and Open/Active Threads.
2. **Four Hash-Synced Tabs (`#hive`, `#projects`, `#decisions`, `#board`):**
   - **Hive Command Deck (Default Hero View):**
     - Apex `ULTRON PRIME` node connected down to Layer 1 teams and arbitrarily nested Layer 2..N subteams (mirroring `format_org_tree`: hides `archived` teams by default and promotes non-archived children of archived parents to top-level when `Show Archived` is off).
     - Each team card renders its mission, `status` (`ACTIVE` / `STANDBY`), `lifespan` (`PERMANENT` / `EPHEMERAL` / `ARCHIVED`), `harness`, `campaign` badge, bound `project` chip, and interactive **pixel-art bot roster**.
   - **Projects Topology:** Multi-level project hierarchy (`layer`, `effective_target_path`, `status`), typed `relationships` (`depends_on`, `part_of`, `shares_assets_with`, `related_to`), and clickable bound team chips.
   - **Prime Decisions Queue:** Filterable by `review_status` (`pending_review`, `needs_improvement`, `approved`, `overruled`), `origin` (`prime_autonomous` vs `user_guided`), `scope`, and text search; shows current ruling, revised indicator when `original_decision != decision`, and one-click **"Copy `review-decision` CLI"** button.
   - **Board Activity Feed:** Filterable by `visibility` (`global`, `team`, `personal`), `status`, `team`, and text query; opens full folded post timeline on click.
3. **Pixel-Art Bot Sprites (`ultron/core/web/sprites.js`):**
   - Crisp inline SVGs (`<svg viewBox="0 0 16 16" shape-rendering="crispEdges">`) with 7 distinct archetypes mapped from `role` + `write_tools`:
     - `prime`, `lead`, `coder` (`coder`/`dev`/`backend`/`frontend`/`engineer`), `designer` (`ui`/`designer`/`ux`/`visual`/`visualizer`/`drafter`), `critic` (`qa`/`tester`/`reviewer`/`critic`/`auditor` or `write_tools === false`, with read-only visor shield cue), `architect` (`spec`/`architect`/`writer`/`analyst`/`explorer`), and `specialist` fallback.
   - 4 clear visual states: `active` (lit glowing visor + gentle idle pixel hover), `standby` (dimmed amber/slate visor in charging dock), `archived` (crated muted silhouette), `unregistered` (powered-off dark visor).
4. **Slide-Over Inspector Drawer:**
   - Displays full details & copyable read/review CLI helpers (`spawn-team`, `stop-team`, `review-decision`, `view`) when clicking any Team, Role Bot, Project, Decision, or Board Thread (`Escape` or backdrop closes cleanly).
