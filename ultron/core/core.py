#!/usr/bin/env python3
"""
ULTRON Core (ultron/core/core.py)
Central org registry, N-layer Hive team/role scaffolder, lifecycle coordinator,
and visibility-scoped message board for ULTRON (Universal Layered Team & Role Orchestration Network).

Zero third-party dependencies (Python 3 standard library only).
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import glob
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Set, Tuple

CORE_DIR = Path(__file__).resolve().parent
ULTRON_DIR = CORE_DIR.parent
DEFAULT_REPO_ROOT = ULTRON_DIR.parent
TEMPLATES_DIR = CORE_DIR / "templates"

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")

VALID_MODELS = {"inherit", "flash_lite", "flash", "pro"}
VALID_WORKSPACES = {"inherit", "share", "branch"}
VALID_TEAM_STATUSES = {"active", "disabled"}
VALID_AGENT_STATUSES = {"active", "disabled"}
VALID_VISIBILITIES = {"personal", "team", "global"}
VALID_THREAD_STATUSES = {"open", "in_progress", "resolved", "blocked", "closed"}

PRIME_ID = "ultron-prime"
RESERVED_SLUGS = {PRIME_ID, "prime", "teams", "roles", "workspace", "core", "hive"}

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS sync_state (
    file_key TEXT PRIMARY KEY,
    mtime_ns INTEGER NOT NULL,
    size INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    slug TEXT PRIMARY KEY COLLATE NOCASE,
    name TEXT NOT NULL,
    parent_team TEXT COLLATE NOCASE REFERENCES teams(slug) ON DELETE RESTRICT,
    mission TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'disabled',
    hive_path TEXT NOT NULL,
    default_model TEXT NOT NULL DEFAULT 'flash',
    workspace_mode TEXT NOT NULL DEFAULT 'inherit',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY COLLATE NOCASE,
    team_slug TEXT COLLATE NOCASE REFERENCES teams(slug) ON DELETE CASCADE,
    role TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    responsibilities TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT 'flash',
    write_tools INTEGER NOT NULL DEFAULT 1,
    mcp_tools INTEGER NOT NULL DEFAULT 1,
    conversation_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'disabled',
    role_path TEXT NOT NULL DEFAULT '',
    last_seen TEXT NOT NULL,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    status TEXT NOT NULL DEFAULT 'open',
    visibility TEXT NOT NULL DEFAULT 'team',
    team_slug TEXT COLLATE NOCASE,
    with_team TEXT COLLATE NOCASE,
    owner_agent TEXT COLLATE NOCASE,
    author TEXT NOT NULL COLLATE NOCASE,
    author_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    parent_post_id INTEGER REFERENCES posts(id),
    author TEXT NOT NULL COLLATE NOCASE,
    author_id TEXT,
    content TEXT NOT NULL,
    tags TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_teams_parent ON teams(parent_team);
CREATE INDEX IF NOT EXISTS idx_teams_status ON teams(status);
CREATE INDEX IF NOT EXISTS idx_agents_team ON agents(team_slug);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_threads_visibility ON threads(visibility);
CREATE INDEX IF NOT EXISTS idx_threads_team ON threads(team_slug);
CREATE INDEX IF NOT EXISTS idx_threads_with_team ON threads(with_team);
CREATE INDEX IF NOT EXISTS idx_threads_owner ON threads(owner_agent);
CREATE INDEX IF NOT EXISTS idx_threads_category ON threads(category);
CREATE INDEX IF NOT EXISTS idx_threads_status ON threads(status);
CREATE INDEX IF NOT EXISTS idx_posts_thread ON posts(thread_id);

CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
    content,
    tags,
    content='posts',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS posts_ai AFTER INSERT ON posts BEGIN
    INSERT INTO posts_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS posts_ad AFTER DELETE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, content, tags) VALUES('delete', old.id, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS posts_au AFTER UPDATE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, content, tags) VALUES('delete', old.id, old.content, old.tags);
    INSERT INTO posts_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
END;
"""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def render_template(template_text: str, values: Mapping[str, Any]) -> str:
    """Single-pass {{KEY}} substitution safe against literal braces in user content."""
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"Missing template placeholder '{{{{{key}}}}}'")
        return str(values[key])

    return PLACEHOLDER_RE.sub(_replace, template_text)


def validate_slug(value: str, label: str = "slug") -> str:
    cleaned = value.strip()
    if not SLUG_RE.match(cleaned):
        raise ValueError(
            f"Invalid {label} '{value}'. Must match {SLUG_RE.pattern} (lowercase letters, digits, hyphens)."
        )
    if cleaned in RESERVED_SLUGS:
        raise ValueError(f"Invalid {label} '{value}': '{cleaned}' is reserved.")
    return cleaned


def validate_role_slug(value: str) -> str:
    cleaned = value.strip()
    if not SLUG_RE.match(cleaned):
        raise ValueError(
            f"Invalid role '{value}'. Must match {SLUG_RE.pattern} (lowercase letters, digits, hyphens)."
        )
    if cleaned in {PRIME_ID, "prime", "teams", "roles", "workspace"}:
        raise ValueError(f"Invalid role '{value}': '{cleaned}' is reserved.")
    return cleaned


def normalize_agent_id(value: str) -> str:
    cleaned = value.strip().lower()
    if cleaned == PRIME_ID:
        return PRIME_ID
    if "/" not in cleaned:
        raise ValueError(
            f"Invalid agent_id '{value}'. Must be '{PRIME_ID}' or '<team-slug>/<role-slug>'."
        )
    parts = cleaned.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(
            f"Invalid agent_id '{value}'. Must be '{PRIME_ID}' or '<team-slug>/<role-slug>'."
        )
    validate_slug(parts[0], "team slug")
    validate_role_slug(parts[1])
    return f"{parts[0]}/{parts[1]}"


def atomic_write_json(target_path: Path, data: Any) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f"{target_path.name}.tmp.{os.getpid()}")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    os.replace(tmp_path, target_path)


