(function () {
  "use strict";

  const Sprites = window.UltronSprites;

  // Isolated ETag polling transport; can be swapped to SSE invalidation later without touching views.
  class LiveSync {
    constructor(intervalMs, onSnapshot, onStatus) {
      this.intervalMs = intervalMs;
      this.onSnapshot = onSnapshot;
      this.onStatus = onStatus;
      this.etag = null;
      this.paused = false;
      this.timer = null;
      this.inFlight = false;
      this.lastSyncAt = null;
    }

    start() {
      if (this.timer) return;
      this.tick(true);
      this.timer = window.setInterval(() => {
        if (!this.paused && !document.hidden) {
          this.tick(false);
        }
      }, this.intervalMs);
      document.addEventListener("visibilitychange", () => {
        if (!document.hidden && !this.paused) {
          this.tick(false);
        }
      });
    }

    setPaused(paused) {
      this.paused = paused;
      this.emitStatus(this.paused ? "paused" : "live");
      if (!paused) this.tick(true);
    }

    emitStatus(mode, extra) {
      this.onStatus({
        mode: mode,
        etag: this.etag,
        lastSyncAt: this.lastSyncAt,
        extra: extra || "",
      });
    }

    async tick(force) {
      if (this.inFlight) return;
      this.inFlight = true;
      try {
        const headers = {};
        if (!force && this.etag) {
          headers["If-None-Match"] = this.etag;
        }
        const resp = await fetch("/api/snapshot", { headers: headers, cache: "no-store" });
        this.lastSyncAt = new Date();
        if (resp.status === 304) {
          this.emitStatus(this.paused ? "paused" : "live");
          return;
        }
        if (!resp.ok) {
          throw new Error("Snapshot HTTP " + resp.status);
        }
        const newEtag = resp.headers.get("ETag");
        if (newEtag) this.etag = newEtag;
        const data = await resp.json();
        this.onSnapshot(data);
        this.emitStatus(this.paused ? "paused" : "live");
      } catch (err) {
        this.emitStatus("error", err && err.message ? err.message : String(err));
      } finally {
        this.inFlight = false;
      }
    }
  }

  const state = {
    snapshot: null,
    activeTab: "hive",
    showArchived: false,
    activeOnly: false,
    drawerMode: null,
    drawerRequestSeq: 0,
    orgOptions: { project: "", expandRoles: false, zoom: "fit" },
    decisionFilters: { status: "", origin: "", scope: "", query: "" },
    boardFilters: { visibility: "", status: "", team: "", query: "" },
    toastTimer: null,
  };

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach((k) => {
        const v = attrs[k];
        if (v === undefined || v === null || v === false) return;
        if (k === "className") {
          node.className = v;
        } else if (k === "text") {
          node.textContent = String(v);
        } else if (k.startsWith("on") && typeof v === "function") {
          node.addEventListener(k.slice(2).toLowerCase(), v);
        } else {
          node.setAttribute(k, v === true ? "" : String(v));
        }
      });
    }
    if (children !== undefined && children !== null) {
      const list = Array.isArray(children) ? children : [children];
      list.forEach((child) => {
        if (child === undefined || child === null || child === false) return;
        if (typeof child === "string" || typeof child === "number") {
          node.appendChild(document.createTextNode(String(child)));
        } else {
          node.appendChild(child);
        }
      });
    }
    return node;
  }

  const SVG_NS = "http://www.w3.org/2000/svg";

  function svgEl(tag, attrs, children) {
    const node = document.createElementNS(SVG_NS, tag);
    if (attrs) {
      Object.keys(attrs).forEach((k) => {
        const v = attrs[k];
        if (v === undefined || v === null || v === false) return;
        if (k === "text") {
          node.textContent = String(v);
        } else if (k === "className") {
          node.setAttribute("class", String(v));
        } else if (k.startsWith("on") && typeof v === "function") {
          node.addEventListener(k.slice(2).toLowerCase(), v);
        } else {
          node.setAttribute(k, String(v));
        }
      });
    }
    if (children !== undefined && children !== null) {
      const list = Array.isArray(children) ? children : [children];
      list.forEach((child) => {
        if (child) node.appendChild(child);
      });
    }
    return node;
  }

  function clearNode(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  async function fetchJson(url) {
    const resp = await fetch(url, { cache: "no-store" });
    const raw = await resp.text();
    let parsed = null;
    try {
      parsed = raw ? JSON.parse(raw) : {};
    } catch (_err) {
      throw new Error("HTTP " + resp.status + ": " + (raw.slice(0, 140) || "Invalid JSON response"));
    }
    if (!resp.ok) {
      throw new Error((parsed && parsed.error) || "HTTP " + resp.status);
    }
    return parsed;
  }

  function shellQuote(value) {
    return "'" + String(value || "").replace(/'/g, "'\"'\"'") + "'";
  }

  function upperStatus(value, fallback) {
    return String(value || fallback || "unknown").toUpperCase();
  }

  function showToast(msg) {
    const toast = document.getElementById("toast");
    toast.textContent = msg;
    toast.classList.remove("hidden");
    if (state.toastTimer) window.clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => toast.classList.add("hidden"), 2200);
  }

  function copyCli(cmd) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(cmd).then(
        () => showToast("Copied CLI command to clipboard"),
        () => fallbackCopy(cmd)
      );
      return;
    }
    fallbackCopy(cmd);
  }

  function fallbackCopy(cmd) {
    const ta = el("textarea", {
      style: "position:fixed;left:-9999px;top:0;",
      readonly: true,
    });
    ta.value = cmd;
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      showToast("Copied CLI command to clipboard");
    } catch (_e) {
      showToast("Copy blocked by browser; command shown in inspector");
    } finally {
      document.body.removeChild(ta);
    }
  }

  function shortTime(isoStr) {
    if (!isoStr) return "—";
    const s = String(isoStr).trim();
    if (!s) return "—";
    const parsed = new Date(s);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toISOString().replace("T", " ").slice(0, 19) + "Z";
    }
    return s;
  }

  function cliSnippetBox(label, cmd) {
    return el("div", { className: "detail-section" }, [
      el("div", { className: "panel-card-header" }, [
        el("h3", { text: label }),
        el("button", {
          className: "btn btn-sm btn-secondary",
          type: "button",
          text: "Copy CLI",
          onClick: () => copyCli(cmd),
        }),
      ]),
      el("pre", { className: "cli-box", text: cmd }),
    ]);
  }

  function renderKvSection(title, pairs) {
    const grid = el("div", { className: "kv-table" });
    pairs.forEach(([k, v]) => {
      grid.appendChild(el("div", { className: "kv-key", text: k }));
      grid.appendChild(el("div", { className: "kv-val", text: v || "—" }));
    });
    return el("div", { className: "detail-section" }, [
      el("h3", { text: title }),
      grid,
    ]);
  }

  function formatScopeBadge(d) {
    if (d && d.scope === "project" && d.project_slug) return "project:" + d.project_slug;
    if (d && d.scope === "team" && d.team_slug) return "team:" + d.team_slug;
    return (d && d.scope) || "global";
  }

  function formatThreadScope(t) {
    if (t && t.visibility === "personal") return "personal:" + (t.owner_agent || "");
    if (t && t.visibility === "team") {
      return t.with_team
        ? "team:" + (t.team_slug || "") + "<->" + t.with_team
        : "team:" + (t.team_slug || "");
    }
    return "global";
  }

  function showDiagBanner(isOk, title, detail) {
    const banner = document.getElementById("diag-banner");
    clearNode(banner);
    banner.className = "diag-banner " + (isOk ? "is-ok" : "is-error");
    banner.appendChild(
      el("div", { className: "diag-text" }, [
        el("strong", { text: title + ": " }),
        detail,
      ])
    );
    banner.appendChild(
      el("button", {
        className: "btn btn-sm btn-ghost",
        type: "button",
        text: "Dismiss",
        onClick: () => banner.classList.add("hidden"),
      })
    );
  }

  function buildTruncationNotice(shownCount, totalCount, noun) {
    if (!totalCount || shownCount >= totalCount) return null;
    return el("div", {
      className: "badge badge-warn",
      style: "margin-bottom:12px;display:inline-flex;",
      text:
        "Showing latest " +
        shownCount +
        " of " +
        totalCount +
        " " +
        noun +
        "; use the core CLI to query older entries.",
    });
  }

  function getBaseTeams(snap) {
    const teams = (snap && snap.teams) || [];
    return state.showArchived ? teams : teams.filter((t) => !t.archived);
  }

  function getVisibleHiveTeams(snap) {
    const base = getBaseTeams(snap);
    return state.activeOnly ? base.filter((t) => t.status === "active") : base;
  }

  function setActiveOnly(nextVal) {
    state.activeOnly = Boolean(nextVal);
    renderHeader();
    refreshActiveTabInPlace();
  }

  function buildActiveOnlyToggle(inputId, activeCount, totalCount) {
    return el(
      "label",
      {
        id: inputId + "-chip",
        className: "toggle-chip" + (state.activeOnly ? " is-active" : ""),
        for: inputId,
      },
      [
        el("input", {
          id: inputId,
          type: "checkbox",
          checked: state.activeOnly,
          onChange: (ev) => setActiveOnly(ev.target.checked),
        }),
        el("span", { className: "status-dot active" }),
        el("span", { text: "Active Teams Only" }),
        el("span", {
          id: inputId + "-count",
          className: "toggle-count mono",
          text: activeCount + "/" + totalCount,
        }),
      ]
    );
  }

  function syncActiveOnlyToggle(inputId, activeCount, totalCount) {
    const input = document.getElementById(inputId);
    const chip = document.getElementById(inputId + "-chip");
    const countEl = document.getElementById(inputId + "-count");
    if (input) input.checked = state.activeOnly;
    if (chip) chip.classList.toggle("is-active", state.activeOnly);
    if (countEl) countEl.textContent = activeCount + "/" + totalCount;
  }

  // Top Header & Stats Strip
  function renderHeader() {
    const snap = state.snapshot;
    if (!snap) return;

    const projects = snap.projects || [];
    const decisions = snap.decisions || [];
    const threads = snap.threads || [];

    const primeSlot = document.getElementById("prime-brand-sprite");
    clearNode(primeSlot);
    primeSlot.appendChild(
      Sprites.renderBotSvg("prime", Sprites.stateForAgent(snap.prime, null), 34)
    );

    document.getElementById("repo-badge").textContent = snap.repo_name || "ULTRON";

    const pendingCount = (snap.stats && snap.stats.pending_decisions) || 0;
    const pendingBtn = document.getElementById("pending-pill");
    if (pendingCount > 0) {
      pendingBtn.textContent =
        pendingCount + " Decision" + (pendingCount === 1 ? "" : "s") + " Pending Review";
      pendingBtn.classList.remove("hidden");
    } else {
      pendingBtn.classList.add("hidden");
    }

    const visibleTeams = getVisibleHiveTeams(snap);
    document.getElementById("count-hive").textContent = String(visibleTeams.length);
    const orgCountEl = document.getElementById("count-org");
    if (orgCountEl) orgCountEl.textContent = String(visibleTeams.length);
    document.getElementById("count-projects").textContent = String(
      (state.showArchived ? projects : projects.filter((p) => p.status !== "archived")).length
    );
    document.getElementById("count-decisions").textContent = String(decisions.length);
    document.getElementById("count-board").textContent = String(threads.length);

    const stats = snap.stats || {};
    const strip = document.getElementById("stats-strip");
    clearNode(strip);

    const tiles = [
      {
        label: "Active Teams",
        value: String(stats.active_teams || 0),
        sub: (stats.total_teams || 0) + " non-archived total",
      },
      {
        label: "Standing Teams",
        value: String(stats.permanent_teams || 0),
        sub: (stats.ephemeral_teams || 0) + " ephemeral pods",
      },
      {
        label: "Archived Pods",
        value: String(stats.archived_teams || 0),
        sub: state.showArchived ? "visible in Hive" : "hidden by default",
      },
      {
        label: "Projects",
        value: String(stats.total_projects || 0),
        sub: "registered in catalog",
      },
      {
        label: "Pending Decisions",
        value: String(stats.pending_decisions || 0),
        sub: (stats.total_decisions || 0) + " total logged",
      },
      {
        label: "Board Threads",
        value: String(stats.total_threads || 0),
        sub: (stats.total_posts || 0) + " total posts",
      },
    ];

    tiles.forEach((tile) => {
      strip.appendChild(
        el("div", { className: "stat-card" }, [
          el("div", { className: "stat-label", text: tile.label }),
          el("div", { className: "stat-value", text: tile.value }),
          el("div", { className: "stat-sub", text: tile.sub }),
        ])
      );
    });
  }

  // Tab 1: Hive Command Deck
  function renderHiveView(container) {
    const snap = state.snapshot;
    const prime = snap.prime || {};
    const primeState = Sprites.stateForAgent(prime, null);
    const blueprints = snap.blueprints || [];

    const primeCard = el(
      "article",
      {
        className: "prime-card",
        onClick: () => openPrimeDrawer(),
      },
      [
        el("div", { className: "prime-identity" }, [
          el("div", { className: "prime-sprite-frame" }, [
            Sprites.renderBotSvg("prime", primeState, 52),
          ]),
          el("div", null, [
            el("div", { className: "team-title-row" }, [
              el("h2", { className: "team-name", text: "ULTRON PRIME" }),
              el("span", {
                className: "badge " + (prime.status === "active" ? "badge-active" : "badge-standby"),
                text: upperStatus(prime.status, "unregistered"),
              }),
              prime.harness ? el("span", { className: "badge", text: prime.harness }) : null,
            ]),
            el("p", {
              className: "team-mission",
              text: "Root Orchestrator · Single User-to-Hive Interface & Provisioning Authority",
            }),
          ]),
        ]),
        el("div", { className: "prime-meta-grid" }, [
          el("span", {
            className: "badge mono",
            text: "doorbell: " + (prime.conversation_id || "unregistered"),
          }),
          el("span", {
            className: "badge",
            text: blueprints.length + " blueprints ready",
          }),
        ]),
      ]
    );
    container.appendChild(primeCard);

    const baseTeams = getBaseTeams(snap);
    const activeCount = baseTeams.filter((t) => t.status === "active").length;
    const visibleTeams = state.activeOnly
      ? baseTeams.filter((t) => t.status === "active")
      : baseTeams;

    const filterBar = el("div", { className: "filter-bar" }, [
      buildActiveOnlyToggle("hive-active-only", activeCount, baseTeams.length),
      el("span", {
        className: "filter-summary",
        text: state.activeOnly
          ? "Showing " +
            visibleTeams.length +
            " active · " +
            (baseTeams.length - visibleTeams.length) +
            " standby hidden"
          : activeCount + " active · " + (baseTeams.length - activeCount) + " standby",
      }),
    ]);
    container.appendChild(filterBar);

    if (baseTeams.length === 0) {
      container.appendChild(
        el("div", { className: "empty-state" }, [
          Sprites.renderBotSvg("specialist", "standby", 56),
          el("h3", { text: "No Active or Standing Teams in This Workspace" }),
          el("p", {
            text:
              "Create a project or team via ULTRON PRIME (or launch Mission Control with `ui --root ~/Dev/ULTRON_IMPERATIVE` to view your populated multi-team Hive).",
          }),
        ])
      );
      return;
    }

    if (visibleTeams.length === 0) {
      container.appendChild(
        el("div", { className: "empty-state" }, [
          Sprites.renderBotSvg("specialist", "standby", 56),
          el("h3", { text: "No Active Teams Right Now" }),
          el("p", {
            text:
              "All " +
              baseTeams.length +
              " team(s) in this workspace are currently on standby.",
          }),
          el("div", { className: "empty-actions" }, [
            el("button", {
              className: "btn btn-secondary",
              type: "button",
              text: "Show All Teams",
              onClick: () => setActiveOnly(false),
            }),
          ]),
        ])
      );
      return;
    }

    const visibleSlugs = new Set(visibleTeams.map((t) => t.slug));
    const byParent = new Map();
    visibleTeams.forEach((t) => {
      // Promote non-archived children whose parent is archived & hidden (matching core.format_org_tree)
      const pKey = t.parent_team && visibleSlugs.has(t.parent_team) ? t.parent_team : "__root__";
      if (!byParent.has(pKey)) byParent.set(pKey, []);
      byParent.get(pKey).push(t);
    });

    const treeWrap = el("div", { className: "hive-tree" });

    function buildTeamNode(team) {
      const children = (byParent.get(team.slug) || []).slice().sort((a, b) =>
        String(a.slug || "").localeCompare(String(b.slug || ""))
      );

      const lifespanBadge = team.archived
        ? el("span", { className: "badge badge-archived", text: "ARCHIVED" })
        : el("span", {
            className:
              "badge " + (team.lifespan === "ephemeral" ? "badge-ephemeral" : "badge-permanent"),
            text: upperStatus(team.lifespan, "permanent"),
          });

      const botBay = el("div", { className: "bot-bay" });
      (team.roles || []).forEach((role) => {
        const archetype = Sprites.archetypeForRole(role);
        const botState = Sprites.stateForAgent(role, team);
        const roBadge =
          role.write_tools === false
            ? el("span", { className: "badge", text: "RO" })
            : null;
        botBay.appendChild(
          el(
            "button",
            {
              className: "bot-tile " + (botState === "active" ? "is-active" : ""),
              type: "button",
              onClick: (ev) => {
                ev.stopPropagation();
                openTeamDrawer(team.slug, role.agent_id);
              },
            },
            [
              Sprites.renderBotSvg(archetype, botState, 36),
              el("div", { className: "bot-tile-info" }, [
                el("div", { className: "bot-tile-role" }, [
                  el("span", { className: "status-dot " + botState }),
                  role.role || role.agent_id,
                  roBadge,
                ]),
                el("div", { className: "bot-tile-title", text: role.title || role.role || "Role" }),
                el("div", {
                  className: "bot-tile-meta",
                  text:
                    (role.model || "medium") +
                    (role.harness ? " · " + role.harness : "") +
                    (team.archived ? " · archived" : role.status === "active" ? " · live" : " · standby"),
                }),
              ]),
            ]
          )
        );
      });

      const card = el(
        "article",
        {
          className:
            "team-card " +
            (team.status === "active" ? "is-active" : "") +
            (team.archived ? " is-archived" : ""),
        },
        [
          el(
            "div",
            {
              className: "team-header",
              onClick: () => openTeamDrawer(team.slug, null),
            },
            [
              el("div", { className: "team-title-block" }, [
                el("div", { className: "team-title-row" }, [
                  el("h3", { className: "team-name", text: team.name || team.slug }),
                  el("span", { className: "badge mono", text: "L" + team.layer + " · " + team.slug }),
                ]),
                el("p", { className: "team-mission", text: team.mission || "" }),
              ]),
              el("div", { className: "team-badges" }, [
                el("span", {
                  className: "badge " + (team.status === "active" ? "badge-active" : "badge-standby"),
                  text: team.status === "active" ? "ACTIVE" : "STANDBY",
                }),
                lifespanBadge,
                team.campaign === "active"
                  ? el("span", { className: "badge badge-campaign", text: "CAMPAIGN ON" })
                  : null,
                team.harness ? el("span", { className: "badge", text: team.harness }) : null,
                team.project
                  ? el("span", {
                      className: team.project_missing ? "badge badge-danger" : "badge badge-repo",
                      text:
                        "proj:" +
                        team.project +
                        (team.project_missing ? " (missing)" : ""),
                    })
                  : null,
                team.parent_team && !visibleSlugs.has(team.parent_team)
                  ? el("span", { className: "badge mono", text: "parent:" + team.parent_team })
                  : null,
              ]),
            ]
          ),
          team.target_repo
            ? el("div", { className: "team-path-row mono" }, [
                el("span", { text: "target: " + team.target_repo }),
              ])
            : null,
          botBay,
        ]
      );

      const nodeWrap = el("div", { className: "hive-node" }, [card]);
      if (children.length > 0) {
        const childBox = el("div", { className: "hive-children" });
        children.forEach((child) => childBox.appendChild(buildTeamNode(child)));
        nodeWrap.appendChild(childBox);
      }
      return nodeWrap;
    }

    (byParent.get("__root__") || [])
      .slice()
      .sort((a, b) => (a.layer || 1) - (b.layer || 1) || String(a.slug || "").localeCompare(String(b.slug || "")))
      .forEach((rootTeam) => treeWrap.appendChild(buildTeamNode(rootTeam)));

    container.appendChild(treeWrap);
  }

  // Tab 1b: Hive Organization (SVG Org Chart)
  function collectProjectDescendantSlugs(rootSlug, projects) {
    const out = new Set([rootSlug]);
    let added = true;
    while (added) {
      added = false;
      (projects || []).forEach((p) => {
        if (p.parent_project && out.has(p.parent_project) && !out.has(p.slug)) {
          out.add(p.slug);
          added = true;
        }
      });
    }
    return out;
  }

  function filterOrgTeams(allTeams, allProjects, projectFilter) {
    const teamsBySlug = new Map(allTeams.map((t) => [t.slug, t]));
    if (!projectFilter) return allTeams;

    let matching;
    if (projectFilter === "__bound__") {
      matching = allTeams.filter((t) => Boolean(t.project));
    } else if (projectFilter === "__unbound__") {
      matching = allTeams.filter((t) => !t.project);
    } else {
      const targetProjSet = collectProjectDescendantSlugs(projectFilter, allProjects);
      matching = allTeams.filter((t) => t.project && targetProjSet.has(t.project));
    }

    const keep = new Set();
    matching.forEach((t) => {
      let cur = t;
      const guard = new Set();
      while (cur && !guard.has(cur.slug)) {
        guard.add(cur.slug);
        keep.add(cur.slug);
        cur = cur.parent_team ? teamsBySlug.get(cur.parent_team) : null;
      }
    });
    return allTeams.filter((t) => keep.has(t.slug));
  }

  function buildHiveOrgSvg(prime, teams, expandRoles, zoomMode) {
    const visibleSlugs = new Set(teams.map((t) => t.slug));
    const byParent = new Map();
    teams.forEach((t) => {
      const pKey = t.parent_team && visibleSlugs.has(t.parent_team) ? t.parent_team : "__root__";
      if (!byParent.has(pKey)) byParent.set(pKey, []);
      byParent.get(pKey).push(t);
    });
    // Place multi-layer branches first so structured org trees stay front and center at the top
    byParent.forEach((arr) => {
      arr.sort((a, b) => {
        const aKids = (byParent.get(a.slug) || []).length > 0 ? 0 : 1;
        const bKids = (byParent.get(b.slug) || []).length > 0 ? 0 : 1;
        if (aKids !== bKids) return aKids - bKids;
        return String(a.slug || "").localeCompare(String(b.slug || ""));
      });
    });

    const padX = 28;
    const padY = 24;
    const primeW = 220;
    const primeH = 94;
    const teamW = 276;
    const teamH = expandRoles ? 76 : 94;
    const agentW = 216;
    const agentH = 40;
    const colGap = 68;
    const rowGap = 14;
    const roleGap = 6;

    const teamPositions = [];
    const agentPositions = [];
    const primeEdges = [];
    const subteamEdges = [];
    const roleEdges = [];

    let cursorY = padY;
    let maxColRight = padX + primeW;
    const visited = new Set();

    function colX(depth) {
      return padX + primeW + colGap + depth * (teamW + colGap);
    }

    function layoutTeam(team, depth) {
      if (!team || visited.has(team.slug)) return null;
      visited.add(team.slug);

      const x = colX(depth);
      const children = (byParent.get(team.slug) || []).filter((c) => !visited.has(c.slug));
      const roles = expandRoles ? (team.roles || []) : [];

      const blockStartY = cursorY;
      let firstChildCenter = null;
      let lastChildCenter = null;
      const roleNodesForTeam = [];
      const childNodesForTeam = [];

      // Place role branches aligned horizontally beside this team, then child subteams below
      roles.forEach((role) => {
        const rx = colX(depth + 1);
        const ry = cursorY;
        cursorY += agentH + roleGap;
        maxColRight = Math.max(maxColRight, rx + agentW);
        const centerY = ry + Math.round(agentH / 2);
        if (firstChildCenter === null) firstChildCenter = centerY;
        lastChildCenter = centerY;
        roleNodesForTeam.push({ team: team, role: role, x: rx, y: ry, centerY: centerY });
      });

      let ty;
      if (roleNodesForTeam.length > 0) {
        const rolesCenter = Math.round(
          (roleNodesForTeam[0].centerY + roleNodesForTeam[roleNodesForTeam.length - 1].centerY) / 2
        );
        ty = Math.max(blockStartY, rolesCenter - Math.round(teamH / 2));
        cursorY = Math.max(cursorY + 6, ty + teamH + rowGap);
      }

      children.forEach((child) => {
        const res = layoutTeam(child, depth + 1);
        if (res) {
          if (firstChildCenter === null) firstChildCenter = res.spanTopCenter;
          lastChildCenter = res.spanBottomCenter;
          childNodesForTeam.push(res.info);
        }
      });

      if (ty === undefined) {
        if (firstChildCenter !== null) {
          const subtreeSpanCenter = Math.round((firstChildCenter + lastChildCenter) / 2);
          ty = Math.max(blockStartY, subtreeSpanCenter - Math.round(teamH / 2));
          cursorY = Math.max(cursorY, ty + teamH + rowGap);
        } else {
          ty = cursorY;
          cursorY += teamH + rowGap;
        }
      }

      maxColRight = Math.max(maxColRight, x + teamW);
      const teamCenterY = ty + Math.round(teamH / 2);
      const info = {
        team: team,
        depth: depth,
        x: x,
        y: ty,
        centerY: teamCenterY,
      };
      teamPositions.push(info);

      roleNodesForTeam.forEach((rn) => {
        agentPositions.push(rn);
        roleEdges.push({ sx: x + teamW, sy: teamCenterY, tx: rn.x, ty: rn.centerY });
      });
      childNodesForTeam.forEach((cn) => {
        subteamEdges.push({ sx: x + teamW, sy: teamCenterY, tx: cn.x, ty: cn.centerY });
      });

      return {
        info: info,
        spanTopCenter: firstChildCenter !== null ? Math.min(teamCenterY, firstChildCenter) : teamCenterY,
        spanBottomCenter: lastChildCenter !== null ? Math.max(teamCenterY, lastChildCenter) : teamCenterY,
      };
    }

    const roots = byParent.get("__root__") || [];
    const rootInfos = [];
    roots.forEach((rt, idx) => {
      const startY = cursorY;
      const res = layoutTeam(rt, 0);
      if (res) {
        rootInfos.push(res.info);
      }
      if (idx < roots.length - 1 && (res && (byParent.get(rt.slug) || []).length > 0 || expandRoles)) {
        cursorY += 10;
      }
      void startY;
    });

    const totalH = Math.max(160, cursorY + padY - rowGap);
    const primeY =
      rootInfos.length > 0
        ? Math.max(
            padY,
            Math.round(
              (rootInfos[0].centerY + rootInfos[rootInfos.length - 1].centerY) / 2 -
                primeH / 2
            )
          )
        : padY;
    const primeX = padX;
    const primeCenterY = primeY + Math.round(primeH / 2);

    rootInfos.forEach((ri) => {
      primeEdges.push({ sx: primeX + primeW, sy: primeCenterY, tx: ri.x, ty: ri.centerY });
    });

    const svgW = Math.max(760, maxColRight + padX);
    const svgH = Math.max(totalH, primeY + primeH + padY);

    const primeEdgeLayer = svgEl("g", { className: "org-edges-prime" });
    primeEdges.forEach((e) => {
      const midX = Math.round((e.sx + e.tx) / 2);
      primeEdgeLayer.appendChild(
        svgEl("path", {
          d: "M " + e.sx + " " + e.sy + " C " + midX + " " + e.sy + ", " + midX + " " + e.ty + ", " + e.tx + " " + e.ty,
          fill: "none",
          stroke: "#fb7185",
          "stroke-opacity": "0.52",
          "stroke-width": "1.8",
        })
      );
      primeEdgeLayer.appendChild(svgEl("circle", { cx: e.tx, cy: e.ty, r: 2.8, fill: "#fb7185" }));
    });

    const subEdgeLayer = svgEl("g", { className: "org-edges-teams" });
    subteamEdges.forEach((e) => {
      const midX = Math.round((e.sx + e.tx) / 2);
      subEdgeLayer.appendChild(
        svgEl("path", {
          d: "M " + e.sx + " " + e.sy + " C " + midX + " " + e.sy + ", " + midX + " " + e.ty + ", " + e.tx + " " + e.ty,
          fill: "none",
          stroke: "#22d3ee",
          "stroke-opacity": "0.72",
          "stroke-width": "2",
        })
      );
      subEdgeLayer.appendChild(svgEl("circle", { cx: e.sx, cy: e.sy, r: 3, fill: "#22d3ee" }));
      subEdgeLayer.appendChild(svgEl("circle", { cx: e.tx, cy: e.ty, r: 3, fill: "#22d3ee" }));
    });

    const roleEdgeLayer = svgEl("g", { className: "org-edges-roles" });
    roleEdges.forEach((e) => {
      const midX = Math.round((e.sx + e.tx) / 2);
      roleEdgeLayer.appendChild(
        svgEl("path", {
          d: "M " + e.sx + " " + e.sy + " C " + midX + " " + e.sy + ", " + midX + " " + e.ty + ", " + e.tx + " " + e.ty,
          fill: "none",
          stroke: "#818cf8",
          "stroke-opacity": "0.55",
          "stroke-width": "1.4",
          "stroke-dasharray": "4 3",
        })
      );
      roleEdgeLayer.appendChild(svgEl("circle", { cx: e.tx, cy: e.ty, r: 2.4, fill: "#818cf8" }));
    });

    const nodesLayer = svgEl("g", { className: "org-nodes" });

    // 1. ULTRON PRIME Apex Node
    const pState = Sprites.stateForAgent(prime, null);
    const pStatusColor = prime && prime.status === "active" ? "#fb7185" : "#64748b";
    const pSprite = Sprites.renderBotSvg("prime", pState, 38);
    const primeNode = svgEl(
      "g",
      {
        className: "topo-node",
        transform: "translate(" + primeX + "," + primeY + ")",
        role: "button",
        tabindex: "0",
        onClick: () => openPrimeDrawer(),
        onKeydown: (ev) => {
          if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            openPrimeDrawer();
          }
        },
      },
      [
        svgEl("title", { text: "ULTRON PRIME — " + ((prime && prime.conversation_id) || "unregistered") }),
        svgEl("rect", {
          className: "topo-node-bg",
          x: 0,
          y: 0,
          width: primeW,
          height: primeH,
          rx: 10,
          fill: "#1a1423",
          stroke: "rgba(244, 63, 94, 0.58)",
          "stroke-width": "1.5",
        }),
        svgEl("rect", { x: 0, y: 10, width: 4, height: primeH - 20, rx: 2, fill: "#f43f5e" }),
        svgEl("g", { transform: "translate(14, 16)" }, [pSprite]),
        svgEl("text", {
          x: 62,
          y: 30,
          fill: "#eef4ff",
          "font-size": "13.5",
          "font-weight": "700",
          "font-family": "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif",
          text: "ULTRON PRIME",
        }),
        svgEl("text", {
          x: 62,
          y: 47,
          fill: "#fda4af",
          "font-size": "10.5",
          "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
          text: upperStatus(prime && prime.status, "unregistered") + ((prime && prime.harness) ? " · " + prime.harness : ""),
        }),
        svgEl("text", {
          x: 16,
          y: 77,
          fill: "#9fb0c7",
          "font-size": "10.5",
          "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
          text: rootInfos.length + " root team" + (rootInfos.length === 1 ? "" : "s") + " · " + teams.length + " total",
        }),
        svgEl("circle", { cx: primeW - 14, cy: 24, r: 4, fill: pStatusColor }),
      ]
    );
    nodesLayer.appendChild(primeNode);

    // 2. Team Nodes
    teamPositions.forEach(({ team, x, y }) => {
      const isAct = team.status === "active";
      const isArch = Boolean(team.archived);
      const accent = isArch
        ? "#475569"
        : isAct
          ? "#22d3ee"
          : team.lifespan === "ephemeral"
            ? "#c084fc"
            : "#818cf8";
      const rawName = String(team.name || team.slug);
      const shortName = rawName.length > 23 ? rawName.slice(0, 21) + "…" : rawName;
      const hiddenParent = team.parent_team && !visibleSlugs.has(team.parent_team) ? team.parent_team : "";
      const metaRaw =
        "L" +
        (team.layer || 1) +
        " · " +
        team.slug +
        (hiddenParent ? " · ↑" + hiddenParent : team.project ? " · " + team.project : "");
      const shortMeta = metaRaw.length > 35 ? metaRaw.slice(0, 33) + "…" : metaRaw;
      const statusText = isArch ? "ARCH" : isAct ? "LIVE" : team.lifespan === "ephemeral" ? "EPHEM" : "PERM";

      const childrenNodes = [
        svgEl("title", {
          text:
            rawName +
            " (" +
            team.slug +
            ")" +
            (hiddenParent ? " [parent: " + hiddenParent + "]" : "") +
            " — " +
            (team.mission || ""),
        }),
        svgEl("rect", {
          className: "topo-node-bg",
          x: 0,
          y: 0,
          width: teamW,
          height: teamH,
          rx: 8,
          fill: isArch ? "#101624" : "#151d2f",
          stroke: isAct ? "rgba(34, 211, 238, 0.55)" : "rgba(148, 163, 184, 0.3)",
          "stroke-width": isAct ? "1.5" : "1.1",
        }),
        svgEl("rect", { x: 0, y: 8, width: 4, height: teamH - 16, rx: 2, fill: accent }),
        svgEl("text", {
          x: 15,
          y: 23,
          fill: isArch ? "#9fb0c7" : "#eef4ff",
          "font-size": "12.5",
          "font-weight": "700",
          "font-family": "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif",
          text: shortName,
        }),
        svgEl("rect", {
          x: teamW - 56,
          y: 10,
          width: 44,
          height: 16,
          rx: 4,
          fill: "#0b101b",
          stroke: accent,
          "stroke-opacity": "0.55",
          "stroke-width": "1",
        }),
        svgEl("text", {
          x: teamW - 34,
          y: 21.5,
          "text-anchor": "middle",
          fill: accent,
          "font-size": "9.5",
          "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
          "font-weight": "700",
          text: statusText,
        }),
        svgEl("text", {
          x: 15,
          y: 41,
          fill: "#9fb0c7",
          "font-size": "10.5",
          "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
          text: shortMeta,
        }),
      ];

      if (!expandRoles) {
        const roles = team.roles || [];
        const shownRoles = roles.slice(0, 4);
        const slotW = 60;
        const slotGap = 5;
        shownRoles.forEach((r, rIdx) => {
          const rx = 14 + rIdx * (slotW + slotGap);
          const ry = 50;
          const rState = Sprites.stateForAgent(r, team);
          const rBot = Sprites.renderBotSvg(Sprites.archetypeForRole(r), rState, 18);
          const rLabel = String(r.role || "role");
          const shortRole = rLabel.length > 5 ? rLabel.slice(0, 4) + "…" : rLabel;
          const chip = svgEl(
            "g",
            {
              className: "org-role-chip",
              transform: "translate(" + rx + "," + ry + ")",
              onClick: (ev) => {
                ev.stopPropagation();
                openTeamDrawer(team.slug, r.agent_id);
              },
            },
            [
              svgEl("title", { text: r.agent_id + " — " + (r.title || r.role) + " (" + r.model + ")" }),
              svgEl("rect", {
                x: 0,
                y: 0,
                width: slotW,
                height: 34,
                rx: 5,
                fill: "#0b101b",
                stroke: rState === "active" ? "rgba(34, 211, 238, 0.45)" : "rgba(148, 163, 184, 0.18)",
                "stroke-width": "1",
              }),
              svgEl("g", { transform: "translate(4, 7)" }, [rBot]),
              svgEl("text", {
                x: 24,
                y: 21,
                fill: r.write_tools === false ? "#34d399" : "#eef4ff",
                "font-size": "9.5",
                "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
                "font-weight": "600",
                text: shortRole,
              }),
            ]
          );
          childrenNodes.push(chip);
        });
        if (roles.length > 4) {
          childrenNodes.push(
            svgEl("text", {
              x: teamW - 10,
              y: 89,
              "text-anchor": "end",
              fill: "#6f809b",
              "font-size": "9.5",
              "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
              text: "+" + (roles.length - 4) + " more",
            })
          );
        }
      } else {
        childrenNodes.push(
          svgEl("text", {
            x: 15,
            y: 61,
            fill: "#6f809b",
            "font-size": "10.5",
            "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
            text:
              (team.roles || []).length +
              " role(s)" +
              (team.harness ? " · " + team.harness : "") +
              (team.campaign === "active" ? " · CAMPAIGN ON" : ""),
          })
        );
      }

      const tNode = svgEl(
        "g",
        {
          className: "topo-node",
          transform: "translate(" + x + "," + y + ")",
          role: "button",
          tabindex: "0",
          onClick: () => openTeamDrawer(team.slug, null),
          onKeydown: (ev) => {
            if (ev.key === "Enter" || ev.key === " ") {
              ev.preventDefault();
              openTeamDrawer(team.slug, null);
            }
          },
        },
        childrenNodes
      );
      nodesLayer.appendChild(tNode);
    });

    // 3. Expanded Role Agent Nodes (when Show Role Branches is ON)
    agentPositions.forEach(({ team, role, x, y }) => {
      const rState = Sprites.stateForAgent(role, team);
      const rBot = Sprites.renderBotSvg(Sprites.archetypeForRole(role), rState, 26);
      const rAccent =
        rState === "active"
          ? "#22d3ee"
          : role.write_tools === false
            ? "#34d399"
            : "#64748b";
      const roleSlug = String(role.role || "role");
      const rawTitle = String(role.title || roleSlug);
      const shortTitle = rawTitle.length > 22 ? rawTitle.slice(0, 20) + "…" : rawTitle;

      const aNode = svgEl(
        "g",
        {
          className: "topo-node",
          transform: "translate(" + x + "," + y + ")",
          role: "button",
          tabindex: "0",
          onClick: () => openTeamDrawer(team.slug, role.agent_id),
          onKeydown: (ev) => {
            if (ev.key === "Enter" || ev.key === " ") {
              ev.preventDefault();
              openTeamDrawer(team.slug, role.agent_id);
            }
          },
        },
        [
          svgEl("title", { text: role.agent_id + " — " + rawTitle + " (" + (role.model || "medium") + ")" }),
          svgEl("rect", {
            className: "topo-node-bg",
            x: 0,
            y: 0,
            width: agentW,
            height: agentH,
            rx: 6,
            fill: "#0f1523",
            stroke: rState === "active" ? "rgba(34, 211, 238, 0.48)" : "rgba(129, 140, 248, 0.28)",
            "stroke-width": "1.1",
          }),
          svgEl("rect", { x: 0, y: 5, width: 3, height: agentH - 10, rx: 1.5, fill: rAccent }),
          svgEl("g", { transform: "translate(10, 7)" }, [rBot]),
          svgEl("text", {
            x: 42,
            y: 17,
            fill: "#eef4ff",
            "font-size": "11.5",
            "font-weight": "700",
            "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
            text: roleSlug + (role.write_tools === false ? " [RO]" : ""),
          }),
          svgEl("text", {
            x: 42,
            y: 31,
            fill: "#9fb0c7",
            "font-size": "10",
            "font-family": "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif",
            text: shortTitle,
          }),
          svgEl("text", {
            x: agentW - 10,
            y: 17,
            "text-anchor": "end",
            fill: rState === "active" ? "#22d3ee" : "#6f809b",
            "font-size": "9.5",
            "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
            text: role.model || "medium",
          }),
        ]
      );
      nodesLayer.appendChild(aNode);
    });

    const scale = zoomMode === "125" ? 1.25 : 1;
    const dispW = Math.round(svgW * scale);
    const dispH = Math.round(svgH * scale);
    const zoomClass =
      zoomMode === "125" ? "org-svg zoom-125" : zoomMode === "100" ? "org-svg zoom-100" : "org-svg zoom-fit";

    const svg = svgEl(
      "svg",
      {
        className: zoomClass,
        viewBox: "0 0 " + svgW + " " + svgH,
        width: dispW,
        height: dispH,
        role: "img",
        "aria-label": "ULTRON Hive Organization Chart",
      },
      [primeEdgeLayer, subEdgeLayer, roleEdgeLayer, nodesLayer]
    );

    return {
      svg: svg,
      shownTeamCount: teamPositions.length,
      shownAgentCount: expandRoles
        ? agentPositions.length
        : teamPositions.reduce((sum, tp) => sum + ((tp.team.roles || []).length), 0),
    };
  }

  function syncOrgProjectOptions() {
    const sel = document.getElementById("org-project-filter");
    if (!sel || !state.snapshot) return;
    const opts = state.orgOptions;
    const projects = state.snapshot.projects || [];
    clearNode(sel);
    sel.appendChild(el("option", { value: "", text: "All Teams (Full Hive)", selected: opts.project === "" }));
    sel.appendChild(el("option", { value: "__bound__", text: "Project-Bound Only", selected: opts.project === "__bound__" }));
    sel.appendChild(el("option", { value: "__unbound__", text: "Legacy / Unbound Only", selected: opts.project === "__unbound__" }));
    projects
      .slice()
      .sort((a, b) => (a.layer || 1) - (b.layer || 1) || String(a.slug).localeCompare(String(b.slug)))
      .forEach((p) => {
        sel.appendChild(
          el("option", {
            value: p.slug,
            text: "Project: " + (p.name || p.slug) + " (" + p.slug + ")",
            selected: opts.project === p.slug,
          })
        );
      });
  }

  function renderOrgView(container) {
    const opts = state.orgOptions;
    const baseTeams = getBaseTeams(state.snapshot);
    const activeCount = baseTeams.filter((t) => t.status === "active").length;

    const toolbar = el("div", { className: "filter-bar" }, [
      el(
        "select",
        {
          id: "org-project-filter",
          className: "filter-select",
          "aria-label": "Filter organization chart by project",
          onChange: (ev) => {
            opts.project = ev.target.value;
            renderOrgChartCanvas();
          },
        }
      ),
      buildActiveOnlyToggle("org-active-only", activeCount, baseTeams.length),
      el("label", { className: "toggle-chip", for: "org-expand-roles" }, [
        el("input", {
          id: "org-expand-roles",
          type: "checkbox",
          checked: opts.expandRoles,
          onChange: (ev) => {
            opts.expandRoles = Boolean(ev.target.checked);
            renderOrgChartCanvas();
          },
        }),
        el("span", { text: "Show Role Branches" }),
      ]),
      el("div", { id: "org-zoom-group", className: "zoom-group", role: "group", "aria-label": "Zoom level" }, [
        ["fit", "Fit"],
        ["100", "100%"],
        ["125", "125%"],
      ].map(([mode, label]) =>
        el("button", {
          className: "btn btn-sm btn-ghost" + (opts.zoom === mode ? " is-selected" : ""),
          type: "button",
          text: label,
          onClick: (ev) => {
            opts.zoom = mode;
            const grp = document.getElementById("org-zoom-group");
            if (grp) {
              grp.querySelectorAll("button").forEach((b) => b.classList.remove("is-selected"));
            }
            ev.currentTarget.classList.add("is-selected");
            renderOrgChartCanvas();
          },
        })
      )),
    ]);
    container.appendChild(toolbar);

    const chartHost = el("div", { id: "org-chart-host" });
    container.appendChild(chartHost);
    syncOrgProjectOptions();
    renderOrgChartCanvas();
  }

  function renderOrgChartCanvas() {
    const chartHost = document.getElementById("org-chart-host");
    if (!chartHost || !state.snapshot) return;
    clearNode(chartHost);

    const snap = state.snapshot;
    const opts = state.orgOptions;
    const baseTeams = getBaseTeams(snap);
    const activeCount = baseTeams.filter((t) => t.status === "active").length;
    syncActiveOnlyToggle("org-active-only", activeCount, baseTeams.length);

    const statusFiltered = state.activeOnly
      ? baseTeams.filter((t) => t.status === "active")
      : baseTeams;
    const filteredTeams = filterOrgTeams(statusFiltered, snap.projects || [], opts.project);

    if (filteredTeams.length === 0) {
      if (state.activeOnly) {
        const actions = [];
        if (opts.project) {
          actions.push(
            el("button", {
              className: "btn btn-ghost",
              type: "button",
              text: "Clear Project Filter",
              onClick: () => {
                opts.project = "";
                const sel = document.getElementById("org-project-filter");
                if (sel) sel.value = "";
                renderOrgChartCanvas();
              },
            })
          );
        }
        actions.push(
          el("button", {
            className: "btn btn-secondary",
            type: "button",
            text: "Show All Teams",
            onClick: () => setActiveOnly(false),
          })
        );
        chartHost.appendChild(
          el("div", { className: "empty-state" }, [
            Sprites.renderBotSvg("prime", "standby", 52),
            el("h3", {
              text: opts.project ? "No Active Teams Match This Filter" : "No Active Teams Right Now",
            }),
            el("p", {
              text:
                activeCount === 0
                  ? "All " + baseTeams.length + " team(s) in this workspace are currently on standby."
                  : activeCount + " active team(s) exist outside this project filter.",
            }),
            el("div", { className: "empty-actions" }, actions),
          ])
        );
      } else {
        chartHost.appendChild(
          el("div", { className: "empty-state" }, [
            Sprites.renderBotSvg("prime", "standby", 52),
            el("h3", { text: "No Teams Match This Organization Filter" }),
            el("p", { text: "Clear the project filter or toggle Show Archived to inspect other pods." }),
          ])
        );
      }
      return;
    }

    const built = buildHiveOrgSvg(snap.prime || {}, filteredTeams, opts.expandRoles, opts.zoom);
    const panel = el("section", { className: "topo-panel" }, [
      el("div", { className: "topo-header" }, [
        el("div", { className: "team-title-row" }, [
          el("h3", { className: "panel-card-title", text: "Organization Chart" }),
          el("span", {
            className: "badge mono",
            text: built.shownTeamCount + " team(s) · " + built.shownAgentCount + " role(s)",
          }),
        ]),
        el("div", { className: "topo-legend" }, [
          el("span", { className: "topo-legend-item" }, [
            el("span", { className: "legend-line legend-prime" }),
            "PRIME -> L1 Team",
          ]),
          el("span", { className: "topo-legend-item" }, [
            el("span", { className: "legend-line legend-solid" }),
            "Parent -> Subteam",
          ]),
          opts.expandRoles
            ? el("span", { className: "topo-legend-item" }, [
                el("span", { className: "legend-line legend-role" }),
                "Team -> Role Bot",
              ])
            : null,
        ]),
      ]),
      el("div", { className: "topo-svg-wrap org-svg-wrap" }, [built.svg]),
    ]);
    chartHost.appendChild(panel);
  }

  // Tab 2: Projects Topology
  function buildProjectTopologySvg(projects, byParent) {
    const visibleSlugs = new Set(projects.map((p) => p.slug));
    const nodeW = 248;
    const nodeH = 78;
    const colGap = 72;
    const rowGap = 24;
    const needsLeftGutter = projects.some((p) => {
      const children = byParent.get(p.slug) || [];
      if (p.parent_project && visibleSlugs.has(p.parent_project)) return false;
      return (p.relationships || []).some((r) => {
        if (!visibleSlugs.has(r.target)) return false;
        const tgt = projects.find((x) => x.slug === r.target);
        const tgtIsRoot = tgt && !(tgt.parent_project && visibleSlugs.has(tgt.parent_project));
        return tgtIsRoot && (children.length > 0 || (byParent.get(tgt.slug) || []).length > 0);
      });
    });
    const padX = needsLeftGutter ? 124 : 28;
    const padY = 24;

    const posMap = new Map();
    const hierarchyEdges = [];
    let leafRow = 0;
    let maxDepth = 0;
    const visited = new Set();

    function layoutSubtree(proj, depth) {
      if (!proj || visited.has(proj.slug)) return null;
      visited.add(proj.slug);
      maxDepth = Math.max(maxDepth, depth);
      const children = (byParent.get(proj.slug) || []).filter((c) => !visited.has(c.slug));

      let y = padY + leafRow * (nodeH + rowGap);
      let firstY = y;
      let lastY = y;

      if (children.length === 0) {
        leafRow += 1;
      } else {
        const spans = [];
        children.forEach((child) => {
          const sp = layoutSubtree(child, depth + 1);
          if (sp) spans.push(sp);
        });
        if (spans.length > 0) {
          firstY = spans[0].firstY;
          lastY = spans[spans.length - 1].lastY;
          y = Math.round((firstY + lastY) / 2);
        } else {
          leafRow += 1;
        }
      }

      const x = padX + depth * (nodeW + colGap);
      const nodeInfo = { proj: proj, depth: depth, x: x, y: y, hasChildren: children.length > 0 };
      posMap.set(proj.slug, nodeInfo);

      children.forEach((child) => {
        const childPos = posMap.get(child.slug);
        if (childPos) hierarchyEdges.push({ from: nodeInfo, to: childPos });
      });

      return { firstY: firstY, lastY: lastY };
    }

    (byParent.get("__root__") || []).forEach((rootProj) => layoutSubtree(rootProj, 0));

    const relEdges = [];
    projects.forEach((p) => {
      const fromPos = posMap.get(p.slug);
      if (!fromPos) return;
      (p.relationships || []).forEach((r) => {
        if (!visibleSlugs.has(r.target)) return;
        const toPos = posMap.get(r.target);
        if (toPos) {
          relEdges.push({ from: fromPos, to: toPos, relation: r.relation, note: r.note || "" });
        }
      });
    });

    const maxNodeRight = padX + (maxDepth + 1) * nodeW + maxDepth * colGap;
    const rightGutter = relEdges.length > 0 ? 156 + Math.max(0, relEdges.length - 1) * 34 : 28;
    const svgW = Math.max(720, maxNodeRight + rightGutter);
    const svgH = Math.max(
      140,
      padY * 2 + Math.max(1, leafRow) * nodeH + Math.max(0, leafRow - 1) * rowGap
    );

    const defs = svgEl("defs", null, [
      svgEl(
        "marker",
        {
          id: "topo-arrow",
          viewBox: "0 0 10 10",
          refX: "8",
          refY: "5",
          markerWidth: "7",
          markerHeight: "7",
          orient: "auto-start-reverse",
        },
        [svgEl("path", { d: "M 0 1.5 L 8.5 5 L 0 8.5 z", fill: "#c084fc" })]
      ),
    ]);

    const edgesLayer = svgEl("g", { className: "topo-edges" });
    hierarchyEdges.forEach(({ from, to }) => {
      const sx = from.x + nodeW;
      const sy = Math.round(from.y + nodeH / 2);
      const tx = to.x;
      const ty = Math.round(to.y + nodeH / 2);
      const midX = Math.round((sx + tx) / 2);
      edgesLayer.appendChild(
        svgEl("path", {
          d: "M " + sx + " " + sy + " C " + midX + " " + sy + ", " + midX + " " + ty + ", " + tx + " " + ty,
          fill: "none",
          stroke: "#22d3ee",
          "stroke-opacity": "0.65",
          "stroke-width": "2",
        })
      );
      edgesLayer.appendChild(svgEl("circle", { cx: sx, cy: sy, r: 3, fill: "#22d3ee" }));
      edgesLayer.appendChild(svgEl("circle", { cx: tx, cy: ty, r: 3, fill: "#22d3ee" }));
    });

    const relLayer = svgEl("g", { className: "topo-rels" });
    relEdges.forEach((edge, idx) => {
      const useLeft = edge.from.depth === 0 && edge.from.hasChildren || edge.to.depth === 0 && edge.to.hasChildren;
      let sx;
      let sy;
      let tx;
      let ty;
      let cx1;
      let cy1;
      let cx2;
      let cy2;

      if (useLeft && edge.from.depth === 0 && edge.to.depth === 0) {
        sx = edge.from.x;
        sy = Math.round(edge.from.y + nodeH / 2);
        tx = edge.to.x - 4;
        ty = Math.round(edge.to.y + nodeH / 2);
        const leftLane = Math.max(24, padX - 64 - idx * 14);
        cx1 = leftLane;
        cy1 = sy;
        cx2 = leftLane;
        cy2 = ty;
      } else {
        sx = edge.from.x + nodeW;
        sy = Math.round(edge.from.y + nodeH / 2);
        tx = edge.to.x + nodeW + 4;
        ty = Math.round(edge.to.y + nodeH / 2);
        const rightLane = maxNodeRight + 74 + idx * 34;
        cx1 = rightLane;
        cy1 = sy;
        cx2 = rightLane;
        cy2 = ty;
      }

      const d =
        "M " +
        sx +
        " " +
        sy +
        " C " +
        cx1 +
        " " +
        cy1 +
        ", " +
        cx2 +
        " " +
        cy2 +
        ", " +
        tx +
        " " +
        ty;
      const pathEl = svgEl("path", {
        d: d,
        fill: "none",
        stroke: "#c084fc",
        "stroke-opacity": "0.85",
        "stroke-width": "1.75",
        "stroke-dasharray": "5 4",
        "marker-end": "url(#topo-arrow)",
      });
      pathEl.appendChild(
        svgEl("title", {
          text:
            edge.from.proj.slug +
            " " +
            edge.relation +
            " " +
            edge.to.proj.slug +
            (edge.note ? " — " + edge.note : ""),
        })
      );
      relLayer.appendChild(pathEl);

      // Bezier midpoint at t=0.5 puts pill label directly on the curve outside boxes
      const lx = Math.round(0.125 * sx + 0.375 * cx1 + 0.375 * cx2 + 0.125 * tx);
      const ly = Math.round(0.125 * sy + 0.375 * cy1 + 0.375 * cy2 + 0.125 * ty);
      const labelText = edge.relation;
      const pillW = Math.max(76, labelText.length * 7 + 16);
      relLayer.appendChild(
        svgEl("rect", {
          x: lx - Math.round(pillW / 2),
          y: ly - 10,
          width: pillW,
          height: 20,
          rx: 5,
          fill: "#101624",
          stroke: "#c084fc",
          "stroke-opacity": "0.7",
          "stroke-width": "1",
        })
      );
      relLayer.appendChild(
        svgEl("text", {
          x: lx,
          y: ly + 4,
          "text-anchor": "middle",
          fill: "#e9d5ff",
          "font-size": "10.5",
          "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
          "font-weight": "600",
          text: labelText,
        })
      );
    });

    const nodesLayer = svgEl("g", { className: "topo-nodes" });
    posMap.forEach(({ proj, x, y }) => {
      const statusColor =
        proj.status === "archived"
          ? "#475569"
          : proj.status === "paused"
            ? "#f59e0b"
            : "#22d3ee";
      const rawTitle = String(proj.name || proj.slug);
      const shortTitle = rawTitle.length > 26 ? rawTitle.slice(0, 24) + "…" : rawTitle;
      const subLine = "L" + (proj.layer || 1) + " · " + proj.slug + (proj.subpath ? " / " + proj.subpath : "");
      const shortSub = subLine.length > 31 ? subLine.slice(0, 29) + "…" : subLine;
      const teamsLabel = (proj.teams || []).length + " team" + ((proj.teams || []).length === 1 ? "" : "s");

      const group = svgEl(
        "g",
        {
          className: "topo-node",
          transform: "translate(" + x + "," + y + ")",
          role: "button",
          tabindex: "0",
          onClick: () => openProjectDrawer(proj.slug),
          onKeydown: (ev) => {
            if (ev.key === "Enter" || ev.key === " ") {
              ev.preventDefault();
              openProjectDrawer(proj.slug);
            }
          },
        },
        [
          svgEl("title", { text: rawTitle + " — " + (proj.effective_target_path || proj.slug) }),
          svgEl("rect", {
            className: "topo-node-bg",
            x: 0,
            y: 0,
            width: nodeW,
            height: nodeH,
            rx: 8,
            fill: "#151d2f",
            stroke: proj.status === "archived" ? "#334155" : "rgba(148, 163, 184, 0.32)",
            "stroke-width": "1.2",
          }),
          svgEl("rect", {
            x: 0,
            y: 8,
            width: 4,
            height: nodeH - 16,
            rx: 2,
            fill: statusColor,
          }),
          svgEl("text", {
            x: 16,
            y: 25,
            fill: "#eef4ff",
            "font-size": "13",
            "font-weight": "700",
            "font-family": "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif",
            text: shortTitle,
          }),
          svgEl("text", {
            x: 16,
            y: 44,
            fill: "#9fb0c7",
            "font-size": "11",
            "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
            text: shortSub,
          }),
          svgEl("rect", {
            x: 16,
            y: 53,
            width: 66,
            height: 17,
            rx: 4,
            fill: "#0b101b",
            stroke: "rgba(34, 211, 238, 0.3)",
            "stroke-width": "1",
          }),
          svgEl("text", {
            x: 49,
            y: 65,
            "text-anchor": "middle",
            fill: "#22d3ee",
            "font-size": "10",
            "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
            "font-weight": "600",
            text: teamsLabel,
          }),
          svgEl("text", {
            x: nodeW - 14,
            y: 65,
            "text-anchor": "end",
            fill: statusColor,
            "font-size": "10",
            "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
            "font-weight": "700",
            text: upperStatus(proj.status, "active"),
          }),
        ]
      );
      nodesLayer.appendChild(group);
    });

    const svg = svgEl(
      "svg",
      {
        className: "topo-svg",
        viewBox: "0 0 " + svgW + " " + svgH,
        width: svgW,
        height: svgH,
        role: "img",
        "aria-label": "Projects Hierarchy and Relationships Diagram",
      },
      [defs, edgesLayer, relLayer, nodesLayer]
    );

    return el("section", { className: "topo-panel" }, [
      el("div", { className: "topo-header" }, [
        el("h3", { className: "panel-card-title", text: "Topology Map" }),
        el("div", { className: "topo-legend" }, [
          el("span", { className: "topo-legend-item" }, [
            el("span", { className: "legend-line legend-solid" }),
            "Sub-project hierarchy",
          ]),
          el("span", { className: "topo-legend-item" }, [
            el("span", { className: "legend-line legend-dashed" }),
            "Cross-project relationship",
          ]),
        ]),
      ]),
      el("div", { className: "topo-svg-wrap" }, [svg]),
    ]);
  }

  function renderProjectsView(container) {
    const snap = state.snapshot;
    const allProjects = snap.projects || [];
    const projects = state.showArchived
      ? allProjects
      : allProjects.filter((p) => p.status !== "archived");

    if (projects.length === 0) {
      container.appendChild(
        el("div", { className: "empty-state" }, [
          Sprites.renderBotSvg("architect", "standby", 52),
          el("h3", { text: "No Projects Registered Yet" }),
          el("p", {
            text:
              "Use create-project --slug <slug> --name <name> --repo-path <path> to catalog monorepos, sub-projects, and typed inter-project links.",
          }),
        ])
      );
      return;
    }

    const visibleSlugs = new Set(projects.map((p) => p.slug));
    const byParent = new Map();
    projects.forEach((p) => {
      const pKey = p.parent_project && visibleSlugs.has(p.parent_project) ? p.parent_project : "__root__";
      if (!byParent.has(pKey)) byParent.set(pKey, []);
      byParent.get(pKey).push(p);
    });
    byParent.forEach((arr) =>
      arr.sort((a, b) => (a.layer || 1) - (b.layer || 1) || String(a.slug || "").localeCompare(String(b.slug || "")))
    );

    container.appendChild(buildProjectTopologySvg(projects, byParent));

    const treeWrap = el("div", { className: "hive-tree" });
    const teamsBySlug = new Map((snap.teams || []).map((t) => [t.slug, t]));

    function buildProjectNode(p) {
      const children = byParent.get(p.slug) || [];
      const statusCls =
        p.status === "archived" ? "badge-archived" : p.status === "paused" ? "badge-warn" : "badge-active";

      const teamChips = (p.teams || []).map((t) => {
        const fullTeam = teamsBySlug.get(t.slug);
        const dotCls = fullTeam && fullTeam.archived ? "archived" : t.status === "active" ? "active" : "standby";
        return el(
          "button",
          {
            className: "btn btn-sm btn-ghost",
            type: "button",
            onClick: (ev) => {
              ev.stopPropagation();
              openTeamDrawer(t.slug, null);
            },
          },
          [
            el("span", { className: "status-dot " + dotCls }),
            t.slug,
            el("span", { className: "badge", text: t.lifespan || "permanent" }),
          ]
        );
      });

      const relChips = (p.relationships || []).map((r) =>
        el("button", {
          className: "badge badge-rel",
          type: "button",
          title: r.note || r.relation + " -> " + r.target,
          text: r.relation + " -> " + r.target,
          onClick: (ev) => {
            ev.stopPropagation();
            openProjectDrawer(r.target);
          },
        })
      );

      const card = el(
        "article",
        {
          className: "team-card project-card" + (p.status === "archived" ? " is-archived" : ""),
          onClick: () => openProjectDrawer(p.slug),
        },
        [
          el("div", { className: "team-header" }, [
            el("div", { className: "team-title-block" }, [
              el("div", { className: "team-title-row" }, [
                el("h3", { className: "team-name", text: p.name || p.slug }),
                el("span", { className: "badge mono", text: "L" + (p.layer || 1) + " · " + p.slug }),
                p.subpath ? el("span", { className: "badge mono", text: "subpath:" + p.subpath }) : null,
              ]),
              p.description ? el("p", { className: "team-mission", text: p.description }) : null,
            ]),
            el("div", { className: "team-badges" }, [
              el("span", { className: "badge " + statusCls, text: upperStatus(p.status, "active") }),
              el("span", { className: "badge", text: (p.subprojects || []).length + " subproject(s)" }),
            ]),
          ]),
          p.effective_target_path
            ? el("div", {
                className: "team-path-row mono",
                text: "path: " + p.effective_target_path,
              })
            : null,
          teamChips.length > 0 || relChips.length > 0
            ? el("div", { className: "project-meta-strip" }, [
                teamChips.length > 0
                  ? el("div", { className: "team-badges" }, teamChips)
                  : null,
                relChips.length > 0
                  ? el("div", { className: "team-badges" }, relChips)
                  : null,
              ])
            : null,
        ]
      );

      const nodeWrap = el("div", { className: "hive-node" }, [card]);
      if (children.length > 0) {
        const childBox = el("div", { className: "hive-children" });
        children.forEach((child) => childBox.appendChild(buildProjectNode(child)));
        nodeWrap.appendChild(childBox);
      }
      return nodeWrap;
    }

    (byParent.get("__root__") || []).forEach((rootProj) =>
      treeWrap.appendChild(buildProjectNode(rootProj))
    );
    container.appendChild(treeWrap);
  }

  // Tab 3: Prime Decisions Queue
  function renderDecisionsView(container) {
    const f = state.decisionFilters;

    const filterBar = el("div", { className: "filter-bar" }, [
      el("select", {
        id: "dec-status-filter",
        className: "filter-select",
        "aria-label": "Filter decisions by status",
        onChange: (ev) => {
          f.status = ev.target.value;
          renderDecisionsList();
        },
      }, [
        el("option", { value: "", text: "All Review Statuses", selected: f.status === "" }),
        el("option", { value: "pending_review", text: "Pending Review", selected: f.status === "pending_review" }),
        el("option", { value: "needs_improvement", text: "Needs Improvement", selected: f.status === "needs_improvement" }),
        el("option", { value: "approved", text: "Approved", selected: f.status === "approved" }),
        el("option", { value: "overruled", text: "Overruled", selected: f.status === "overruled" }),
      ]),
      el("select", {
        id: "dec-origin-filter",
        className: "filter-select",
        "aria-label": "Filter decisions by origin",
        onChange: (ev) => {
          f.origin = ev.target.value;
          renderDecisionsList();
        },
      }, [
        el("option", { value: "", text: "All Origins", selected: f.origin === "" }),
        el("option", { value: "prime_autonomous", text: "prime_autonomous", selected: f.origin === "prime_autonomous" }),
        el("option", { value: "user_guided", text: "user_guided", selected: f.origin === "user_guided" }),
      ]),
      el("select", {
        id: "dec-scope-filter",
        className: "filter-select",
        "aria-label": "Filter decisions by scope",
        onChange: (ev) => {
          f.scope = ev.target.value;
          renderDecisionsList();
        },
      }, [
        el("option", { value: "", text: "All Scopes", selected: f.scope === "" }),
        el("option", { value: "global", text: "global", selected: f.scope === "global" }),
        el("option", { value: "project", text: "project", selected: f.scope === "project" }),
        el("option", { value: "team", text: "team", selected: f.scope === "team" }),
      ]),
      el("input", {
        id: "dec-search-filter",
        className: "filter-input",
        type: "search",
        placeholder: "Search title, ruling, tags, project...",
        value: f.query,
        onInput: (ev) => {
          f.query = ev.target.value;
          renderDecisionsList();
        },
      }),
    ]);
    container.appendChild(filterBar);

    const listHost = el("div", { id: "decisions-list", className: "list-stack" });
    container.appendChild(listHost);
    renderDecisionsList();
  }

  function renderDecisionsList() {
    const listHost = document.getElementById("decisions-list");
    if (!listHost || !state.snapshot) return;
    clearNode(listHost);

    const snap = state.snapshot;
    const decisions = snap.decisions || [];
    const totalDecisions = (snap.stats && snap.stats.total_decisions) || decisions.length;
    const trunc = buildTruncationNotice(decisions.length, totalDecisions, "decisions");
    if (trunc) listHost.appendChild(trunc);

    const f = state.decisionFilters;
    const q = f.query.trim().toLowerCase();

    const matches = decisions.filter((d) => {
      if (f.status && d.review_status !== f.status) return false;
      if (f.origin && d.origin !== f.origin) return false;
      if (f.scope && d.scope !== f.scope) return false;
      if (q) {
        const hay = [d.id, d.title, d.decision, d.rationale, d.project_slug, d.team_slug, d.tags]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    if (matches.length === 0) {
      listHost.appendChild(
        el("div", { className: "empty-state" }, [
          Sprites.renderBotSvg("prime", "standby", 48),
          el("h3", { text: "No Matching Prime Decisions" }),
          el("p", {
            text:
              decisions.length === 0
                ? "Autonomous Prime rulings and User-guided directives logged via `log-decision` will appear here for review."
                : "Adjust your status, origin, or search filters to view other recorded decisions.",
          }),
        ])
      );
      return;
    }

    matches.forEach((d) => {
      const stCls =
        d.review_status === "approved"
          ? "badge-ro"
          : d.review_status === "overruled"
            ? "badge-danger"
            : "badge-warn";
      const copyCmd =
        "python3 ultron/core/core.py review-decision " +
        shellQuote(d.id) +
        ' --status approved --notes "Confirmed."';

      listHost.appendChild(
        el(
          "article",
          { className: "panel-card", onClick: () => openDecisionDrawer(d.id) },
          [
            el("div", { className: "panel-card-header" }, [
              el("h3", { className: "panel-card-title", text: d.title || d.id }),
              el("div", { className: "team-badges" }, [
                el("span", { className: "badge " + stCls, text: upperStatus(d.review_status, "pending_review") }),
                el("span", { className: "badge", text: d.origin || "prime_autonomous" }),
                el("span", { className: "badge badge-repo", text: formatScopeBadge(d) }),
                d.original_decision && d.original_decision !== d.decision
                  ? el("span", { className: "badge badge-ephemeral", text: "REVISED" })
                  : null,
              ]),
            ]),
            el("p", { className: "panel-card-body", text: d.decision || "" }),
            d.latest_review_notes
              ? el("div", {
                  className: "team-path-row",
                  text: "Latest review note: " + d.latest_review_notes,
                })
              : null,
            el("div", { className: "panel-card-footer" }, [
              el("span", {
                className: "mono",
                text: d.id + " · updated " + shortTime(d.updated_at),
              }),
              el("button", {
                className: "btn btn-sm btn-secondary",
                type: "button",
                text: "Copy review-decision CLI",
                onClick: (ev) => {
                  ev.stopPropagation();
                  copyCli(copyCmd);
                },
              }),
            ]),
          ]
        )
      );
    });
  }

  // Tab 4: Board Activity Feed
  function renderBoardView(container) {
    const f = state.boardFilters;

    const filterBar = el("div", { className: "filter-bar" }, [
      el("select", {
        id: "board-vis-filter",
        className: "filter-select",
        "aria-label": "Filter board by visibility",
        onChange: (ev) => {
          f.visibility = ev.target.value;
          renderBoardList();
        },
      }, [
        el("option", { value: "", text: "All Visibilities", selected: f.visibility === "" }),
        el("option", { value: "global", text: "global", selected: f.visibility === "global" }),
        el("option", { value: "team", text: "team", selected: f.visibility === "team" }),
        el("option", { value: "personal", text: "personal", selected: f.visibility === "personal" }),
      ]),
      el("select", {
        id: "board-status-filter",
        className: "filter-select",
        "aria-label": "Filter board by status",
        onChange: (ev) => {
          f.status = ev.target.value;
          renderBoardList();
        },
      }, [
        el("option", { value: "", text: "All Statuses", selected: f.status === "" }),
        el("option", { value: "open", text: "open", selected: f.status === "open" }),
        el("option", { value: "in_progress", text: "in_progress", selected: f.status === "in_progress" }),
        el("option", { value: "blocked", text: "blocked", selected: f.status === "blocked" }),
        el("option", { value: "resolved", text: "resolved", selected: f.status === "resolved" }),
        el("option", { value: "closed", text: "closed", selected: f.status === "closed" }),
      ]),
      el("select", {
        id: "board-team-filter",
        className: "filter-select",
        "aria-label": "Filter board by team",
        onChange: (ev) => {
          f.team = ev.target.value;
          renderBoardList();
        },
      }),
      el("input", {
        id: "board-search-filter",
        className: "filter-input",
        type: "search",
        placeholder: "Search thread title, ID, author, category...",
        value: f.query,
        onInput: (ev) => {
          f.query = ev.target.value;
          renderBoardList();
        },
      }),
    ]);
    container.appendChild(filterBar);

    const listHost = el("div", { id: "board-list", className: "list-stack" });
    container.appendChild(listHost);
    syncBoardTeamOptions();
    renderBoardList();
  }

  function syncBoardTeamOptions() {
    const sel = document.getElementById("board-team-filter");
    if (!sel || !state.snapshot) return;
    const f = state.boardFilters;
    const threads = state.snapshot.threads || [];
    const teamOptions = Array.from(
      new Set(threads.map((t) => t.team_slug).filter(Boolean))
    ).sort();
    clearNode(sel);
    sel.appendChild(el("option", { value: "", text: "All Teams", selected: f.team === "" }));
    teamOptions.forEach((slug) => {
      sel.appendChild(el("option", { value: slug, text: slug, selected: f.team === slug }));
    });
  }

  function renderBoardList() {
    const listHost = document.getElementById("board-list");
    if (!listHost || !state.snapshot) return;
    clearNode(listHost);

    const snap = state.snapshot;
    const threads = snap.threads || [];
    const totalThreads = (snap.stats && snap.stats.total_threads) || threads.length;
    const trunc = buildTruncationNotice(threads.length, totalThreads, "threads");
    if (trunc) listHost.appendChild(trunc);

    const f = state.boardFilters;
    const q = f.query.trim().toLowerCase();

    const matches = threads.filter((t) => {
      if (f.visibility && t.visibility !== f.visibility) return false;
      if (f.status && t.status !== f.status) return false;
      if (f.team && t.team_slug !== f.team && t.with_team !== f.team) return false;
      if (q) {
        const hay = [t.id, t.title, t.author, t.category, t.team_slug, t.with_team]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    if (matches.length === 0) {
      listHost.appendChild(
        el("div", { className: "empty-state" }, [
          Sprites.renderBotSvg("architect", "standby", 48),
          el("h3", { text: "No Board Threads Match Current Filters" }),
          el("p", {
            text: "Append-only JSONL conversations from ultron/core/threads/ appear here as teams collaborate.",
          }),
        ])
      );
      return;
    }

    matches.forEach((t) => {
      const statusCls =
        t.status === "blocked"
          ? "badge-danger"
          : t.status === "resolved" || t.status === "closed"
            ? "badge-ro"
            : "badge-active";
      listHost.appendChild(
        el(
          "article",
          { className: "panel-card", onClick: () => openThreadDrawer(t.id) },
          [
            el("div", { className: "panel-card-header" }, [
              el("h3", { className: "panel-card-title", text: t.title || t.id }),
              el("div", { className: "team-badges" }, [
                el("span", { className: "badge " + statusCls, text: upperStatus(t.status, "open") }),
                el("span", { className: "badge", text: t.category || "general" }),
                el("span", { className: "badge badge-repo", text: formatThreadScope(t) }),
              ]),
            ]),
            el("div", { className: "panel-card-footer" }, [
              el("span", {
                className: "mono",
                text: t.id + " · by @" + (t.author || "unknown") + " · updated " + shortTime(t.updated_at),
              }),
              el("span", { className: "badge", text: (t.post_count || 1) + " post(s)" }),
            ]),
          ]
        )
      );
    });
  }

  // Slide-Over Inspector Drawer
  function openDrawer(kicker, title, bodyNodes) {
    document.getElementById("drawer-kicker").textContent = kicker;
    document.getElementById("drawer-title").textContent = title;
    const body = document.getElementById("drawer-body");
    clearNode(body);
    bodyNodes.filter(Boolean).forEach((n) => body.appendChild(n));
    document.getElementById("drawer-backdrop").classList.remove("hidden");
    document.getElementById("inspector-drawer").classList.remove("hidden");
  }

  function closeDrawer() {
    state.drawerRequestSeq += 1;
    state.drawerMode = null;
    document.getElementById("drawer-backdrop").classList.add("hidden");
    document.getElementById("inspector-drawer").classList.add("hidden");
  }

  function refreshOpenDrawer() {
    if (!state.drawerMode || !state.snapshot) return;
    if (state.drawerMode.kind === "prime") {
      openPrimeDrawer();
    } else if (state.drawerMode.kind === "team") {
      openTeamDrawer(state.drawerMode.slug, state.drawerMode.agentId);
    } else if (state.drawerMode.kind === "project") {
      openProjectDrawer(state.drawerMode.slug);
    }
  }

  function openPrimeDrawer() {
    const snap = state.snapshot;
    if (!snap) return;
    const p = snap.prime || {};
    state.drawerRequestSeq += 1;
    state.drawerMode = { kind: "prime" };
    openDrawer("Root Orchestrator", "ULTRON PRIME", [
      renderKvSection("Registration & Runtime", [
        ["agent_id", p.agent_id],
        ["status", p.status],
        ["harness", p.harness],
        ["conversation_id", p.conversation_id],
        ["last_seen", shortTime(p.last_seen)],
        ["repo_root", snap.repo_root],
      ]),
      cliSnippetBox(
        "Prime Boot & Decision Catch-Up CLI",
        "python3 ultron/core/core.py decisions --pending\npython3 ultron/core/core.py org-tree\npython3 ultron/core/core.py verify"
      ),
    ]);
  }

  function openTeamDrawer(teamSlug, focusAgentId) {
    const snap = state.snapshot;
    if (!snap) return;
    const team = (snap.teams || []).find((t) => t.slug === teamSlug);
    if (!team) return;
    state.drawerRequestSeq += 1;
    state.drawerMode = { kind: "team", slug: teamSlug, agentId: focusAgentId };

    const focusRole = focusAgentId
      ? (team.roles || []).find((r) => r.agent_id === focusAgentId)
      : null;

    const focusSection = focusRole
      ? renderKvSection("Selected Role Bot: " + focusRole.agent_id, [
          ["title", focusRole.title],
          ["status", focusRole.status],
          ["model_tier", focusRole.model],
          ["write_tools", focusRole.write_tools ? "true (read/write)" : "false (read-only)"],
          ["harness", focusRole.harness],
          ["conversation_id", focusRole.conversation_id],
          ["session_id", focusRole.session_id],
          ["responsibilities", focusRole.responsibilities],
        ])
      : null;

    const roleRows = el("div", { className: "list-stack" });
    (team.roles || []).forEach((r) => {
      roleRows.appendChild(
        el(
          "button",
          {
            className: "bot-tile " + (r.status === "active" ? "is-active" : ""),
            type: "button",
            onClick: () => openTeamDrawer(teamSlug, r.agent_id),
          },
          [
            Sprites.renderBotSvg(
              Sprites.archetypeForRole(r),
              Sprites.stateForAgent(r, team),
              34
            ),
            el("div", { className: "bot-tile-info" }, [
              el("div", { className: "bot-tile-role", text: r.agent_id }),
              el("div", {
                className: "bot-tile-title",
                text: (r.title || r.role || "Role") + " (" + (r.model || "medium") + ")",
              }),
            ]),
          ]
        )
      );
    });

    const allTeamThreads = (snap.threads || []).filter(
      (t) => t.team_slug === teamSlug || t.with_team === teamSlug
    );
    const recentThreads = allTeamThreads.slice(0, 8);
    const threadHeading =
      "Team Board Threads (" +
      recentThreads.length +
      (allTeamThreads.length > recentThreads.length ? " of " + allTeamThreads.length : "") +
      ")";

    const threadSec = el("div", { className: "detail-section" }, [
      el("h3", { text: threadHeading }),
      recentThreads.length === 0
        ? el("p", { className: "panel-card-body", text: "No board threads for this team yet." })
        : el(
            "div",
            { className: "list-stack" },
            recentThreads.map((t) =>
              el(
                "button",
                {
                  className: "btn btn-ghost",
                  style: "justify-content:space-between;width:100%;",
                  type: "button",
                  onClick: () => openThreadDrawer(t.id),
                },
                [
                  el("span", { text: t.title || t.id }),
                  el("span", { className: "badge", text: t.status || "open" }),
                ]
              )
            )
          ),
    ]);

    const teamTitleBase = team.name || team.slug;
    const teamDrawerTitle = teamTitleBase.endsWith("(" + team.slug + ")")
      ? teamTitleBase
      : teamTitleBase + " (" + team.slug + ")";

    const spawnCmd =
      "python3 ultron/core/core.py " +
      (team.status === "active" ? "stop-team " : "spawn-team ") +
      shellQuote(team.slug);

    openDrawer("Team · Layer " + (team.layer || 1), teamDrawerTitle, [
      renderKvSection("Manifest & Project Binding", [
        ["status", team.status],
        ["lifespan", team.archived ? team.lifespan + " (archived)" : team.lifespan],
        ["project", team.project ? team.project + (team.project_missing ? " (MISSING)" : "") : ""],
        ["target_repo", team.target_repo],
        ["parent_team", team.parent_team || "ultron-prime"],
        ["blueprint", team.blueprint],
        ["harness", team.harness],
        ["campaign", team.campaign],
        ["hive_path", team.hive_path],
        ["mission", team.mission],
      ]),
      focusSection,
      el("div", { className: "detail-section" }, [
        el("h3", { text: "Role Roster (" + (team.roles || []).length + ")" }),
        roleRows,
      ]),
      threadSec,
      cliSnippetBox(
        team.status === "active" ? "Stand Down Team CLI" : "Spawn Team CLI",
        spawnCmd
      ),
    ]);
  }

  function openProjectDrawer(projectSlug) {
    const snap = state.snapshot;
    if (!snap) return;
    const proj = (snap.projects || []).find((p) => p.slug === projectSlug);
    if (!proj) return;
    state.drawerRequestSeq += 1;
    state.drawerMode = { kind: "project", slug: projectSlug };

    const relSection =
      (proj.relationships || []).length > 0
        ? el("div", { className: "detail-section" }, [
            el("h3", { text: "Relationships (" + proj.relationships.length + ")" }),
            el(
              "div",
              { className: "team-badges" },
              proj.relationships.map((r) =>
                el("button", {
                  className: "btn btn-sm btn-ghost",
                  type: "button",
                  text: r.relation + " -> " + r.target + (r.note ? " (" + r.note + ")" : ""),
                  onClick: () => openProjectDrawer(r.target),
                })
              )
            ),
          ])
        : null;

    const boundSection = el("div", { className: "detail-section" }, [
      el("h3", { text: "Bound Teams (" + (proj.teams || []).length + ")" }),
      (proj.teams || []).length === 0
        ? el("p", { className: "panel-card-body", text: "No active/standing teams bound." })
        : el(
            "div",
            { className: "team-badges" },
            proj.teams.map((t) =>
              el("button", {
                className: "btn btn-sm btn-secondary",
                type: "button",
                text: t.slug + " [" + t.status + "/" + t.lifespan + "]",
                onClick: () => openTeamDrawer(t.slug, null),
              })
            )
          ),
    ]);

    openDrawer(
      "Project Catalog · Layer " + (proj.layer || 1),
      (proj.name || proj.slug) + " (" + proj.slug + ")",
      [
        renderKvSection("Hierarchy & Path Resolution", [
          ["slug", proj.slug],
          ["status", proj.status],
          ["parent_project", proj.parent_project || "(root)"],
          ["lineage", (proj.lineage || []).join(" -> ")],
          ["repo_path", proj.repo_path],
          ["subpath", proj.subpath],
          ["effective_path", proj.effective_target_path],
          ["target_path_abs", proj.target_path_abs],
          ["description", proj.description],
        ]),
        relSection,
        boundSection,
        cliSnippetBox(
          "Create Bound Team CLI",
          "python3 ultron/core/core.py create-team --slug " +
            shellQuote(proj.slug + "-dev") +
            " --blueprint coding-light --project " +
            shellQuote(proj.slug) +
            " --lifespan permanent --mission " +
            shellQuote("Own " + (proj.name || proj.slug))
        ),
      ]
    );
  }

  async function openDecisionDrawer(decisionId) {
    const seq = ++state.drawerRequestSeq;
    state.drawerMode = { kind: "decision", id: decisionId };
    openDrawer("Prime Decision", decisionId, [
      el("p", { className: "panel-card-body", text: "Loading decision stream..." }),
    ]);
    try {
      const d = await fetchJson("/api/decisions/" + encodeURIComponent(decisionId));
      if (seq !== state.drawerRequestSeq || !state.drawerMode || state.drawerMode.id !== decisionId) {
        return;
      }

      const reviewsSec = el("div", { className: "detail-section" }, [
        el("h3", { text: "Chronological Review History (" + (d.reviews || []).length + ")" }),
        (d.reviews || []).length === 0
          ? el("p", { className: "panel-card-body", text: "No reviews appended yet." })
          : el(
              "div",
              { className: "list-stack" },
              d.reviews.map((rev) =>
                el("div", { className: "post-card" }, [
                  el("div", { className: "post-meta" }, [
                    el("span", {
                      className: "post-author",
                      text:
                        "@" +
                        (rev.reviewer || "user") +
                        " -> " +
                        upperStatus(rev.review_status, "approved"),
                    }),
                    el("span", { className: "mono", text: shortTime(rev.created_at) }),
                  ]),
                  rev.replacement_decision
                    ? el("p", {
                        className: "post-content",
                        text: "Replacement: " + rev.replacement_decision,
                      })
                    : null,
                  rev.notes
                    ? el("p", { className: "post-content", text: "Notes: " + rev.notes })
                    : null,
                ])
              )
            ),
      ]);

      openDrawer(
        "Prime Decision · " + upperStatus(d.review_status, "pending_review"),
        d.title || d.id,
        [
          renderKvSection("Decision Stream", [
            ["decision_id", d.id],
            ["review_status", d.review_status],
            ["origin", d.origin],
            ["scope", formatScopeBadge(d)],
            ["decided_by", d.decided_by],
            ["current_ruling", d.decision],
            ["original_ruling", d.original_decision],
            ["rationale", d.rationale],
            ["tags", d.tags],
            ["created_at", shortTime(d.created_at)],
            ["updated_at", shortTime(d.updated_at)],
          ]),
          reviewsSec,
          cliSnippetBox(
            "Validate / Refine Decision CLI",
            "python3 ultron/core/core.py review-decision " +
              shellQuote(d.id) +
              ' --status approved --notes "Validated"'
          ),
        ]
      );
    } catch (err) {
      if (seq !== state.drawerRequestSeq || !state.drawerMode || state.drawerMode.id !== decisionId) {
        return;
      }
      openDrawer("Prime Decision Error", decisionId, [
        el("p", { className: "panel-card-body", text: String(err.message || err) }),
      ]);
    }
  }

  async function openThreadDrawer(threadId) {
    const seq = ++state.drawerRequestSeq;
    state.drawerMode = { kind: "thread", id: threadId };
    openDrawer("ULTRON Board Thread", threadId, [
      el("p", { className: "panel-card-body", text: "Loading folded thread events..." }),
    ]);
    try {
      const t = await fetchJson("/api/threads/" + encodeURIComponent(threadId));
      if (seq !== state.drawerRequestSeq || !state.drawerMode || state.drawerMode.id !== threadId) {
        return;
      }

      const postsList = el("div", { className: "list-stack" });
      (t.posts || []).forEach((post) => {
        const parts = String(post.author || "").split("/");
        const rSlug = parts.length > 1 ? parts[1] : parts[0];
        const botSvg = Sprites.renderBotSvg(
          Sprites.archetypeForRole({ agent_id: post.author, role: rSlug }),
          "active",
          24
        );
        postsList.appendChild(
          el("div", { className: "post-card" }, [
            el("div", { className: "post-meta" }, [
              el("span", { className: "post-author" }, [
                botSvg,
                "@" + (post.author || "unknown"),
                post.parent_post_id
                  ? el("span", { className: "badge", text: "reply to " + post.parent_post_id })
                  : null,
              ]),
              el("span", {
                className: "mono",
                text: post.id + " · " + shortTime(post.created_at),
              }),
            ]),
            post.tags
              ? el("div", { className: "team-badges", style: "margin-bottom:6px;" }, [
                  el("span", { className: "badge", text: "tags: " + post.tags }),
                ])
              : null,
            el("pre", { className: "post-content", text: post.content || "" }),
          ])
        );
      });

      openDrawer("Board Thread · " + formatThreadScope(t), t.title || t.id, [
        renderKvSection("Thread Metadata", [
          ["thread_id", t.id],
          ["status", t.status],
          ["category", t.category],
          ["scope", formatThreadScope(t)],
          ["author", t.author],
          ["posts", String((t.posts || []).length)],
          ["updated_at", shortTime(t.updated_at)],
        ]),
        el("div", { className: "detail-section" }, [
          el("h3", { text: "Folded Conversation (" + (t.posts || []).length + ")" }),
          postsList,
        ]),
        cliSnippetBox(
          "Inspect Thread CLI",
          "python3 ultron/core/core.py view " + shellQuote(t.id) + " --all"
        ),
      ]);
    } catch (err) {
      if (seq !== state.drawerRequestSeq || !state.drawerMode || state.drawerMode.id !== threadId) {
        return;
      }
      openDrawer("Board Thread Error", threadId, [
        el("p", { className: "panel-card-body", text: String(err.message || err) }),
      ]);
    }
  }

  function renderMain() {
    const view = document.getElementById("main-view");
    clearNode(view);
    if (!state.snapshot) return;
    if (state.activeTab === "hive") {
      renderHiveView(view);
    } else if (state.activeTab === "org") {
      renderOrgView(view);
    } else if (state.activeTab === "projects") {
      renderProjectsView(view);
    } else if (state.activeTab === "decisions") {
      renderDecisionsView(view);
    } else if (state.activeTab === "board") {
      renderBoardView(view);
    }
  }

  function refreshActiveTabInPlace() {
    if (!state.snapshot) return;
    if (state.activeTab === "org" && document.getElementById("org-chart-host")) {
      syncOrgProjectOptions();
      renderOrgChartCanvas();
      return;
    }
    if (state.activeTab === "decisions" && document.getElementById("decisions-list")) {
      renderDecisionsList();
      return;
    }
    if (state.activeTab === "board" && document.getElementById("board-list")) {
      syncBoardTeamOptions();
      renderBoardList();
      return;
    }
    renderMain();
  }

  function syncTabButtons(tab) {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      const isCurrent = btn.getAttribute("data-tab") === tab;
      btn.classList.toggle("active", isCurrent);
      btn.setAttribute("aria-selected", isCurrent ? "true" : "false");
    });
  }

  function switchTab(tab, updateHash) {
    if (!["hive", "org", "projects", "decisions", "board"].includes(tab)) tab = "hive";
    state.activeTab = tab;
    if (updateHash !== false && window.location.hash !== "#" + tab) {
      window.history.replaceState(null, "", "#" + tab);
    }
    syncTabButtons(tab);
    renderMain();
  }

  function init() {
    const initialHash = window.location.hash.replace(/^#/, "");
    if (["hive", "org", "projects", "decisions", "board"].includes(initialHash)) {
      state.activeTab = initialHash;
    }
    syncTabButtons(state.activeTab);

    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.getAttribute("data-tab"), true));
    });

    window.addEventListener("hashchange", () => {
      const next = window.location.hash.replace(/^#/, "");
      if (["hive", "org", "projects", "decisions", "board"].includes(next) && next !== state.activeTab) {
        switchTab(next, false);
      }
    });

    document.getElementById("pending-pill").addEventListener("click", () => {
      state.decisionFilters.status = "pending_review";
      switchTab("decisions", true);
    });

    document.getElementById("toggle-archived").addEventListener("change", (ev) => {
      state.showArchived = Boolean(ev.target.checked);
      renderHeader();
      refreshActiveTabInPlace();
    });

    document.getElementById("drawer-close").addEventListener("click", closeDrawer);
    document.getElementById("drawer-backdrop").addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") closeDrawer();
    });

    const sync = new LiveSync(
      2500,
      (snapshot) => {
        state.snapshot = snapshot;
        renderHeader();
        refreshActiveTabInPlace();
        refreshOpenDrawer();
      },
      (statusInfo) => {
        const line = document.getElementById("sync-status-line");
        if (statusInfo.mode === "error") {
          line.textContent = "Sync error: " + statusInfo.extra;
        } else {
          const ts = statusInfo.lastSyncAt
            ? statusInfo.lastSyncAt.toLocaleTimeString()
            : "...";
          line.textContent =
            "Sync: " +
            statusInfo.mode.toUpperCase() +
            " · ETag " +
            (statusInfo.etag || "none") +
            " · " +
            ts;
        }
      }
    );

    document.getElementById("btn-pause").addEventListener("click", (ev) => {
      const nextPaused = !sync.paused;
      sync.setPaused(nextPaused);
      ev.target.textContent = nextPaused ? "Resume Sync" : "Pause Sync";
    });

    document.getElementById("btn-refresh").addEventListener("click", () => sync.tick(true));

    document.getElementById("btn-verify").addEventListener("click", async () => {
      try {
        const res = await fetchJson("/api/verify");
        if (res.ok) {
          showDiagBanner(
            true,
            "Verify Passed",
            res.teams +
              " team(s), " +
              res.agents +
              " role(s), " +
              res.projects +
              " project(s), " +
              res.decisions +
              " decision(s), " +
              res.threads +
              " thread(s), merge=union=" +
              res.gitattributes_union_merge
          );
        } else {
          showDiagBanner(false, "Verify Failed", res.error || "Unknown verification error");
        }
      } catch (err) {
        showDiagBanner(false, "Verify Error", String(err.message || err));
      }
    });

    document.getElementById("btn-liveness").addEventListener("click", async () => {
      try {
        const res = await fetchJson("/api/liveness");
        if (res.ok) {
          const agentKeys = Object.keys(res.agents || {});
          const summary =
            agentKeys.length === 0
              ? "No active sessions running (0 active agents across Hive)."
              : agentKeys.map((k) => k + "=" + res.agents[k].state).join(", ");
          const note =
            res.next_steps && res.next_steps.length > 0
              ? "\n" + res.next_steps.join("\n")
              : "";
          showDiagBanner(true, "Liveness (" + (res.harness || "hive") + ")", summary + note);
        } else {
          showDiagBanner(false, "Liveness Unavailable", res.error || "Failed to probe liveness");
        }
      } catch (err) {
        showDiagBanner(false, "Liveness Error", String(err.message || err));
      }
    });

    sync.start();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