class UltronCore:
    def __init__(
        self,
        repo_root: Optional[Path | str] = None,
        db_path: Optional[Path | str] = None,
        hive_dir: Optional[Path | str] = None,
        teams_file: Optional[Path | str] = None,
        agents_file: Optional[Path | str] = None,
        threads_dir: Optional[Path | str] = None,
        templates_dir: Optional[Path | str] = None,
    ) -> None:
        env_root = os.environ.get("ULTRON_REPO_ROOT")
        self.repo_root = Path(repo_root or env_root or DEFAULT_REPO_ROOT).resolve()
        default_core = self.repo_root / "ultron" / "core"
        default_hive = self.repo_root / "ultron" / "hive"

        self.db_path = Path(
            db_path or os.environ.get("ULTRON_DB_PATH") or (default_core / "core.db")
        ).resolve()
        self.hive_dir = Path(
            hive_dir or os.environ.get("ULTRON_HIVE_DIR") or default_hive
        ).resolve()
        self.teams_file = Path(
            teams_file or os.environ.get("ULTRON_TEAMS_FILE") or (default_core / "teams.json")
        ).resolve()
        self.agents_file = Path(
            agents_file or os.environ.get("ULTRON_AGENTS_FILE") or (default_core / "agents.json")
        ).resolve()
        self.threads_dir = Path(
            threads_dir or os.environ.get("ULTRON_THREADS_DIR") or (default_core / "threads")
        ).resolve()
        self.templates_dir = Path(templates_dir or TEMPLATES_DIR).resolve()

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.hive_dir.mkdir(parents=True, exist_ok=True)
        self.threads_dir.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _rel_posix(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.repo_root).as_posix()
        except ValueError as exc:
            raise ValueError(
                f"Path '{resolved}' lies outside ULTRON repo root '{self.repo_root}'."
            ) from exc

    def _abs_from_rel(self, rel_posix: str) -> Path:
        candidate = (self.repo_root / Path(rel_posix)).resolve()
        try:
            candidate.relative_to(self.repo_root)
        except ValueError as exc:
            raise ValueError(
                f"Stored relative path '{rel_posix}' escapes repo root '{self.repo_root}'."
            ) from exc
        return candidate

    def _load_template(self, filename: str) -> str:
        tpath = self.templates_dir / filename
        if not tpath.is_file():
            raise FileNotFoundError(f"Missing ULTRON template file: {tpath}")
        return tpath.read_text(encoding="utf-8")

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Disk <-> SQLite Sync & Reconciliatory Restore
    # ------------------------------------------------------------------

    def _disk_snapshot(self) -> Dict[str, Tuple[int, int]]:
        snap: Dict[str, Tuple[int, int]] = {}
        if self.teams_file.is_file():
            st = self.teams_file.stat()
            snap["teams.json"] = (st.st_mtime_ns, st.st_size)
        if self.agents_file.is_file():
            st = self.agents_file.stat()
            snap["agents.json"] = (st.st_mtime_ns, st.st_size)
        if self.threads_dir.is_dir():
            for fpath in sorted(self.threads_dir.glob("thread_*.json")):
                if fpath.is_file():
                    st = fpath.stat()
                    snap[f"thread:{fpath.name}"] = (st.st_mtime_ns, st.st_size)
        return snap

    def _record_file_sync(self, conn: sqlite3.Connection, key: str, path: Path) -> None:
        if path.is_file():
            st = path.stat()
            conn.execute(
                """
                INSERT INTO sync_state (file_key, mtime_ns, size)
                VALUES (?, ?, ?)
                ON CONFLICT(file_key) DO UPDATE SET
                    mtime_ns = excluded.mtime_ns,
                    size = excluded.size
                """,
                (key, st.st_mtime_ns, st.st_size),
            )
        else:
            conn.execute("DELETE FROM sync_state WHERE file_key = ?", (key,))

    def _replace_all_sync_state(
        self, conn: sqlite3.Connection, snap: Mapping[str, Tuple[int, int]]
    ) -> None:
        conn.execute("DELETE FROM sync_state")
        for key, (mtime_ns, size) in snap.items():
            conn.execute(
                "INSERT INTO sync_state (file_key, mtime_ns, size) VALUES (?, ?, ?)",
                (key, mtime_ns, size),
            )

    def _checkpoint_wal(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
        except sqlite3.OperationalError:
            pass

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(SCHEMA)
            disk_snap = self._disk_snapshot()
            db_rows = conn.execute("SELECT file_key, mtime_ns, size FROM sync_state").fetchall()
            db_snap = {r["file_key"]: (r["mtime_ns"], r["size"]) for r in db_rows}

            if disk_snap != db_snap:
                self._reconcile_from_disk(conn, disk_snap)
                self._checkpoint_wal(conn)

    @staticmethod
    def _topological_sort_teams(teams_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_slug: Dict[str, Dict[str, Any]] = {}
        for item in teams_list:
            slug = item["slug"].strip().lower()
            if slug in by_slug:
                raise ValueError(f"Duplicate team slug '{slug}' in teams.json.")
            by_slug[slug] = item

        visited: Dict[str, int] = {}  # 0=visiting, 1=done
        ordered: List[Dict[str, Any]] = []

        def visit(slug: str) -> None:
            state = visited.get(slug)
            if state == 1:
                return
            if state == 0:
                raise ValueError(f"Cycle detected in team parent hierarchy involving '{slug}'.")
            visited[slug] = 0
            item = by_slug[slug]
            parent = (item.get("parent_team") or "").strip().lower() or None
            if parent:
                if parent not in by_slug:
                    raise ValueError(
                        f"Team '{slug}' references missing parent_team '{parent}'."
                    )
                visit(parent)
            visited[slug] = 1
            ordered.append(item)

        for s in sorted(by_slug.keys()):
            visit(s)
        return ordered

    def _reconcile_from_disk(
        self,
        conn: sqlite3.Connection,
        disk_snap: Optional[Mapping[str, Tuple[int, int]]] = None,
    ) -> Dict[str, int]:
        snap = dict(disk_snap) if disk_snap is not None else self._disk_snapshot()
        teams_data: List[Dict[str, Any]] = []
        agents_data: List[Dict[str, Any]] = []
        thread_files = sorted(self.threads_dir.glob("thread_*.json")) if self.threads_dir.is_dir() else []

        if self.teams_file.is_file():
            with open(self.teams_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if not isinstance(raw, list):
                    raise ValueError(f"Expected JSON list in {self.teams_file}")
                teams_data = self._topological_sort_teams(raw)

        if self.agents_file.is_file():
            with open(self.agents_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if not isinstance(raw, list):
                    raise ValueError(f"Expected JSON list in {self.agents_file}")
                agents_data = raw

        conn.execute("PRAGMA defer_foreign_keys = ON;")
        cursor = conn.cursor()

        # 1. Reconcile teams (delete removed leaves/subtrees safely under deferred FKs)
        if self.teams_file.is_file():
            active_team_slugs = [t["slug"].strip().lower() for t in teams_data]
            if active_team_slugs:
                placeholders = ",".join("?" for _ in active_team_slugs)
                cursor.execute(
                    f"DELETE FROM teams WHERE lower(slug) NOT IN ({placeholders})",
                    active_team_slugs,
                )
            else:
                cursor.execute("DELETE FROM teams")

            for t in teams_data:
                slug = validate_slug(t["slug"], "team slug")
                parent = (t.get("parent_team") or "").strip().lower() or None
                if parent:
                    validate_slug(parent, "parent_team")
                status = t.get("status", "disabled").strip().lower()
                if status not in VALID_TEAM_STATUSES:
                    raise ValueError(f"Invalid team status '{status}' for team '{slug}'.")
                hive_path = Path(t["hive_path"]).as_posix()
                if hive_path.startswith("/") or ".." in Path(hive_path).parts:
                    raise ValueError(f"Non-portable hive_path '{hive_path}' in teams.json.")
                model = t.get("default_model", "flash").strip().lower()
                ws = t.get("workspace_mode", "inherit").strip().lower()
                created_at = t.get("created_at") or now_iso()
                updated_at = t.get("updated_at") or created_at
                cursor.execute(
                    """
                    INSERT INTO teams (
                        slug, name, parent_team, mission, status,
                        hive_path, default_model, workspace_mode, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(slug) DO UPDATE SET
                        name = excluded.name,
                        parent_team = excluded.parent_team,
                        mission = excluded.mission,
                        status = excluded.status,
                        hive_path = excluded.hive_path,
                        default_model = excluded.default_model,
                        workspace_mode = excluded.workspace_mode,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        slug,
                        t["name"].strip(),
                        parent,
                        t.get("mission", "").strip(),
                        status,
                        hive_path,
                        model,
                        ws,
                        created_at,
                        updated_at,
                    ),
                )

        # 2. Reconcile agents
        if self.agents_file.is_file():
            active_agent_ids = [normalize_agent_id(a["agent_id"]) for a in agents_data]
            if active_agent_ids:
                placeholders = ",".join("?" for _ in active_agent_ids)
                cursor.execute(
                    f"DELETE FROM agents WHERE lower(agent_id) NOT IN ({placeholders})",
                    active_agent_ids,
                )
            else:
                cursor.execute("DELETE FROM agents")

            for a in agents_data:
                aid = normalize_agent_id(a["agent_id"])
                team_slug = (a.get("team_slug") or "").strip().lower() or None
                role = a.get("role", "").strip().lower()
                if aid == PRIME_ID:
                    team_slug = None
                    role = "prime"
                else:
                    inferred_team, inferred_role = aid.split("/", 1)
                    team_slug = inferred_team
                    role = inferred_role
                status = a.get("status", "disabled").strip().lower()
                if status not in VALID_AGENT_STATUSES:
                    raise ValueError(f"Invalid agent status '{status}' for '{aid}'.")
                role_path = Path(a.get("role_path", "")).as_posix() if a.get("role_path") else ""
                if role_path and (role_path.startswith("/") or ".." in Path(role_path).parts):
                    raise ValueError(f"Non-portable role_path '{role_path}' in agents.json.")
                reg_at = a.get("registered_at") or now_iso()
                seen_at = a.get("last_seen") or reg_at
                cursor.execute(
                    """
                    INSERT INTO agents (
                        agent_id, team_slug, role, title, responsibilities,
                        model, write_tools, mcp_tools, conversation_id,
                        status, role_path, last_seen, registered_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        team_slug = excluded.team_slug,
                        role = excluded.role,
                        title = excluded.title,
                        responsibilities = excluded.responsibilities,
                        model = excluded.model,
                        write_tools = excluded.write_tools,
                        mcp_tools = excluded.mcp_tools,
                        conversation_id = excluded.conversation_id,
                        status = excluded.status,
                        role_path = excluded.role_path,
                        last_seen = excluded.last_seen,
                        registered_at = excluded.registered_at
                    """,
                    (
                        aid,
                        team_slug,
                        role,
                        a.get("title", "").strip(),
                        a.get("responsibilities", "").strip(),
                        a.get("model", "flash").strip().lower(),
                        1 if a.get("write_tools", True) else 0,
                        1 if a.get("mcp_tools", True) else 0,
                        a.get("conversation_id", "").strip(),
                        status,
                        role_path,
                        seen_at,
                        reg_at,
                    ),
                )

        # 3. Reconcile threads & posts
        loaded_thread_ids: List[int] = []
        for fpath in thread_files:
            with open(fpath, "r", encoding="utf-8") as f:
                t_data = json.load(f)
            t_id = int(t_data["id"])
            loaded_thread_ids.append(t_id)
            vis = t_data.get("visibility", "team").strip().lower()
            if vis not in VALID_VISIBILITIES:
                raise ValueError(f"Invalid visibility '{vis}' in {fpath.name}")
            created_at = t_data.get("created_at") or now_iso()
            updated_at = t_data.get("updated_at") or created_at
            cursor.execute(
                """
                INSERT INTO threads (
                    id, title, category, status, visibility, team_slug,
                    with_team, owner_agent, author, author_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    category = excluded.category,
                    status = excluded.status,
                    visibility = excluded.visibility,
                    team_slug = excluded.team_slug,
                    with_team = excluded.with_team,
                    owner_agent = excluded.owner_agent,
                    author = excluded.author,
                    author_id = excluded.author_id,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    t_id,
                    t_data["title"],
                    t_data.get("category", "general"),
                    t_data.get("status", "open"),
                    vis,
                    t_data.get("team_slug"),
                    t_data.get("with_team"),
                    t_data.get("owner_agent"),
                    t_data.get("author", PRIME_ID).strip().lower(),
                    t_data.get("author_id", ""),
                    created_at,
                    updated_at,
                ),
            )

            posts = t_data.get("posts", [])
            post_ids = [int(p["id"]) for p in posts]
            if post_ids:
                p_placeholders = ",".join("?" for _ in post_ids)
                cursor.execute(
                    f"DELETE FROM posts WHERE thread_id = ? AND id NOT IN ({p_placeholders})",
                    [t_id, *post_ids],
                )
            else:
                cursor.execute("DELETE FROM posts WHERE thread_id = ?", (t_id,))

            for p in posts:
                cursor.execute(
                    """
                    INSERT INTO posts (
                        id, thread_id, parent_post_id, author, author_id,
                        content, tags, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        thread_id = excluded.thread_id,
                        parent_post_id = excluded.parent_post_id,
                        author = excluded.author,
                        author_id = excluded.author_id,
                        content = excluded.content,
                        tags = excluded.tags,
                        created_at = excluded.created_at
                    """,
                    (
                        int(p["id"]),
                        t_id,
                        p.get("parent_post_id"),
                        p.get("author", PRIME_ID).strip().lower(),
                        p.get("author_id", ""),
                        p.get("content", ""),
                        p.get("tags", ""),
                        p.get("created_at") or created_at,
                    ),
                )

        if loaded_thread_ids:
            t_placeholders = ",".join("?" for _ in loaded_thread_ids)
            cursor.execute(
                f"DELETE FROM threads WHERE id NOT IN ({t_placeholders})",
                loaded_thread_ids,
            )
        else:
            cursor.execute("DELETE FROM threads")

        cursor.execute("INSERT INTO posts_fts(posts_fts) VALUES('rebuild');")

        fk_violations = cursor.execute("PRAGMA foreign_key_check;").fetchall()
        if fk_violations:
            raise RuntimeError(
                f"Foreign key integrity check failed during JSON restore: {[tuple(r) for r in fk_violations]}"
            )

        self._replace_all_sync_state(conn, snap)
        return {
            "teams": len(teams_data),
            "agents": len(agents_data),
            "threads": len(loaded_thread_ids),
        }

    # ------------------------------------------------------------------
    # Deterministic JSON Exports
    # ------------------------------------------------------------------

    def _serialize_team_row(self, row: sqlite3.Row, layer: int) -> Dict[str, Any]:
        return {
            "created_at": row["created_at"],
            "default_model": row["default_model"],
            "hive_path": row["hive_path"],
            "layer": layer,
            "mission": row["mission"],
            "name": row["name"],
            "parent_team": row["parent_team"],
            "slug": row["slug"],
            "status": row["status"],
            "updated_at": row["updated_at"],
            "workspace_mode": row["workspace_mode"],
        }

    @staticmethod
    def _serialize_agent_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "agent_id": row["agent_id"],
            "conversation_id": row["conversation_id"],
            "last_seen": row["last_seen"],
            "mcp_tools": bool(row["mcp_tools"]),
            "model": row["model"],
            "registered_at": row["registered_at"],
            "responsibilities": row["responsibilities"],
            "role": row["role"],
            "role_path": row["role_path"],
            "status": row["status"],
            "team_slug": row["team_slug"],
            "title": row["title"],
            "write_tools": bool(row["write_tools"]),
        }

    def export_teams(self) -> str:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM teams").fetchall()
            by_slug = {r["slug"].lower(): r for r in rows}
            layers: Dict[str, int] = {}

            def get_layer(slug: str, seen: Set[str]) -> int:
                if slug in layers:
                    return layers[slug]
                if slug in seen:
                    raise RuntimeError(f"Cycle detected in teams table for '{slug}'.")
                seen.add(slug)
                parent = by_slug[slug]["parent_team"]
                lvl = 1 if not parent else (get_layer(parent.lower(), seen) + 1)
                layers[slug] = lvl
                return lvl

            for s in by_slug:
                get_layer(s, set())

            ordered_slugs = sorted(by_slug.keys(), key=lambda s: (layers[s], s))
            payload = [self._serialize_team_row(by_slug[s], layers[s]) for s in ordered_slugs]
            atomic_write_json(self.teams_file, payload)
            self._record_file_sync(conn, "teams.json", self.teams_file)
            self._checkpoint_wal(conn)
        return str(self.teams_file)

    def export_agents(self) -> str:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM agents").fetchall()
            ordered = sorted(
                rows,
                key=lambda r: (0 if r["agent_id"].lower() == PRIME_ID else 1, r["agent_id"].lower()),
            )
            payload = [self._serialize_agent_row(r) for r in ordered]
            atomic_write_json(self.agents_file, payload)
            self._record_file_sync(conn, "agents.json", self.agents_file)
            self._checkpoint_wal(conn)
        return str(self.agents_file)

    def export_thread(self, thread_id: int) -> str:
        with self._get_connection() as conn:
            t_row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if not t_row:
                raise ValueError(f"Thread #{thread_id} not found.")
            p_rows = conn.execute(
                "SELECT * FROM posts WHERE thread_id = ? ORDER BY id ASC",
                (thread_id,),
            ).fetchall()
            thread_dict = dict(t_row)
            thread_dict["posts"] = [dict(r) for r in p_rows]
            fname = f"thread_{thread_id:04d}.json"
            fpath = self.threads_dir / fname
            atomic_write_json(fpath, thread_dict)
            self._record_file_sync(conn, f"thread:{fname}", fpath)
            self._checkpoint_wal(conn)
        return str(fpath)

    def export_all(self) -> Dict[str, int]:
        self.export_teams()
        self.export_agents()
        with self._get_connection() as conn:
            t_ids = [r["id"] for r in conn.execute("SELECT id FROM threads ORDER BY id ASC").fetchall()]
            expected_names = {f"thread_{tid:04d}.json" for tid in t_ids}
            for existing in self.threads_dir.glob("thread_*.json"):
                if existing.name not in expected_names:
                    existing.unlink()
                    conn.execute("DELETE FROM sync_state WHERE file_key = ?", (f"thread:{existing.name}",))
            a_count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            t_count = conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
        for tid in t_ids:
            self.export_thread(tid)
        return {"teams": t_count, "agents": a_count, "threads": len(t_ids)}

    def restore(self) -> Dict[str, int]:
        with self._get_connection() as conn:
            res = self._reconcile_from_disk(conn)
            self._checkpoint_wal(conn)
            return res

    # ------------------------------------------------------------------
    # Org Graph & Team / Role Scaffolding
    # ------------------------------------------------------------------

    def _get_team_lineage_conn(self, conn: sqlite3.Connection, slug: str) -> List[sqlite3.Row]:
        chain: List[sqlite3.Row] = []
        seen: Set[str] = set()
        curr: Optional[str] = slug.strip().lower()
        while curr:
            if curr in seen:
                raise RuntimeError(f"Cycle detected in team lineage at '{curr}'.")
            seen.add(curr)
            row = conn.execute("SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (curr,)).fetchone()
            if not row:
                raise ValueError(f"Team '{curr}' does not exist.")
            chain.append(row)
            curr = row["parent_team"].lower() if row["parent_team"] else None
        chain.reverse()
        return chain

    def _get_descendants_conn(self, conn: sqlite3.Connection, slug: str) -> List[sqlite3.Row]:
        descendants: List[sqlite3.Row] = []
        queue = [slug.strip().lower()]
        seen: Set[str] = {slug.strip().lower()}
        while queue:
            parent = queue.pop(0)
            children = conn.execute(
                "SELECT * FROM teams WHERE parent_team = ? COLLATE NOCASE ORDER BY slug ASC",
                (parent,),
            ).fetchall()
            for child in children:
                c_slug = child["slug"].lower()
                if c_slug not in seen:
                    seen.add(c_slug)
                    descendants.append(child)
                    queue.append(c_slug)
        return descendants

    def _write_team_manifest_on_disk(self, team_row: Mapping[str, Any], layer: int) -> None:
        team_dir = self._abs_from_rel(team_row["hive_path"])
        if team_dir.is_dir():
            manifest = {
                "created_at": team_row["created_at"],
                "default_model": team_row["default_model"],
                "hive_path": team_row["hive_path"],
                "layer": layer,
                "mission": team_row["mission"],
                "name": team_row["name"],
                "parent_team": team_row["parent_team"],
                "slug": team_row["slug"],
                "status": team_row["status"],
                "updated_at": team_row["updated_at"],
                "workspace_mode": team_row["workspace_mode"],
            }
            atomic_write_json(team_dir / "team.json", manifest)

    def register_prime(self, conversation_id: str) -> Dict[str, Any]:
        cid = conversation_id.strip()
        if not cid:
            raise ValueError("conversation_id cannot be empty for register-prime.")
        iso = now_iso()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, team_slug, role, title, responsibilities,
                    model, write_tools, mcp_tools, conversation_id,
                    status, role_path, last_seen, registered_at
                )
                VALUES (?, NULL, 'prime', 'ULTRON PRIME',
                        'Ultimate Leader of Teams, Roles, and Operational Nodes',
                        'inherit', 1, 1, ?, 'active', 'ultron/core', ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    conversation_id = excluded.conversation_id,
                    status = 'active',
                    last_seen = excluded.last_seen
                """,
                (PRIME_ID, cid, iso, iso),
            )
        self.export_agents()
        return self.get_agent(PRIME_ID) or {}

    def create_team(
        self,
        slug: str,
        name: str,
        mission: str,
        parent_team: Optional[str] = None,
        default_model: str = "flash",
        workspace_mode: str = "inherit",
        lead_responsibilities: str = "",
    ) -> Dict[str, Any]:
        clean_slug = validate_slug(slug, "team slug")
        clean_name = name.strip()
        clean_mission = mission.strip()
        if not clean_name:
            raise ValueError("Team name cannot be empty.")
        if not clean_mission:
            raise ValueError("Team mission cannot be empty.")

        model = default_model.strip().lower()
        if model not in VALID_MODELS:
            raise ValueError(f"Invalid model '{default_model}'. Must be one of {sorted(VALID_MODELS)}.")
        ws = workspace_mode.strip().lower()
        if ws not in VALID_WORKSPACES:
            raise ValueError(
                f"Invalid workspace_mode '{workspace_mode}'. Must be one of {sorted(VALID_WORKSPACES)}."
            )

        clean_parent = validate_slug(parent_team, "parent_team") if parent_team else None
        iso = now_iso()

        with self._get_connection() as conn:
            existing = conn.execute(
                "SELECT slug FROM teams WHERE slug = ? COLLATE NOCASE", (clean_slug,)
            ).fetchone()
            if existing:
                raise ValueError(f"Team '{clean_slug}' already exists.")

            if clean_parent:
                parent_row = conn.execute(
                    "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (clean_parent,)
                ).fetchone()
                if not parent_row:
                    raise ValueError(f"Parent team '{clean_parent}' does not exist.")
                parent_abs = self._abs_from_rel(parent_row["hive_path"])
                team_dir = parent_abs / "teams" / clean_slug
                lineage_rows = self._get_team_lineage_conn(conn, clean_parent)
                layer = len(lineage_rows) + 1
            else:
                team_dir = self.hive_dir / clean_slug
                layer = 1

            hive_rel = self._rel_posix(team_dir)
            lead_dir = team_dir / "roles" / "lead"
            lead_rel = self._rel_posix(lead_dir)
            lead_ws_rel = self._rel_posix(lead_dir / "workspace")

            lead_id = f"{clean_slug}/lead"
            lead_title = f"{clean_name} Team Leader"
            lead_resp = (
                lead_responsibilities.strip()
                or f"Coordinate internal execution for '{clean_name}' ({clean_slug}) and serve as sole external communication bridge along the ULTRON hierarchy."
            )

            # Scaffold Hive folders & templates on disk
            (team_dir / "teams").mkdir(parents=True, exist_ok=True)
            (lead_dir / "workspace").mkdir(parents=True, exist_ok=True)
            (team_dir / "teams" / ".gitkeep").touch(exist_ok=True)
            (lead_dir / "workspace" / ".gitkeep").touch(exist_ok=True)

            team_agents_md = render_template(
                self._load_template("team_agents.md.tmpl"),
                {
                    "TEAM_NAME": clean_name,
                    "TEAM_SLUG": clean_slug,
                    "TEAM_MISSION": clean_mission,
                    "PARENT_TEAM_DISPLAY": clean_parent or f"{PRIME_ID} (Layer 1 root)",
                    "HIVE_PATH": hive_rel,
                },
            )
            lead_role_md = render_template(
                self._load_template("lead_role.md.tmpl"),
                {
                    "ROLE_TITLE": lead_title,
                    "AGENT_ID": lead_id,
                    "TEAM_NAME": clean_name,
                    "TEAM_SLUG": clean_slug,
                    "ROLE_WORKSPACE_PATH": lead_ws_rel,
                    "RESPONSIBILITIES": lead_resp,
                },
            )

            team_agents_path = team_dir / "AGENTS.md"
            if not team_agents_path.exists():
                team_agents_path.write_text(team_agents_md, encoding="utf-8")

            lead_agents_path = lead_dir / "AGENTS.md"
            if not lead_agents_path.exists():
                lead_agents_path.write_text(lead_role_md, encoding="utf-8")

            conn.execute(
                """
                INSERT INTO teams (
                    slug, name, parent_team, mission, status,
                    hive_path, default_model, workspace_mode, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'disabled', ?, ?, ?, ?, ?)
                """,
                (clean_slug, clean_name, clean_parent, clean_mission, hive_rel, model, ws, iso, iso),
            )
            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, team_slug, role, title, responsibilities,
                    model, write_tools, mcp_tools, conversation_id,
                    status, role_path, last_seen, registered_at
                )
                VALUES (?, ?, 'lead', ?, ?, ?, 1, 1, '', 'disabled', ?, ?, ?)
                """,
                (lead_id, clean_slug, lead_title, lead_resp, model, lead_rel, iso, iso),
            )

            t_row = conn.execute(
                "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (clean_slug,)
            ).fetchone()
            self._write_team_manifest_on_disk(t_row, layer)

        self.export_teams()
        self.export_agents()
        return self.get_team(clean_slug) or {}

    def add_role(
        self,
        team_slug: str,
        role: str,
        title: str,
        responsibilities: str,
        model: Optional[str] = None,
        write_tools: bool = True,
        mcp_tools: bool = True,
    ) -> Dict[str, Any]:
        clean_team = validate_slug(team_slug, "team slug")
        clean_role = validate_role_slug(role)
        if clean_role == "lead":
            raise ValueError("Role 'lead' is automatically created with every team.")
        clean_title = title.strip()
        clean_resp = responsibilities.strip()
        if not clean_title:
            raise ValueError("Role title cannot be empty.")
        if not clean_resp:
            raise ValueError("Role responsibilities cannot be empty.")

        aid = f"{clean_team}/{clean_role}"
        iso = now_iso()

        with self._get_connection() as conn:
            t_row = conn.execute(
                "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (clean_team,)
            ).fetchone()
            if not t_row:
                raise ValueError(f"Team '{clean_team}' does not exist.")

            existing = conn.execute(
                "SELECT agent_id FROM agents WHERE agent_id = ? COLLATE NOCASE", (aid,)
            ).fetchone()
            if existing:
                raise ValueError(f"Role '{aid}' already exists.")

            chosen_model = (model or t_row["default_model"]).strip().lower()
            if chosen_model not in VALID_MODELS:
                raise ValueError(
                    f"Invalid model '{chosen_model}'. Must be one of {sorted(VALID_MODELS)}."
                )

            team_dir = self._abs_from_rel(t_row["hive_path"])
            role_dir = team_dir / "roles" / clean_role
            role_rel = self._rel_posix(role_dir)
            ws_rel = self._rel_posix(role_dir / "workspace")

            (role_dir / "workspace").mkdir(parents=True, exist_ok=True)
            (role_dir / "workspace" / ".gitkeep").touch(exist_ok=True)

            member_md = render_template(
                self._load_template("member_role.md.tmpl"),
                {
                    "ROLE_TITLE": clean_title,
                    "AGENT_ID": aid,
                    "TEAM_NAME": t_row["name"],
                    "TEAM_SLUG": clean_team,
                    "ROLE_SLUG": clean_role,
                    "ROLE_WORKSPACE_PATH": ws_rel,
                    "RESPONSIBILITIES": clean_resp,
                },
            )
            role_agents_path = role_dir / "AGENTS.md"
            if not role_agents_path.exists():
                role_agents_path.write_text(member_md, encoding="utf-8")

            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, team_slug, role, title, responsibilities,
                    model, write_tools, mcp_tools, conversation_id,
                    status, role_path, last_seen, registered_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', 'disabled', ?, ?, ?)
                """,
                (
                    aid,
                    clean_team,
                    clean_role,
                    clean_title,
                    clean_resp,
                    chosen_model,
                    1 if write_tools else 0,
                    1 if mcp_tools else 0,
                    role_rel,
                    iso,
                    iso,
                ),
            )
            conn.execute(
                "UPDATE teams SET updated_at = ? WHERE slug = ? COLLATE NOCASE",
                (iso, clean_team),
            )

        self.export_teams()
        self.export_agents()
        return self.get_agent(aid) or {}

    def get_team(self, slug: str) -> Optional[Dict[str, Any]]:
        clean = validate_slug(slug, "team slug")
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (clean,)
            ).fetchone()
            if not row:
                return None
            lineage = self._get_team_lineage_conn(conn, clean)
            roles = conn.execute(
                "SELECT * FROM agents WHERE team_slug = ? COLLATE NOCASE ORDER BY CASE WHEN role = 'lead' THEN 0 ELSE 1 END, role ASC",
                (clean,),
            ).fetchall()
            children = conn.execute(
                "SELECT slug, name, status FROM teams WHERE parent_team = ? COLLATE NOCASE ORDER BY slug ASC",
                (clean,),
            ).fetchall()
            out = self._serialize_team_row(row, len(lineage))
            out["lineage"] = [r["slug"] for r in lineage]
            out["roles"] = [self._serialize_agent_row(r) for r in roles]
            out["child_teams"] = [dict(c) for c in children]
            return out

    def list_teams(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            query = "SELECT slug FROM teams"
            params: List[Any] = []
            if status:
                st = status.strip().lower()
                if st not in VALID_TEAM_STATUSES:
                    raise ValueError(f"Invalid status '{status}'.")
                query += " WHERE status = ?"
                params.append(st)
            slugs = [r["slug"] for r in conn.execute(query, params).fetchall()]

        teams = [t for s in slugs if (t := self.get_team(s)) is not None]
        teams.sort(key=lambda t: (t["layer"], t["slug"]))
        return teams

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        aid = normalize_agent_id(agent_id)
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ? COLLATE NOCASE", (aid,)
            ).fetchone()
            return self._serialize_agent_row(row) if row else None

    def list_agents(
        self, team_slug: Optional[str] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM agents WHERE 1=1"
        params: List[Any] = []
        if team_slug:
            query += " AND team_slug = ? COLLATE NOCASE"
            params.append(validate_slug(team_slug, "team slug"))
        if status:
            st = status.strip().lower()
            if st not in VALID_AGENT_STATUSES:
                raise ValueError(f"Invalid status '{status}'.")
            query += " AND status = ?"
            params.append(st)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        ordered = sorted(
            rows,
            key=lambda r: (
                0 if r["agent_id"].lower() == PRIME_ID else 1,
                r["team_slug"] or "",
                0 if r["role"] == "lead" else 1,
                r["role"],
            ),
        )
        return [self._serialize_agent_row(r) for r in ordered]

    # ------------------------------------------------------------------
    # Lifecycle Operations: Render Spawn, Activate, Prepare-Disable, Disable
    # ------------------------------------------------------------------

    def get_contacts(self, agent_id: str) -> Dict[str, Any]:
        aid = normalize_agent_id(agent_id)
        with self._get_connection() as conn:
            agent = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ? COLLATE NOCASE", (aid,)
            ).fetchone()
            if not agent:
                raise ValueError(f"Agent '{aid}' is not registered.")

            prime_row = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ? COLLATE NOCASE", (PRIME_ID,)
            ).fetchone()
            prime_info = self._serialize_agent_row(prime_row) if prime_row else None

            if aid == PRIME_ID:
                l1_leads = conn.execute(
                    """
                    SELECT a.* FROM agents a
                    JOIN teams t ON a.team_slug = t.slug
                    WHERE t.parent_team IS NULL AND a.role = 'lead'
                    ORDER BY t.slug ASC
                    """
                ).fetchall()
                return {
                    "agent_id": PRIME_ID,
                    "role": "prime",
                    "reports_to": "user",
                    "layer1_team_leads": [self._serialize_agent_row(r) for r in l1_leads],
                }

            t_slug = agent["team_slug"]
            team = conn.execute(
                "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (t_slug,)
            ).fetchone()
            lineage = self._get_team_lineage_conn(conn, t_slug)
            layer = len(lineage)

            if agent["role"] != "lead":
                lead_row = conn.execute(
                    "SELECT * FROM agents WHERE agent_id = ? COLLATE NOCASE",
                    (f"{t_slug}/lead",),
                ).fetchone()
                return {
                    "agent_id": aid,
                    "team_slug": t_slug,
                    "layer": layer,
                    "role": agent["role"],
                    "reports_to": self._serialize_agent_row(lead_row) if lead_row else None,
                    "direct_peers_allowed": False,
                    "note": f"Coordinate and escalate strictly through your Team Lead ('{t_slug}/lead').",
                }

            # Team Lead routing
            if team["parent_team"]:
                parent_lead_id = f"{team['parent_team'].lower()}/lead"
                superior_row = conn.execute(
                    "SELECT * FROM agents WHERE agent_id = ? COLLATE NOCASE",
                    (parent_lead_id,),
                ).fetchone()
                superior = self._serialize_agent_row(superior_row) if superior_row else None
            else:
                superior = prime_info

            teammates = conn.execute(
                "SELECT * FROM agents WHERE team_slug = ? COLLATE NOCASE AND role != 'lead' ORDER BY role ASC",
                (t_slug,),
            ).fetchall()
            child_leads = conn.execute(
                """
                SELECT a.* FROM agents a
                JOIN teams ct ON a.team_slug = ct.slug
                WHERE ct.parent_team = ? COLLATE NOCASE AND a.role = 'lead'
                ORDER BY ct.slug ASC
                """,
                (t_slug,),
            ).fetchall()

            parent_disabled = bool(superior and superior["status"] != "active")
            return {
                "agent_id": aid,
                "team_slug": t_slug,
                "layer": layer,
                "role": "lead",
                "reports_to": superior,
                "parent_disabled_warning": parent_disabled,
                "prime_fallback": prime_info if parent_disabled else None,
                "team_members": [self._serialize_agent_row(r) for r in teammates],
                "child_team_leads": [self._serialize_agent_row(r) for r in child_leads],
            }

    def render_spawn(
        self,
        team_slug: str,
        role: Optional[str] = None,
        mission_brief: str = "",
    ) -> List[Dict[str, Any]]:
        clean_team = validate_slug(team_slug, "team slug")
        clean_role = validate_role_slug(role) if role else None

        with self._get_connection() as conn:
            team = conn.execute(
                "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (clean_team,)
            ).fetchone()
            if not team:
                raise ValueError(f"Team '{clean_team}' does not exist.")

            lineage = self._get_team_lineage_conn(conn, clean_team)
            layer = len(lineage)
            lineage_display = " -> ".join([PRIME_ID, *[r["slug"] for r in lineage]])

            query = "SELECT * FROM agents WHERE team_slug = ? COLLATE NOCASE"
            params: List[Any] = [clean_team]
            if clean_role:
                query += " AND role = ? COLLATE NOCASE"
                params.append(clean_role)
            query += " ORDER BY CASE WHEN role = 'lead' THEN 0 ELSE 1 END, role ASC"
            role_rows = conn.execute(query, params).fetchall()
            if not role_rows:
                target = f"{clean_team}/{clean_role}" if clean_role else clean_team
                raise ValueError(f"No roles found for '{target}'.")

            # Gather inherited team charters from Layer 1 down to this team
            charter_blocks: List[str] = []
            for anc in lineage:
                anc_dir = self._abs_from_rel(anc["hive_path"])
                anc_agents_file = anc_dir / "AGENTS.md"
                if anc_agents_file.is_file():
                    content = anc_agents_file.read_text(encoding="utf-8").strip()
                    charter_blocks.append(
                        f"### [{anc['slug']}] (`{anc['hive_path']}/AGENTS.md`)\n{content}"
                    )
            inherited_charters = "\n\n".join(charter_blocks) if charter_blocks else "(No team charters found)"

            teammate_ids = [
                r["agent_id"]
                for r in conn.execute(
                    "SELECT agent_id FROM agents WHERE team_slug = ? COLLATE NOCASE AND role != 'lead' ORDER BY role ASC",
                    (clean_team,),
                ).fetchall()
            ]
            child_lead_ids = [
                f"{r['slug']}/lead"
                for r in conn.execute(
                    "SELECT slug FROM teams WHERE parent_team = ? COLLATE NOCASE ORDER BY slug ASC",
                    (clean_team,),
                ).fetchall()
            ]

        spawn_tmpl = self._load_template("spawn_prompt.md.tmpl")
        specs: List[Dict[str, Any]] = []

        for r in role_rows:
            aid = r["agent_id"]
            r_slug = r["role"]
            role_dir = self._abs_from_rel(r["role_path"])
            role_ws_rel = self._rel_posix(role_dir / "workspace")
            role_agents_path = role_dir / "AGENTS.md"
            role_charter = (
                role_agents_path.read_text(encoding="utf-8").strip()
                if role_agents_path.is_file()
                else r["responsibilities"]
            )

            if r_slug == "lead":
                superior_id = f"{team['parent_team']}/lead" if team["parent_team"] else PRIME_ID
                members_str = ", ".join(f"`{m}`" for m in teammate_ids) if teammate_ids else "(none provisioned yet)"
                children_str = ", ".join(f"`{c}`" for c in child_lead_ids) if child_lead_ids else "(none)"
                routing_summary = (
                    f"- **Role Type:** Team Leader (`{aid}`)\n"
                    f"- **Report & Escalate UP to:** `{superior_id}`\n"
                    f"- **Orchestrate Within Your Team:** {members_str}\n"
                    f"- **Coordinate Child Team Leads:** {children_str}\n"
                    f"- **Cross-Team Board Rule:** Use `--visibility team --team {clean_team} --with-team <other-team>` for parent/child handoffs."
                )
            else:
                routing_summary = (
                    f"- **Role Type:** Specialist (`{aid}`)\n"
                    f"- **Report & Escalate ONLY to Your Team Lead:** `{clean_team}/lead`\n"
                    f"- **Strict Boundary:** Never doorbell external teams or `{PRIME_ID}` directly."
                )

            is_read_only = not bool(r["write_tools"])
            if is_read_only:
                routing_summary += (
                    "\n- **[READ-ONLY ROLE MODE]:** Do NOT call `write_file` or `edit_file` on repository source code. "
                    "Use `run_command` strictly for `python3 ultron/core/core.py` board operations and non-mutating inspection/test commands."
                )

            system_prompt = render_template(
                spawn_tmpl,
                {
                    "AGENT_ID": aid,
                    "TEAM_NAME": team["name"],
                    "TEAM_SLUG": clean_team,
                    "LAYER": str(layer),
                    "ROLE_SLUG": r_slug,
                    "ROLE_TITLE": r["title"],
                    "LINEAGE_DISPLAY": lineage_display,
                    "ROLE_PATH": r["role_path"],
                    "ROLE_WORKSPACE_PATH": role_ws_rel,
                    "ROUTING_SUMMARY": routing_summary,
                    "INHERITED_CHARTERS": inherited_charters,
                    "ROLE_CHARTER": role_charter,
                },
            )

            subagent_type = f"ultron--{clean_team}--{r_slug}"
            initial_prompt = (
                f"Boot sequence for `{aid}` ({r['title']}):\n"
                f"1. Run your startup hydration commands (`list --as {aid} --visibility personal`, "
                f"`list --as {aid} --visibility team`, and `contacts {aid}`).\n"
            )
            if mission_brief.strip():
                initial_prompt += f"2. Initial directive: {mission_brief.strip()}\n"
            else:
                initial_prompt += (
                    "2. Confirm readiness in a brief reply to ULTRON PRIME and await doorbelled tasks on the board."
                )

            specs.append(
                {
                    "agent_id": aid,
                    "team_slug": clean_team,
                    "role": r_slug,
                    "read_only_mode": is_read_only,
                    "define_subagent": {
                        "Name": subagent_type,
                        "Description": f"ULTRON [{clean_team}] {r['title']} ({aid})",
                        "SystemPrompt": system_prompt,
                        # Antigravity gates `run_command` under EnableWriteTools; keep True so
                        # every Hive role can execute `python3 ultron/core/core.py` CLI commands.
                        "EnableWriteTools": True,
                        "EnableSubagentTools": False,  # Hard invariant: only ULTRON PRIME spawns agents
                        "EnableMCPTools": bool(r["mcp_tools"]),
                    },
                    "invoke_subagent": {
                        "TypeName": subagent_type,
                        "Role": f"{team['name']} - {r['title']}"[:60],
                        "Model": r["model"],
                        "Workspace": team["workspace_mode"],
                        "Prompt": initial_prompt,
                    },
                }
            )
        return specs

    def activate_agent(
        self,
        agent_id: str,
        conversation_id: str,
        allow_detached: bool = False,
    ) -> Dict[str, Any]:
        aid = normalize_agent_id(agent_id)
        if aid == PRIME_ID:
            return self.register_prime(conversation_id)
        cid = conversation_id.strip()
        if not cid:
            raise ValueError("conversation_id cannot be empty.")

        iso = now_iso()
        with self._get_connection() as conn:
            a_row = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ? COLLATE NOCASE", (aid,)
            ).fetchone()
            if not a_row:
                raise ValueError(f"Agent '{aid}' does not exist.")
            t_slug = a_row["team_slug"]
            t_row = conn.execute(
                "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (t_slug,)
            ).fetchone()

            if t_row["parent_team"] and not allow_detached:
                p_row = conn.execute(
                    "SELECT status FROM teams WHERE slug = ? COLLATE NOCASE",
                    (t_row["parent_team"],),
                ).fetchone()
                if not p_row or p_row["status"] != "active":
                    raise ValueError(
                        f"Cannot activate '{aid}': parent team '{t_row['parent_team']}' is disabled. "
                        f"Activate '{t_row['parent_team']}' first or pass --allow-detached."
                    )

            if a_row["role"] != "lead":
                lead_row = conn.execute(
                    "SELECT status FROM agents WHERE agent_id = ? COLLATE NOCASE",
                    (f"{t_slug}/lead",),
                ).fetchone()
                if (not lead_row or lead_row["status"] != "active") and not allow_detached:
                    raise ValueError(
                        f"Cannot activate specialist '{aid}' while Team Lead '{t_slug}/lead' is disabled. "
                        f"Activate '{t_slug}/lead' first (or use activate-team)."
                    )

            conn.execute(
                """
                UPDATE agents
                SET conversation_id = ?, status = 'active', last_seen = ?
                WHERE agent_id = ? COLLATE NOCASE
                """,
                (cid, iso, aid),
            )
            conn.execute(
                "UPDATE teams SET status = 'active', updated_at = ? WHERE slug = ? COLLATE NOCASE",
                (iso, t_slug),
            )
            lineage = self._get_team_lineage_conn(conn, t_slug)
            updated_team = conn.execute(
                "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (t_slug,)
            ).fetchone()
            self._write_team_manifest_on_disk(updated_team, len(lineage))

        self.export_teams()
        self.export_agents()
        return self.get_agent(aid) or {}

    def activate_team(
        self,
        team_slug: str,
        role_uuids: Mapping[str, str],
        allow_detached: bool = False,
        partial: bool = False,
    ) -> Dict[str, Any]:
        clean_team = validate_slug(team_slug, "team slug")
        if not role_uuids:
            raise ValueError("role_uuids mapping cannot be empty.")

        normalized_map: Dict[str, str] = {}
        for key, uuid_val in role_uuids.items():
            cid = str(uuid_val).strip()
            if not cid:
                raise ValueError(f"Empty UUID provided for '{key}'.")
            if "/" in key:
                norm_id = normalize_agent_id(key)
                if norm_id.split("/", 1)[0] != clean_team:
                    raise ValueError(f"Agent '{norm_id}' does not belong to team '{clean_team}'.")
                r_slug = norm_id.split("/", 1)[1]
            else:
                r_slug = validate_role_slug(key)
            normalized_map[r_slug] = cid

        iso = now_iso()
        with self._get_connection() as conn:
            t_row = conn.execute(
                "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (clean_team,)
            ).fetchone()
            if not t_row:
                raise ValueError(f"Team '{clean_team}' does not exist.")

            if t_row["parent_team"] and not allow_detached:
                p_row = conn.execute(
                    "SELECT status FROM teams WHERE slug = ? COLLATE NOCASE",
                    (t_row["parent_team"],),
                ).fetchone()
                if not p_row or p_row["status"] != "active":
                    raise ValueError(
                        f"Cannot activate team '{clean_team}': parent team '{t_row['parent_team']}' is disabled. "
                        f"Activate '{t_row['parent_team']}' first or pass --allow-detached."
                    )

            existing_roles = {
                r["role"].lower(): r
                for r in conn.execute(
                    "SELECT * FROM agents WHERE team_slug = ? COLLATE NOCASE", (clean_team,)
                ).fetchall()
            }
            unknown = sorted(set(normalized_map.keys()) - set(existing_roles.keys()))
            if unknown:
                raise ValueError(f"Unknown role(s) for team '{clean_team}': {unknown}")

            lead_will_be_active = (
                "lead" in normalized_map or existing_roles["lead"]["status"] == "active"
            )
            if not lead_will_be_active and not partial:
                raise ValueError(
                    f"Team activation for '{clean_team}' must include 'lead' UUID (or 'lead' must already be active)."
                )

            for r_slug, cid in normalized_map.items():
                conn.execute(
                    """
                    UPDATE agents
                    SET conversation_id = ?, status = 'active', last_seen = ?
                    WHERE agent_id = ? COLLATE NOCASE
                    """,
                    (cid, iso, f"{clean_team}/{r_slug}"),
                )

            conn.execute(
                "UPDATE teams SET status = 'active', updated_at = ? WHERE slug = ? COLLATE NOCASE",
                (iso, clean_team),
            )
            lineage = self._get_team_lineage_conn(conn, clean_team)
            updated_team = conn.execute(
                "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (clean_team,)
            ).fetchone()
            self._write_team_manifest_on_disk(updated_team, len(lineage))

        self.export_teams()
        self.export_agents()
        return self.get_team(clean_team) or {}

    def prepare_disable(self, team_slug: str, cascade: bool = False) -> Dict[str, Any]:
        clean_team = validate_slug(team_slug, "team slug")
        with self._get_connection() as conn:
            t_row = conn.execute(
                "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (clean_team,)
            ).fetchone()
            if not t_row:
                raise ValueError(f"Team '{clean_team}' does not exist.")

            descendants = self._get_descendants_conn(conn, clean_team)
            active_descendants = [d["slug"] for d in descendants if d["status"] == "active"]
            if active_descendants and not cascade:
                raise ValueError(
                    f"Cannot disable team '{clean_team}': active child teams exist ({active_descendants}). "
                    f"Re-run with --cascade to disable the entire subtree."
                )

            target_teams = [clean_team] + ([d["slug"].lower() for d in descendants] if cascade else [])
            placeholders = ",".join("?" for _ in target_teams)
            active_agents = conn.execute(
                f"""
                SELECT agent_id, team_slug, role, conversation_id
                FROM agents
                WHERE lower(team_slug) IN ({placeholders})
                  AND conversation_id != ''
                ORDER BY agent_id ASC
                """,
                target_teams,
            ).fetchall()

            uuids: List[str] = []
            seen_uuids: Set[str] = set()
            for r in active_agents:
                cid = r["conversation_id"].strip()
                if cid and cid not in seen_uuids:
                    seen_uuids.add(cid)
                    uuids.append(cid)

            return {
                "team_slug": clean_team,
                "cascade": cascade,
                "teams_affected": target_teams,
                "agents_to_kill": [dict(r) for r in active_agents],
                "conversation_ids_to_kill": uuids,
            }

    def disable_team(self, team_slug: str, cascade: bool = False) -> Dict[str, Any]:
        plan = self.prepare_disable(team_slug, cascade=cascade)
        target_teams = plan["teams_affected"]
        iso = now_iso()

        with self._get_connection() as conn:
            placeholders = ",".join("?" for _ in target_teams)
            conn.execute(
                f"""
                UPDATE agents
                SET conversation_id = '', status = 'disabled', last_seen = ?
                WHERE lower(team_slug) IN ({placeholders})
                """,
                [iso, *target_teams],
            )
            conn.execute(
                f"""
                UPDATE teams
                SET status = 'disabled', updated_at = ?
                WHERE lower(slug) IN ({placeholders})
                """,
                [iso, *target_teams],
            )
            for t_slug in target_teams:
                lineage = self._get_team_lineage_conn(conn, t_slug)
                t_row = conn.execute(
                    "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (t_slug,)
                ).fetchone()
                self._write_team_manifest_on_disk(t_row, len(lineage))

        self.export_teams()
        self.export_agents()
        return plan

    def disable_agent(self, agent_id: str) -> Dict[str, Any]:
        aid = normalize_agent_id(agent_id)
        if aid == PRIME_ID:
            raise ValueError(f"Cannot disable '{PRIME_ID}'.")
        iso = now_iso()
        with self._get_connection() as conn:
            a_row = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ? COLLATE NOCASE", (aid,)
            ).fetchone()
            if not a_row:
                raise ValueError(f"Agent '{aid}' does not exist.")
            t_slug = a_row["team_slug"]
            if a_row["role"] == "lead":
                active_peers = conn.execute(
                    """
                    SELECT agent_id FROM agents
                    WHERE team_slug = ? COLLATE NOCASE AND role != 'lead' AND status = 'active'
                    """,
                    (t_slug,),
                ).fetchall()
                if active_peers:
                    raise ValueError(
                        f"Cannot disable Team Lead '{aid}' while specialists are still active "
                        f"({[r['agent_id'] for r in active_peers]}). Use 'disable-team {t_slug}' instead."
                    )
            old_uuid = a_row["conversation_id"]
            conn.execute(
                "UPDATE agents SET conversation_id = '', status = 'disabled', last_seen = ? WHERE agent_id = ? COLLATE NOCASE",
                (iso, aid),
            )
            remaining = conn.execute(
                "SELECT COUNT(*) FROM agents WHERE team_slug = ? COLLATE NOCASE AND status = 'active'",
                (t_slug,),
            ).fetchone()[0]
            if remaining == 0:
                conn.execute(
                    "UPDATE teams SET status = 'disabled', updated_at = ? WHERE slug = ? COLLATE NOCASE",
                    (iso, t_slug),
                )
                lineage = self._get_team_lineage_conn(conn, t_slug)
                t_row = conn.execute(
                    "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (t_slug,)
                ).fetchone()
                self._write_team_manifest_on_disk(t_row, len(lineage))

        self.export_teams()
        self.export_agents()
        return {"agent_id": aid, "previous_conversation_id": old_uuid, "status": "disabled"}

    def remove_team(
        self,
        team_slug: str,
        cascade: bool = False,
        delete_files: bool = False,
    ) -> Dict[str, Any]:
        clean_team = validate_slug(team_slug, "team slug")
        with self._get_connection() as conn:
            t_row = conn.execute(
                "SELECT * FROM teams WHERE slug = ? COLLATE NOCASE", (clean_team,)
            ).fetchone()
            if not t_row:
                raise ValueError(f"Team '{clean_team}' does not exist.")

            descendants = self._get_descendants_conn(conn, clean_team)
            if descendants and not cascade:
                raise ValueError(
                    f"Cannot remove team '{clean_team}': child teams exist ({[d['slug'] for d in descendants]}). "
                    f"Pass --cascade to remove the entire subtree."
                )

            target_rows = [t_row, *descendants]
            active_any = [r["slug"] for r in target_rows if r["status"] == "active"]
            if active_any:
                raise ValueError(
                    f"Cannot remove active team(s) {active_any}. Disable and kill live sessions first."
                )

            # Delete bottom-up so ON DELETE RESTRICT on parent_team is respected
            for r in reversed(target_rows):
                conn.execute("DELETE FROM teams WHERE slug = ? COLLATE NOCASE", (r["slug"],))

            root_hive_dir = self._abs_from_rel(t_row["hive_path"])

        if delete_files and root_hive_dir.is_dir():
            shutil.rmtree(root_hive_dir)

        self.export_teams()
        self.export_agents()
        return {
            "removed_teams": [r["slug"] for r in target_rows],
            "deleted_files": delete_files,
        }

    # ------------------------------------------------------------------
    # Board Operations with Visibility & Authorization Enforcement
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_viewer(as_agent: Optional[str], show_all: bool) -> Tuple[str, bool]:
        raw_viewer = (as_agent or os.environ.get("ULTRON_AGENT_ID") or "").strip()
        viewer = normalize_agent_id(raw_viewer) if raw_viewer else ""
        if show_all:
            if viewer and viewer != PRIME_ID:
                raise PermissionError(
                    f"Agent '{viewer}' is not authorized to use --all. Pass --as {viewer} without --all."
                )
            return (PRIME_ID, True)
        if not viewer:
            raise PermissionError(
                "Caller identity required for board reads: pass --as <agent_id> (or set ULTRON_AGENT_ID), or --all (ULTRON PRIME)."
            )
        if viewer == PRIME_ID:
            return (PRIME_ID, True)
        return (viewer, False)

    @staticmethod
    def _can_access_thread(viewer_id: str, unrestricted: bool, thread_row: Mapping[str, Any]) -> bool:
        if unrestricted or viewer_id == PRIME_ID:
            return True
        vis = (thread_row["visibility"] or "team").lower()
        if vis == "global":
            return True
        viewer_team = viewer_id.split("/", 1)[0] if "/" in viewer_id else ""
        if vis == "team":
            t_slug = (thread_row["team_slug"] or "").lower()
            w_slug = (thread_row["with_team"] or "").lower()
            return bool(viewer_team and viewer_team in {t_slug, w_slug})
        if vis == "personal":
            owner = (thread_row["owner_agent"] or "").lower()
            return viewer_id.lower() == owner
        return False

    def _visibility_sql_clause(self, viewer_id: str, unrestricted: bool) -> Tuple[str, List[Any]]:
        if unrestricted or viewer_id == PRIME_ID:
            return ("1=1", [])
        viewer_team = viewer_id.split("/", 1)[0]
        clause = (
            "(t.visibility = 'global' "
            "OR (t.visibility = 'team' AND (lower(t.team_slug) = ? OR lower(t.with_team) = ?)) "
            "OR (t.visibility = 'personal' AND lower(t.owner_agent) = ?))"
        )
        return (clause, [viewer_team, viewer_team, viewer_id])

    def _resolve_author_and_touch(
        self, conn: sqlite3.Connection, author: str, author_id: str, iso_time: str
    ) -> Tuple[str, Optional[str], str]:
        norm_author = normalize_agent_id(author)
        row = conn.execute(
            "SELECT * FROM agents WHERE agent_id = ? COLLATE NOCASE", (norm_author,)
        ).fetchone()
        if not row and norm_author != PRIME_ID:
            raise ValueError(
                f"Author '{norm_author}' is not a registered ULTRON agent. Create the team/role first."
            )
        resolved_uuid = author_id.strip()
        if row:
            if not resolved_uuid:
                resolved_uuid = row["conversation_id"]
            conn.execute(
                "UPDATE agents SET last_seen = ? WHERE agent_id = ? COLLATE NOCASE",
                (iso_time, norm_author),
            )
        author_team = None if norm_author == PRIME_ID else norm_author.split("/", 1)[0]
        return (norm_author, author_team, resolved_uuid)

    def create_thread(
        self,
        title: str,
        author: str,
        content: str,
        category: str = "general",
        visibility: Optional[str] = None,
        team_slug: Optional[str] = None,
        with_team: Optional[str] = None,
        tags: str = "",
        author_id: str = "",
        auto_backup: bool = True,
    ) -> Dict[str, Any]:
        clean_title = title.strip()
        clean_content = content.strip()
        if not clean_title:
            raise ValueError("Thread title cannot be empty.")
        if not clean_content:
            raise ValueError("Thread content cannot be empty.")

        iso = now_iso()
        with self._get_connection() as conn:
            norm_author, author_team, resolved_uuid = self._resolve_author_and_touch(
                conn, author, author_id, iso
            )

            chosen_vis = (
                visibility.strip().lower()
                if visibility
                else ("global" if norm_author == PRIME_ID and not team_slug else "team")
            )
            if chosen_vis not in VALID_VISIBILITIES:
                raise ValueError(
                    f"Invalid visibility '{chosen_vis}'. Must be one of {sorted(VALID_VISIBILITIES)}."
                )

            resolved_team: Optional[str] = validate_slug(team_slug, "team") if team_slug else None
            resolved_with: Optional[str] = validate_slug(with_team, "with_team") if with_team else None
            resolved_owner: Optional[str] = None

            if chosen_vis == "personal":
                if with_team:
                    raise ValueError("--with-team is only valid for --visibility team.")
                if team_slug and author_team and resolved_team != author_team:
                    raise PermissionError(
                        f"Author '{norm_author}' cannot create a personal thread under team '{resolved_team}'."
                    )
                resolved_owner = norm_author
                resolved_team = author_team

            elif chosen_vis == "team":
                if norm_author == PRIME_ID:
                    if not resolved_team:
                        raise ValueError(
                            f"'{PRIME_ID}' must specify --team <slug> when creating a 'team' thread."
                        )
                else:
                    if resolved_team and resolved_team != author_team:
                        raise PermissionError(
                            f"Author '{norm_author}' belongs to '{author_team}' and cannot create team threads owned by '{resolved_team}' (use --team {author_team} --with-team {resolved_team} instead)."
                        )
                    resolved_team = author_team

                t_exists = conn.execute(
                    "SELECT slug FROM teams WHERE slug = ? COLLATE NOCASE", (resolved_team,)
                ).fetchone()
                if not t_exists:
                    raise ValueError(f"Team '{resolved_team}' does not exist.")

                if resolved_with:
                    if resolved_with == resolved_team:
                        raise ValueError("--with-team cannot be the same as the owning team.")
                    w_exists = conn.execute(
                        "SELECT slug FROM teams WHERE slug = ? COLLATE NOCASE", (resolved_with,)
                    ).fetchone()
                    if not w_exists:
                        raise ValueError(f"Target --with-team '{resolved_with}' does not exist.")

            elif chosen_vis == "global":
                if with_team:
                    raise ValueError("--with-team is only valid for --visibility team.")
                if not resolved_team and author_team:
                    resolved_team = author_team

            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO threads (
                    title, category, status, visibility, team_slug,
                    with_team, owner_agent, author, author_id, created_at, updated_at
                )
                VALUES (?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_title,
                    category.strip().lower(),
                    chosen_vis,
                    resolved_team,
                    resolved_with,
                    resolved_owner,
                    norm_author,
                    resolved_uuid,
                    iso,
                    iso,
                ),
            )
            thread_id = int(cursor.lastrowid)
            cursor.execute(
                """
                INSERT INTO posts (thread_id, parent_post_id, author, author_id, content, tags, created_at)
                VALUES (?, NULL, ?, ?, ?, ?, ?)
                """,
                (thread_id, norm_author, resolved_uuid, clean_content, tags.strip(), iso),
            )
            post_id = int(cursor.lastrowid)

        if auto_backup:
            self.export_thread(thread_id)
            self.export_agents()

        return {
            "thread_id": thread_id,
            "post_id": post_id,
            "title": clean_title,
            "category": category.strip().lower(),
            "visibility": chosen_vis,
            "team_slug": resolved_team,
            "with_team": resolved_with,
            "owner_agent": resolved_owner,
            "author": norm_author,
            "author_id": resolved_uuid,
            "created_at": iso,
        }

    def add_post(
        self,
        thread_id: int,
        author: str,
        content: str,
        parent_post_id: Optional[int] = None,
        tags: str = "",
        author_id: str = "",
        auto_backup: bool = True,
    ) -> Dict[str, Any]:
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("Post content cannot be empty.")

        iso = now_iso()
        with self._get_connection() as conn:
            t_row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if not t_row:
                raise ValueError(f"Thread #{thread_id} does not exist.")

            norm_author, _, resolved_uuid = self._resolve_author_and_touch(
                conn, author, author_id, iso
            )
            if not self._can_access_thread(norm_author, norm_author == PRIME_ID, t_row):
                raise PermissionError(
                    f"Author '{norm_author}' is not authorized to access or reply to Thread #{thread_id} "
                    f"(visibility='{t_row['visibility']}')."
                )

            if parent_post_id is not None:
                p_exists = conn.execute(
                    "SELECT id FROM posts WHERE id = ? AND thread_id = ?",
                    (parent_post_id, thread_id),
                ).fetchone()
                if not p_exists:
                    raise ValueError(
                        f"Parent post #{parent_post_id} does not exist in Thread #{thread_id}."
                    )

            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO posts (thread_id, parent_post_id, author, author_id, content, tags, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (thread_id, parent_post_id, norm_author, resolved_uuid, clean_content, tags.strip(), iso),
            )
            post_id = int(cursor.lastrowid)
            cursor.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (iso, thread_id))

        if auto_backup:
            self.export_thread(thread_id)
            self.export_agents()

        return {
            "thread_id": thread_id,
            "post_id": post_id,
            "author": norm_author,
            "author_id": resolved_uuid,
            "created_at": iso,
        }

    def list_threads(
        self,
        as_agent: Optional[str] = None,
        show_all: bool = False,
        visibility: Optional[str] = None,
        team_slug: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        viewer_id, unrestricted = self._resolve_viewer(as_agent, show_all)
        vis_clause, vis_params = self._visibility_sql_clause(viewer_id, unrestricted)

        query = f"""
            SELECT t.id, t.title, t.category, t.status, t.visibility,
                   t.team_slug, t.with_team, t.owner_agent, t.author,
                   t.created_at, t.updated_at, COUNT(p.id) AS post_count
            FROM threads t
            LEFT JOIN posts p ON t.id = p.thread_id
            WHERE {vis_clause}
        """
        params: List[Any] = list(vis_params)

        if visibility:
            v = visibility.strip().lower()
            if v not in VALID_VISIBILITIES:
                raise ValueError(f"Invalid visibility '{visibility}'.")
            query += " AND t.visibility = ?"
            params.append(v)
        if team_slug:
            ts = validate_slug(team_slug, "team")
            query += " AND (lower(t.team_slug) = ? OR lower(t.with_team) = ?)"
            params.extend([ts, ts])
        if category:
            query += " AND t.category = ?"
            params.append(category.strip().lower())
        if status:
            st = status.strip().lower()
            if st not in VALID_THREAD_STATUSES:
                raise ValueError(f"Invalid thread status '{status}'.")
            query += " AND t.status = ?"
            params.append(st)

        query += " GROUP BY t.id ORDER BY t.updated_at DESC, t.id DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_thread(
        self,
        thread_id: int,
        as_agent: Optional[str] = None,
        show_all: bool = False,
    ) -> Optional[Dict[str, Any]]:
        viewer_id, unrestricted = self._resolve_viewer(as_agent, show_all)
        with self._get_connection() as conn:
            t_row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if not t_row:
                return None
            if not self._can_access_thread(viewer_id, unrestricted, t_row):
                raise PermissionError(
                    f"Agent '{viewer_id}' is not authorized to view Thread #{thread_id} "
                    f"(visibility='{t_row['visibility']}')."
                )
            p_rows = conn.execute(
                "SELECT * FROM posts WHERE thread_id = ? ORDER BY id ASC",
                (thread_id,),
            ).fetchall()
            out = dict(t_row)
            out["posts"] = [dict(r) for r in p_rows]
            return out

    def search(
        self,
        query_str: str,
        as_agent: Optional[str] = None,
        show_all: bool = False,
        visibility: Optional[str] = None,
        team_slug: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        viewer_id, unrestricted = self._resolve_viewer(as_agent, show_all)
        vis_clause, vis_params = self._visibility_sql_clause(viewer_id, unrestricted)

        extra_sql = ""
        extra_params: List[Any] = []
        if visibility:
            v = visibility.strip().lower()
            if v not in VALID_VISIBILITIES:
                raise ValueError(f"Invalid visibility '{visibility}'.")
            extra_sql += " AND t.visibility = ?"
            extra_params.append(v)
        if team_slug:
            ts = validate_slug(team_slug, "team")
            extra_sql += " AND (lower(t.team_slug) = ? OR lower(t.with_team) = ?)"
            extra_params.extend([ts, ts])

        fts_sql = f"""
            SELECT p.id AS post_id, p.thread_id, t.title AS thread_title, t.category,
                   t.visibility, t.team_slug, t.with_team, t.owner_agent,
                   p.author, p.content, p.tags, p.created_at
            FROM posts_fts fts
            JOIN posts p ON fts.rowid = p.id
            JOIN threads t ON p.thread_id = t.id
            WHERE posts_fts MATCH ? AND {vis_clause}{extra_sql}
            ORDER BY rank
            LIMIT ?
        """
        with self._get_connection() as conn:
            try:
                rows = conn.execute(
                    fts_sql, [query_str, *vis_params, *extra_params, limit]
                ).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.OperationalError:
                like_pat = f"%{query_str}%"
                like_sql = f"""
                    SELECT p.id AS post_id, p.thread_id, t.title AS thread_title, t.category,
                           t.visibility, t.team_slug, t.with_team, t.owner_agent,
                           p.author, p.content, p.tags, p.created_at
                    FROM posts p
                    JOIN threads t ON p.thread_id = t.id
                    WHERE (p.content LIKE ? OR p.tags LIKE ? OR t.title LIKE ?)
                      AND {vis_clause}{extra_sql}
                    ORDER BY p.created_at DESC
                    LIMIT ?
                """
                rows = conn.execute(
                    like_sql,
                    [like_pat, like_pat, like_pat, *vis_params, *extra_params, limit],
                ).fetchall()
                return [dict(r) for r in rows]

    def set_thread_status(
        self,
        thread_id: int,
        status: str,
        as_agent: Optional[str] = None,
        show_all: bool = False,
        auto_backup: bool = True,
    ) -> bool:
        st = status.strip().lower()
        if st not in VALID_THREAD_STATUSES:
            raise ValueError(
                f"Invalid thread status '{status}'. Must be one of {sorted(VALID_THREAD_STATUSES)}."
            )
        viewer_id, unrestricted = self._resolve_viewer(as_agent, show_all)
        iso = now_iso()
        with self._get_connection() as conn:
            t_row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if not t_row:
                return False
            if not self._can_access_thread(viewer_id, unrestricted, t_row):
                raise PermissionError(
                    f"Agent '{viewer_id}' is not authorized to modify Thread #{thread_id}."
                )
            conn.execute(
                "UPDATE threads SET status = ?, updated_at = ? WHERE id = ?",
                (st, iso, thread_id),
            )
        if auto_backup:
            self.export_thread(thread_id)
        return True

    def reclassify_thread(
        self,
        thread_id: int,
        visibility: str,
        team_slug: Optional[str] = None,
        with_team: Optional[str] = None,
        owner_agent: Optional[str] = None,
        as_agent: Optional[str] = None,
        show_all: bool = False,
        auto_backup: bool = True,
    ) -> Dict[str, Any]:
        viewer_id, unrestricted = self._resolve_viewer(as_agent, show_all)
        if not unrestricted and viewer_id != PRIME_ID:
            raise PermissionError(
                f"Agent '{viewer_id}' is not authorized to reclassify threads. Only '{PRIME_ID}' (or --all) can reclassify."
            )

        vis = visibility.strip().lower()
        if vis not in VALID_VISIBILITIES:
            raise ValueError(
                f"Invalid visibility '{visibility}'. Must be one of {sorted(VALID_VISIBILITIES)}."
            )

        iso = now_iso()
        with self._get_connection() as conn:
            t_row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if not t_row:
                raise ValueError(f"Thread #{thread_id} does not exist.")

            new_team: Optional[str] = None
            new_with: Optional[str] = None
            new_owner: Optional[str] = None

            if vis == "personal":
                if with_team:
                    raise ValueError("--with-team cannot be set on a 'personal' thread.")
                candidate_owner = normalize_agent_id(
                    owner_agent or t_row["owner_agent"] or t_row["author"]
                )
                if candidate_owner != PRIME_ID:
                    owner_row = conn.execute(
                        "SELECT agent_id, team_slug FROM agents WHERE agent_id = ? COLLATE NOCASE",
                        (candidate_owner,),
                    ).fetchone()
                    if not owner_row:
                        raise ValueError(
                            f"Target owner agent '{candidate_owner}' does not exist."
                        )
                    new_team = owner_row["team_slug"]
                else:
                    new_team = None
                new_owner = candidate_owner

            elif vis == "team":
                candidate_team = team_slug or t_row["team_slug"]
                if not candidate_team and "/" in t_row["author"]:
                    candidate_team = t_row["author"].split("/", 1)[0]
                if not candidate_team:
                    raise ValueError("Reclassifying to 'team' requires --team <slug>.")
                new_team = validate_slug(candidate_team, "team")
                t_exists = conn.execute(
                    "SELECT slug FROM teams WHERE slug = ? COLLATE NOCASE", (new_team,)
                ).fetchone()
                if not t_exists:
                    raise ValueError(f"Target team '{new_team}' does not exist.")

                if with_team:
                    new_with = validate_slug(with_team, "with_team")
                    if new_with == new_team:
                        raise ValueError("--with-team cannot equal --team.")
                    w_exists = conn.execute(
                        "SELECT slug FROM teams WHERE slug = ? COLLATE NOCASE", (new_with,)
                    ).fetchone()
                    if not w_exists:
                        raise ValueError(f"Target --with-team '{new_with}' does not exist.")

            elif vis == "global":
                if with_team:
                    raise ValueError("--with-team cannot be set on a 'global' thread.")
                if team_slug:
                    new_team = validate_slug(team_slug, "team")
                    t_exists = conn.execute(
                        "SELECT slug FROM teams WHERE slug = ? COLLATE NOCASE", (new_team,)
                    ).fetchone()
                    if not t_exists:
                        raise ValueError(f"Target team '{new_team}' does not exist.")
                else:
                    new_team = t_row["team_slug"]

            conn.execute(
                """
                UPDATE threads
                SET visibility = ?, team_slug = ?, with_team = ?, owner_agent = ?, updated_at = ?
                WHERE id = ?
                """,
                (vis, new_team, new_with, new_owner, iso, thread_id),
            )

        if auto_backup:
            self.export_thread(thread_id)
        return self.get_thread(thread_id, show_all=True) or {}

    def get_stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            total_teams = conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
            active_teams = conn.execute("SELECT COUNT(*) FROM teams WHERE status = 'active'").fetchone()[0]
            total_agents = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            active_agents = conn.execute("SELECT COUNT(*) FROM agents WHERE status = 'active'").fetchone()[0]
            total_threads = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
            total_posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            vis_counts = conn.execute(
                "SELECT visibility, COUNT(*) FROM threads GROUP BY visibility"
            ).fetchall()
            cat_counts = conn.execute(
                "SELECT category, COUNT(*) FROM threads GROUP BY category"
            ).fetchall()
            status_counts = conn.execute(
                "SELECT status, COUNT(*) FROM threads GROUP BY status"
            ).fetchall()

        return {
            "repo_root": str(self.repo_root),
            "db_path": str(self.db_path),
            "hive_dir": str(self.hive_dir),
            "teams_file": str(self.teams_file),
            "agents_file": str(self.agents_file),
            "threads_dir": str(self.threads_dir),
            "total_teams": total_teams,
            "active_teams": active_teams,
            "total_agents": total_agents,
            "active_agents": active_agents,
            "total_threads": total_threads,
            "total_posts": total_posts,
            "visibilities": {r[0]: r[1] for r in vis_counts},
            "categories": {r[0]: r[1] for r in cat_counts},
            "statuses": {r[0]: r[1] for r in status_counts},
        }


# ----------------------------------------------------------------------
# Human-Readable Formatters
# ----------------------------------------------------------------------


def format_org_tree(core: UltronCore) -> str:
    prime = core.get_agent(PRIME_ID)
    teams = core.list_teams()
    prime_state = (
        f"ACTIVE ({prime['conversation_id']})"
        if prime and prime["status"] == "active" and prime["conversation_id"]
        else "UNREGISTERED"
    )
    lines = [f"[ULTRON HIVE] {PRIME_ID.upper()} [{prime_state}]"]
    if not teams:
        lines.append("  └── (No teams created in ultron/hive/ yet)")
        return "\n".join(lines)

    by_parent: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for t in teams:
        by_parent.setdefault(t["parent_team"], []).append(t)

    def render_branch(parent: Optional[str], prefix: str) -> None:
        children = by_parent.get(parent, [])
        for idx, t in enumerate(children):
            is_last = idx == len(children) - 1
            connector = "└── " if is_last else "├── "
            active_roles = sum(1 for r in t["roles"] if r["status"] == "active")
            role_names = ", ".join(
                f"{r['role']}*" if r["status"] == "active" else r["role"]
                for r in t["roles"]
            )
            lines.append(
                f"{prefix}{connector}[L{t['layer']}] {t['slug']} ({t['name']}) "
                f"[{t['status'].upper()} | {active_roles}/{len(t['roles'])} active] "
                f"roles: [{role_names}]"
            )
            next_prefix = prefix + ("    " if is_last else "│   ")
            render_branch(t["slug"], next_prefix)

    render_branch(None, "  ")
    return "\n".join(lines)


def format_agent_table(agents: List[Dict[str, Any]]) -> str:
    if not agents:
        return "[ULTRON] No registered agents/roles found."
    lines = [f"[ULTRON] Registered Roles & Sessions ({len(agents)}):\n"]
    header = f"{'AGENT ID':<28} {'STATUS':<10} {'MODEL':<10} {'CONVERSATION ID (UUID)':<38} {'TITLE'}"
    lines.append(header)
    lines.append("-" * 110)
    for a in agents:
        cid = a["conversation_id"] or "-"
        lines.append(
            f"{a['agent_id']:<28} {a['status']:<10} {a['model']:<10} {cid:<38} {a['title']}"
        )
    return "\n".join(lines)


def format_scope_badge(t: Mapping[str, Any]) -> str:
    vis = t.get("visibility", "team")
    if vis == "personal":
        return f"personal:{t.get('owner_agent')}"
    if vis == "team":
        if t.get("with_team"):
            return f"team:{t.get('team_slug')}<->{t.get('with_team')}"
        return f"team:{t.get('team_slug')}"
    return "global"


def format_thread_view(thread: Dict[str, Any]) -> str:
    lines = ["=" * 84]
    lines.append(f"THREAD #{thread['id']}: {thread['title']}")
    lines.append(
        f"Scope: [{format_scope_badge(thread)}] | Category: [{thread['category'].upper()}] | "
        f"Status: [{thread['status'].upper()}] | By: {thread['author']} ({thread['created_at'][:19]})"
    )
    lines.append("=" * 84)
    for post in thread.get("posts", []):
        reply_info = f" (reply to #{post['parent_post_id']})" if post.get("parent_post_id") else ""
        lines.append(
            f"\n--- Post #{post['id']} by @{post['author']}{reply_info} at {post['created_at'][:19]} ---"
        )
        if post.get("tags"):
            lines.append(f"Tags: [{post['tags']}]")
        lines.append("")
        for line in post["content"].splitlines():
            lines.append(f"  {line}")
    lines.append("\n" + "=" * 84)
    return "\n".join(lines)


# ----------------------------------------------------------------------
# CLI Entrypoint
# ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=argparse.SUPPRESS, help="Override ULTRON repository root")
    common.add_argument("--db", default=argparse.SUPPRESS, help="Override SQLite database path")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Emit machine-readable JSON output")

    parser = argparse.ArgumentParser(
        description="ULTRON Core: Org Registry, N-Layer Hive Scaffolder & Visibility-Scoped Message Board",
        parents=[common],
    )
    parser.set_defaults(root=None, db=None, json=False)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_cmd(
        name: str, help_text: str, aliases: Optional[List[str]] = None
    ) -> argparse.ArgumentParser:
        return sub.add_parser(name, aliases=aliases or [], help=help_text, parents=[common])

    # register-prime
    p_prime = add_cmd("register-prime", "Register/update ULTRON PRIME session UUID")
    p_prime.add_argument("--id", required=True, help="ULTRON PRIME conversation UUID")

    # org-tree
    add_cmd("org-tree", "Display full N-layer Hive organization tree")

    # create-team
    p_ct = add_cmd("create-team", "Create a team folder in ultron/hive/ and register it")
    p_ct.add_argument("--slug", required=True, help="Unique team slug (kebab-case)")
    p_ct.add_argument("--name", required=True, help="Human-readable team name")
    p_ct.add_argument("--mission", required=True, help="Team mission and scope boundaries")
    p_ct.add_argument("--parent", default=None, help="Parent team slug (omit for Layer 1 under ULTRON PRIME)")
    p_ct.add_argument("--model", default="flash", choices=sorted(VALID_MODELS), help="Default model tier (default: flash)")
    p_ct.add_argument("--workspace", default="inherit", choices=sorted(VALID_WORKSPACES), help="Workspace mode (default: inherit)")
    p_ct.add_argument("--lead-responsibilities", default="", help="Optional custom Team Lead responsibilities")

    # add-role
    p_ar = add_cmd("add-role", "Add a specialist role to a team")
    p_ar.add_argument("--team", required=True, help="Team slug")
    p_ar.add_argument("--role", required=True, help="Role slug (e.g. coder, reviewer, designer)")
    p_ar.add_argument("--title", required=True, help="Human-readable role title")
    p_ar.add_argument("--responsibilities", required=True, help="Role duties and deliverables")
    p_ar.add_argument("--model", default=None, choices=sorted(VALID_MODELS), help="Override model for this role")
    p_ar.add_argument(
        "--read-only",
        action="store_true",
        help="Enforce [READ-ONLY ROLE MODE] prompt guardrails while preserving run_command for core.py",
    )
    p_ar.add_argument("--no-mcp", action="store_true", help="Disable MCP tools (EnableMCPTools=False)")

    # teams
    p_tms = add_cmd("teams", "List registered teams")
    p_tms.add_argument("--status", default=None, choices=sorted(VALID_TEAM_STATUSES), help="Filter by status")

    # team-info
    p_ti = add_cmd("team-info", "Show detailed info and role roster for a team")
    p_ti.add_argument("slug", help="Team slug")

    # render-spawn (alias: prepare-spawn)
    p_rs = add_cmd(
        "render-spawn",
        "Generate Antigravity define_subagent + invoke_subagent payloads",
        aliases=["prepare-spawn"],
    )
    p_rs.add_argument("team", help="Team slug")
    p_rs.add_argument("--role", default=None, help="Optional single role slug to render")
    p_rs.add_argument("--brief", default="", help="Optional initial directive appended to startup prompt")

    # activate-team
    p_at = add_cmd("activate-team", "Bind live Antigravity UUIDs and mark a team active")
    p_at.add_argument("team", help="Team slug")
    p_at.add_argument("--uuids", required=True, help='JSON object mapping role -> UUID (e.g. \'{"lead":"...","coder":"..."}\')')
    p_at.add_argument("--allow-detached", action="store_true", help="Allow activation even if parent team is disabled")
    p_at.add_argument("--partial", action="store_true", help="Allow partial role activation")

    # activate-agent
    p_aa = add_cmd("activate-agent", "Bind a live Antigravity UUID to a single role")
    p_aa.add_argument("agent_id", help="Agent ID (<team>/<role> or ultron-prime)")
    p_aa.add_argument("--id", required=True, help="Conversation UUID")
    p_aa.add_argument("--allow-detached", action="store_true", help="Allow activation if parent/lead is disabled")

    # prepare-disable
    p_pd = add_cmd("prepare-disable", "List live UUIDs to kill before disabling a team")
    p_pd.add_argument("team", help="Team slug")
    p_pd.add_argument("--cascade", action="store_true", help="Include all descendant child teams")

    # disable-team
    p_dt = add_cmd("disable-team", "Clear UUIDs and mark a team disabled after killing sessions")
    p_dt.add_argument("team", help="Team slug")
    p_dt.add_argument("--cascade", action="store_true", help="Disable entire descendant subtree")

    # disable-agent
    p_da = add_cmd("disable-agent", "Disable a single specialist role")
    p_da.add_argument("agent_id", help="Agent ID (<team>/<role>)")

    # remove-team
    p_rm = add_cmd("remove-team", "Remove a disabled team from registry (preserves board threads)")
    p_rm.add_argument("team", help="Team slug")
    p_rm.add_argument("--cascade", action="store_true", help="Remove child teams recursively")
    p_rm.add_argument("--delete-files", action="store_true", help="Also delete ultron/hive/<team> folder on disk")

    # agents
    p_ag = add_cmd("agents", "List registered roles and live session UUIDs")
    p_ag.add_argument("--team", default=None, help="Filter by team slug")
    p_ag.add_argument("--status", default=None, choices=sorted(VALID_AGENT_STATUSES), help="Filter by status")

    # whois
    p_who = add_cmd("whois", "Resolve <team>/<role> or ultron-prime to live session UUID")
    p_who.add_argument("agent_id", help="Agent ID (e.g. platform/lead or ultron-prime)")
    p_who.add_argument("--id-only", action="store_true", help="Print ONLY raw UUID to stdout (errors go strictly to stderr)")

    # contacts
    p_con = add_cmd("contacts", "Show chain-of-command contacts and live UUIDs for an agent")
    p_con.add_argument("agent_id", help="Agent ID (e.g. platform/lead)")

    # new-thread
    p_new = add_cmd("new-thread", "Create a visibility-scoped board thread")
    p_new.add_argument("--title", required=True, help="Thread title")
    p_new.add_argument("--author", required=True, help="Canonical author ID (<team>/<role> or ultron-prime)")
    p_new.add_argument("--content", "-m", required=True, help="Initial post content")
    p_new.add_argument("--category", default="general", help="Category (task, architecture, review, escalation, lesson, etc.)")
    p_new.add_argument("--visibility", default=None, choices=sorted(VALID_VISIBILITIES), help="Visibility (personal | team | global)")
    p_new.add_argument("--team", default=None, help="Owning team slug (inferred from author if omitted)")
    p_new.add_argument("--with-team", default=None, help="Secondary team slug for parent/child handoffs (team visibility only)")
    p_new.add_argument("--tags", default="", help="Comma-separated tags")
    p_new.add_argument("--author-id", default="", help="Optional conversation UUID override")

    # reply
    p_rep = add_cmd("reply", "Reply to an existing thread (enforces visibility auth)")
    p_rep.add_argument("thread_id", type=int, help="Thread ID")
    p_rep.add_argument("--author", required=True, help="Canonical author ID (<team>/<role> or ultron-prime)")
    p_rep.add_argument("--content", "-m", required=True, help="Reply body")
    p_rep.add_argument("--reply-to", type=int, default=None, help="Optional parent post ID")
    p_rep.add_argument("--tags", default="", help="Comma-separated tags")
    p_rep.add_argument("--author-id", default="", help="Optional conversation UUID override")

    # list
    p_lst = add_cmd("list", "List visible threads (--as <agent_id> or --all required)")
    p_lst.add_argument("--as", dest="as_agent", default=None, help="Caller agent ID (<team>/<role> or ultron-prime)")
    p_lst.add_argument("--all", dest="show_all", action="store_true", help="Unfiltered view (ULTRON PRIME / Curator)")
    p_lst.add_argument("--visibility", default=None, choices=sorted(VALID_VISIBILITIES), help="Filter by visibility")
    p_lst.add_argument("--team", default=None, help="Filter by team involvement")
    p_lst.add_argument("--category", default=None, help="Filter by category")
    p_lst.add_argument("--status", default=None, choices=sorted(VALID_THREAD_STATUSES), help="Filter by status")
    p_lst.add_argument("--limit", type=int, default=25, help="Max threads to return")

    # view
    p_vw = add_cmd("view", "View full thread and replies (--as <agent_id> or --all required)")
    p_vw.add_argument("thread_id", type=int, help="Thread ID")
    p_vw.add_argument("--as", dest="as_agent", default=None, help="Caller agent ID")
    p_vw.add_argument("--all", dest="show_all", action="store_true", help="Unfiltered view (ULTRON PRIME / Curator)")

    # search
    p_sr = add_cmd("search", "Full-text search across visible threads (--as <agent_id> or --all required)")
    p_sr.add_argument("query", help="Search query")
    p_sr.add_argument("--as", dest="as_agent", default=None, help="Caller agent ID")
    p_sr.add_argument("--all", dest="show_all", action="store_true", help="Unfiltered view (ULTRON PRIME / Curator)")
    p_sr.add_argument("--visibility", default=None, choices=sorted(VALID_VISIBILITIES), help="Filter by visibility")
    p_sr.add_argument("--team", default=None, help="Filter by team involvement")
    p_sr.add_argument("--limit", type=int, default=20, help="Max results")

    # set-status (alias: status)
    p_st = add_cmd("set-status", "Update thread status", aliases=["status"])
    p_st.add_argument("thread_id", type=int, help="Thread ID")
    p_st.add_argument("status", choices=sorted(VALID_THREAD_STATUSES), help="New status")
    p_st.add_argument("--as", dest="as_agent", default=None, help="Caller agent ID")
    p_st.add_argument("--all", dest="show_all", action="store_true", help="Unfiltered access (ULTRON PRIME)")

    # reclassify
    p_rc = add_cmd("reclassify", "Reclassify a thread's visibility/scope (ULTRON PRIME / Curator)")
    p_rc.add_argument("thread_id", type=int, help="Thread ID")
    p_rc.add_argument("--visibility", required=True, choices=sorted(VALID_VISIBILITIES), help="Target visibility")
    p_rc.add_argument("--team", default=None, help="Target owning team slug")
    p_rc.add_argument("--with-team", default=None, help="Target secondary team slug (team visibility)")
    p_rc.add_argument("--owner", default=None, help="Target owner agent_id (personal visibility)")
    p_rc.add_argument("--as", dest="as_agent", default=None, help="Caller agent ID (must be ultron-prime)")
    p_rc.add_argument("--all", dest="show_all", action="store_true", help="Authorized ULTRON PRIME override")

    # backup / restore / stats
    add_cmd("backup", "Export all teams, agents, and threads to Git-tracked JSON")
    add_cmd("restore", "Reconcile SQLite database from Git-tracked JSON files")
    add_cmd("stats", "Show ULTRON Core & Hive statistics")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        core = UltronCore(repo_root=args.root, db_path=args.db)
        cmd = args.command

        if cmd == "register-prime":
            res = core.register_prime(args.id)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(f"[ULTRON] Registered {PRIME_ID} -> {res['conversation_id']} (status=active)")

        elif cmd == "org-tree":
            if args.json:
                print(
                    json.dumps(
                        {"prime": core.get_agent(PRIME_ID), "teams": core.list_teams()},
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(format_org_tree(core))

        elif cmd == "create-team":
            res = core.create_team(
                slug=args.slug,
                name=args.name,
                mission=args.mission,
                parent_team=args.parent,
                default_model=args.model,
                workspace_mode=args.workspace,
                lead_responsibilities=args.lead_responsibilities,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Created Team '{res['slug']}' (Layer {res['layer']}) at {res['hive_path']} "
                    f"with role '{res['slug']}/lead' [status=disabled]"
                )

        elif cmd == "add-role":
            res = core.add_role(
                team_slug=args.team,
                role=args.role,
                title=args.title,
                responsibilities=args.responsibilities,
                model=args.model,
                write_tools=not args.read_only,
                mcp_tools=not args.no_mcp,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Added Role '{res['agent_id']}' ({res['title']}) at {res['role_path']} "
                    f"[model={res['model']}, write={res['write_tools']}, status=disabled]"
                )

        elif cmd == "teams":
            res = core.list_teams(status=args.status)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            elif not res:
                print("[ULTRON] No teams registered.")
            else:
                for t in res:
                    print(
                        f"[L{t['layer']}] {t['slug']:<20} status={t['status']:<10} "
                        f"parent={t['parent_team'] or PRIME_ID:<16} path={t['hive_path']}"
                    )

        elif cmd == "team-info":
            res = core.get_team(args.slug)
            if not res:
                print(f"[ULTRON Error] Team '{args.slug}' not found.", file=sys.stderr)
                return 1
            print(json.dumps(res, indent=2, sort_keys=True))

        elif cmd in ("render-spawn", "prepare-spawn"):
            specs = core.render_spawn(team_slug=args.team, role=args.role, mission_brief=args.brief)
            if args.json:
                print(json.dumps(specs, indent=2, sort_keys=True))
            else:
                for s in specs:
                    print("=" * 80)
                    print(f"SPAWN SPEC FOR: {s['agent_id']} (TypeName={s['define_subagent']['Name']})")
                    print(
                        f"  Model={s['invoke_subagent']['Model']} | "
                        f"Workspace={s['invoke_subagent']['Workspace']} | "
                        f"Write={s['define_subagent']['EnableWriteTools']} | "
                        f"Subagents={s['define_subagent']['EnableSubagentTools']}"
                    )
                    print("-" * 80)
                    print(s["define_subagent"]["SystemPrompt"])

        elif cmd == "activate-team":
            try:
                uuid_map = json.loads(args.uuids)
                if not isinstance(uuid_map, dict):
                    raise ValueError("--uuids must decode to a JSON object.")
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON passed to --uuids: {exc}") from exc

            res = core.activate_team(
                team_slug=args.team,
                role_uuids=uuid_map,
                allow_detached=args.allow_detached,
                partial=args.partial,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                active_list = [
                    f"{r['agent_id']}={r['conversation_id']}"
                    for r in res["roles"]
                    if r["status"] == "active"
                ]
                print(f"[ULTRON] Activated Team '{res['slug']}': {', '.join(active_list)}")

        elif cmd == "activate-agent":
            res = core.activate_agent(
                agent_id=args.agent_id,
                conversation_id=args.id,
                allow_detached=args.allow_detached,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(f"[ULTRON] Activated '{res['agent_id']}' -> {res['conversation_id']}")

        elif cmd == "prepare-disable":
            res = core.prepare_disable(team_slug=args.team, cascade=args.cascade)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(f"[ULTRON] Teams to disable: {res['teams_affected']}")
                print(f"[ULTRON] ConversationIds to kill ({len(res['conversation_ids_to_kill'])}):")
                for cid in res["conversation_ids_to_kill"]:
                    print(f"  {cid}")

        elif cmd == "disable-team":
            res = core.disable_team(team_slug=args.team, cascade=args.cascade)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Disabled team(s) {res['teams_affected']} "
                    f"(cleared {len(res['conversation_ids_to_kill'])} live UUID(s); Hive files & board threads preserved)."
                )

        elif cmd == "disable-agent":
            res = core.disable_agent(args.agent_id)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Disabled '{res['agent_id']}' (previous UUID: {res['previous_conversation_id'] or 'none'})."
                )

        elif cmd == "remove-team":
            res = core.remove_team(
                team_slug=args.team,
                cascade=args.cascade,
                delete_files=args.delete_files,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(f"[ULTRON] Removed team(s): {res['removed_teams']}")

        elif cmd == "agents":
            res = core.list_agents(team_slug=args.team, status=args.status)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(format_agent_table(res))

        elif cmd == "whois":
            agent = core.get_agent(args.agent_id)
            if not agent:
                print(f"[ULTRON Error] Agent '{args.agent_id}' is not registered.", file=sys.stderr)
                return 1
            if agent["status"] != "active" or not agent["conversation_id"]:
                print(
                    f"[ULTRON Error] Agent '{agent['agent_id']}' is currently DISABLED (no live session UUID).",
                    file=sys.stderr,
                )
                return 1
            if args.id_only:
                print(agent["conversation_id"])
            elif args.json:
                print(json.dumps(agent, indent=2, sort_keys=True))
            else:
                print(f"[ULTRON] Agent: {agent['agent_id']}")
                print(f"  Title:           {agent['title']}")
                print(f"  Status:          {agent['status']}")
                print(f"  Model:           {agent['model']}")
                print(f"  Conversation ID: {agent['conversation_id']}")
                print(f"  Role Path:       {agent['role_path']}")

        elif cmd == "contacts":
            res = core.get_contacts(args.agent_id)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(json.dumps(res, indent=2, sort_keys=True))

        elif cmd == "new-thread":
            res = core.create_thread(
                title=args.title,
                author=args.author,
                content=args.content,
                category=args.category,
                visibility=args.visibility,
                team_slug=args.team,
                with_team=args.with_team,
                tags=args.tags,
                author_id=args.author_id,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Created Thread #{res['thread_id']} [{format_scope_badge(res)}]: "
                    f"'{res['title']}' (Post #{res['post_id']})"
                )

        elif cmd == "reply":
            res = core.add_post(
                thread_id=args.thread_id,
                author=args.author,
                content=args.content,
                parent_post_id=args.reply_to,
                tags=args.tags,
                author_id=args.author_id,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Added Post #{res['post_id']} to Thread #{res['thread_id']} by @{res['author']}"
                )

        elif cmd == "list":
            threads = core.list_threads(
                as_agent=args.as_agent,
                show_all=args.show_all,
                visibility=args.visibility,
                team_slug=args.team,
                category=args.category,
                status=args.status,
                limit=args.limit,
            )
            if args.json:
                print(json.dumps(threads, indent=2, sort_keys=True))
            elif not threads:
                print("[ULTRON] No visible threads matched criteria.")
            else:
                print(f"[ULTRON] Visible Threads ({len(threads)}):\n")
                header = f"{'ID':<5} {'SCOPE':<24} {'CAT':<12} {'STATUS':<12} {'POSTS':<6} {'AUTHOR':<18} {'TITLE'}"
                print(header)
                print("-" * 105)
                for t in threads:
                    print(
                        f"#{t['id']:<4} {format_scope_badge(t):<24} {t['category']:<12} "
                        f"{t['status']:<12} {t['post_count']:<6} {t['author']:<18} {t['title']}"
                    )

        elif cmd == "view":
            thread = core.get_thread(
                thread_id=args.thread_id,
                as_agent=args.as_agent,
                show_all=args.show_all,
            )
            if not thread:
                print(f"[ULTRON Error] Thread #{args.thread_id} not found.", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(thread, indent=2, sort_keys=True))
            else:
                print(format_thread_view(thread))

        elif cmd == "search":
            results = core.search(
                query_str=args.query,
                as_agent=args.as_agent,
                show_all=args.show_all,
                visibility=args.visibility,
                team_slug=args.team,
                limit=args.limit,
            )
            if args.json:
                print(json.dumps(results, indent=2, sort_keys=True))
            elif not results:
                print(f"[ULTRON] No visible posts matched query: '{args.query}'")
            else:
                print(f"[ULTRON] Found {len(results)} matching post(s) for '{args.query}':\n")
                for r in results:
                    snippet = r["content"][:140] + ("..." if len(r["content"]) > 140 else "")
                    print(
                        f"[Post #{r['post_id']} in Thread #{r['thread_id']} "
                        f"({format_scope_badge(r)}) '{r['thread_title']}' by @{r['author']}]"
                    )
                    print(f"  {snippet}\n")

        elif cmd in ("set-status", "status"):
            has_identity = bool(args.as_agent or os.environ.get("ULTRON_AGENT_ID") or args.show_all)
            if not has_identity:
                raise PermissionError(
                    "Caller identity required: pass --as <agent_id> (or set ULTRON_AGENT_ID), or --all."
                )
            ok = core.set_thread_status(
                thread_id=args.thread_id,
                status=args.status,
                as_agent=args.as_agent,
                show_all=args.show_all,
            )
            if not ok:
                print(f"[ULTRON Error] Thread #{args.thread_id} not found.", file=sys.stderr)
                return 1
            print(f"[ULTRON] Thread #{args.thread_id} status updated to '{args.status}'.")

        elif cmd == "reclassify":
            res = core.reclassify_thread(
                thread_id=args.thread_id,
                visibility=args.visibility,
                team_slug=args.team,
                with_team=args.with_team,
                owner_agent=args.owner,
                as_agent=args.as_agent,
                show_all=args.show_all,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Reclassified Thread #{res['id']} -> [{format_scope_badge(res)}]"
                )

        elif cmd == "backup":
            res = core.export_all()
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Exported {res['teams']} team(s), {res['agents']} agent(s), "
                    f"and {res['threads']} thread(s) to Git-tracked JSON."
                )

        elif cmd == "restore":
            res = core.restore()
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Restored {res['teams']} team(s), {res['agents']} agent(s), "
                    f"and {res['threads']} thread(s) from Git-tracked JSON."
                )

        elif cmd == "stats":
            stats = core.get_stats()
            if args.json:
                print(json.dumps(stats, indent=2, sort_keys=True))
            else:
                print("[ULTRON] System Statistics:")
                print(f"  Repo Root:        {stats['repo_root']}")
                print(f"  Database Path:    {stats['db_path']}")
                print(f"  Hive Directory:   {stats['hive_dir']}")
                print(f"  Teams:            {stats['active_teams']} active / {stats['total_teams']} total")
                print(f"  Agents / Roles:   {stats['active_agents']} active / {stats['total_agents']} total")
                print(f"  Threads:          {stats['total_threads']} (Visibilities: {stats['visibilities']})")
                print(f"  Posts:            {stats['total_posts']}")

        return 0

    except (ValueError, PermissionError, FileNotFoundError, RuntimeError) as exc:
        print(f"[ULTRON Error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
