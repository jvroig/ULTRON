#!/usr/bin/env python3
"""
AgentBoard: Persistent SQLite-backed bulletin board & shared forum for autonomous agents.
Enables cross-agent knowledge sharing, architecture records, bug tracking, and telemetry.
Includes Git-friendly JSON text file backup/restore and automatic thread persistence.
"""

import os
import sys
import glob
import json
import sqlite3
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional

DEFAULT_DB_PATH = os.environ.get(
    "AGENT_BOARD_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "board.db")
)

DEFAULT_THREADS_DIR = os.environ.get(
    "AGENT_BOARD_THREADS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "threads")
)

DEFAULT_AGENTS_FILE = os.environ.get(
    "AGENT_BOARD_AGENTS_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents.json")
)

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    status TEXT NOT NULL DEFAULT 'open',
    author TEXT NOT NULL,
    author_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    parent_post_id INTEGER REFERENCES posts(id),
    author TEXT NOT NULL,
    author_id TEXT,
    content TEXT NOT NULL,
    tags TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    last_seen TEXT NOT NULL,
    registered_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_threads_category ON threads(category);
CREATE INDEX IF NOT EXISTS idx_threads_status ON threads(status);
CREATE INDEX IF NOT EXISTS idx_posts_thread ON posts(thread_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

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

class AgentBoard:
    def __init__(
        self,
        db_path: Optional[str] = None,
        threads_dir: Optional[str] = None,
        agents_file: Optional[str] = None
    ):
        self.db_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
        self.threads_dir = os.path.abspath(threads_dir or DEFAULT_THREADS_DIR)
        self.agents_file = os.path.abspath(agents_file or DEFAULT_AGENTS_FILE)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.threads_dir, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_db(self) -> None:
        db_existed = os.path.exists(self.db_path)
        db_mtime = os.path.getmtime(self.db_path) if db_existed else 0.0
        with self._get_connection() as conn:
            conn.executescript(SCHEMA)
            cursor = conn.cursor()

            # Auto-restore/sync agents if table is empty or agents.json is newer than board.db
            cursor.execute("SELECT COUNT(*) FROM agents")
            agent_count = cursor.fetchone()[0]
            if os.path.isfile(self.agents_file):
                agents_mtime = os.path.getmtime(self.agents_file)
                if agent_count == 0 or agents_mtime > db_mtime:
                    self._restore_agents_from_file(self.agents_file, conn)

            # Auto-restore/sync threads if table is empty, file count differs, or any thread JSON is newer
            cursor.execute("SELECT COUNT(*) FROM threads")
            count = cursor.fetchone()[0]
            if os.path.isdir(self.threads_dir):
                backup_files = glob.glob(os.path.join(self.threads_dir, "thread_*.json"))
                if backup_files:
                    newest_thread_mtime = max(os.path.getmtime(f) for f in backup_files)
                    if count < len(backup_files) or newest_thread_mtime > db_mtime:
                        self._restore_from_dir(self.threads_dir, conn)

    def _resolve_author_id_and_touch(self, conn: sqlite3.Connection, author: str, author_id: str, iso_time: str) -> str:
        resolved_id = author_id.strip()
        row = conn.execute(
            "SELECT conversation_id FROM agents WHERE name = ? COLLATE NOCASE",
            (author.strip(),)
        ).fetchone()
        if row:
            if not resolved_id:
                resolved_id = row["conversation_id"]
            conn.execute(
                "UPDATE agents SET last_seen = ? WHERE name = ? COLLATE NOCASE",
                (iso_time, author.strip())
            )
        return resolved_id

    def create_thread(
        self,
        title: str,
        category: str,
        author: str,
        content: str,
        tags: str = "",
        author_id: str = "",
        auto_backup: bool = True
    ) -> Dict[str, Any]:
        iso_time = now_iso()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            resolved_author_id = self._resolve_author_id_and_touch(conn, author, author_id, iso_time)
            cursor.execute(
                """
                INSERT INTO threads (title, category, status, author, author_id, created_at, updated_at)
                VALUES (?, ?, 'open', ?, ?, ?, ?)
                """,
                (title.strip(), category.strip().lower(), author.strip(), resolved_author_id, iso_time, iso_time)
            )
            thread_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO posts (thread_id, parent_post_id, author, author_id, content, tags, created_at)
                VALUES (?, NULL, ?, ?, ?, ?, ?)
                """,
                (thread_id, author.strip(), resolved_author_id, content.strip(), tags.strip(), iso_time)
            )
            post_id = cursor.lastrowid

        if auto_backup:
            self.export_thread(thread_id)

        return {
            "thread_id": thread_id,
            "post_id": post_id,
            "title": title,
            "category": category,
            "author": author,
            "author_id": resolved_author_id,
            "created_at": iso_time
        }

    def add_post(
        self,
        thread_id: int,
        author: str,
        content: str,
        parent_post_id: Optional[int] = None,
        tags: str = "",
        author_id: str = "",
        auto_backup: bool = True
    ) -> Dict[str, Any]:
        iso_time = now_iso()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM threads WHERE id = ?", (thread_id,))
            if not cursor.fetchone():
                raise ValueError(f"Thread #{thread_id} does not exist.")

            resolved_author_id = self._resolve_author_id_and_touch(conn, author, author_id, iso_time)

            cursor.execute(
                """
                INSERT INTO posts (thread_id, parent_post_id, author, author_id, content, tags, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (thread_id, parent_post_id, author.strip(), resolved_author_id, content.strip(), tags.strip(), iso_time)
            )
            post_id = cursor.lastrowid

            cursor.execute(
                "UPDATE threads SET updated_at = ? WHERE id = ?",
                (iso_time, thread_id)
            )

        if auto_backup:
            self.export_thread(thread_id)

        return {
            "thread_id": thread_id,
            "post_id": post_id,
            "author": author,
            "author_id": resolved_author_id,
            "created_at": iso_time
        }

    def list_threads(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 25
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT t.id, t.title, t.category, t.status, t.author, t.created_at, t.updated_at,
                   COUNT(p.id) AS post_count
            FROM threads t
            LEFT JOIN posts p ON t.id = p.thread_id
            WHERE 1=1
        """
        params: List[Any] = []
        if category:
            query += " AND t.category = ?"
            params.append(category.strip().lower())
        if status:
            query += " AND t.status = ?"
            params.append(status.strip().lower())

        query += " GROUP BY t.id ORDER BY t.updated_at DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_thread(self, thread_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            t_row = conn.execute(
                "SELECT * FROM threads WHERE id = ?", (thread_id,)
            ).fetchone()
            if not t_row:
                return None

            thread_dict = dict(t_row)
            p_rows = conn.execute(
                "SELECT * FROM posts WHERE thread_id = ? ORDER BY created_at ASC",
                (thread_id,)
            ).fetchall()
            thread_dict["posts"] = [dict(r) for r in p_rows]
            return thread_dict

    def search(self, query_str: str, limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            sql = """
                SELECT p.id AS post_id, p.thread_id, t.title AS thread_title, t.category,
                       p.author, p.content, p.tags, p.created_at
                FROM posts_fts fts
                JOIN posts p ON fts.rowid = p.id
                JOIN threads t ON p.thread_id = t.id
                WHERE posts_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """
            try:
                rows = conn.execute(sql, (query_str, limit)).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.OperationalError:
                like_sql = """
                    SELECT p.id AS post_id, p.thread_id, t.title AS thread_title, t.category,
                           p.author, p.content, p.tags, p.created_at
                    FROM posts p
                    JOIN threads t ON p.thread_id = t.id
                    WHERE p.content LIKE ? OR p.tags LIKE ? OR t.title LIKE ?
                    ORDER BY p.created_at DESC
                    LIMIT ?
                """
                like_pat = f"%{query_str}%"
                rows = conn.execute(like_sql, (like_pat, like_pat, like_pat, limit)).fetchall()
                return [dict(r) for r in rows]

    def set_thread_status(self, thread_id: int, status: str, auto_backup: bool = True) -> bool:
        valid_statuses = {"open", "in_progress", "resolved", "blocked", "closed"}
        st = status.strip().lower()
        if st not in valid_statuses:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {sorted(valid_statuses)}")

        iso_time = now_iso()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE threads SET status = ?, updated_at = ? WHERE id = ?",
                (st, iso_time, thread_id)
            )
            success = cursor.rowcount > 0

        if success and auto_backup:
            self.export_thread(thread_id)

        return success

    def export_thread(self, thread_id: int, out_dir: Optional[str] = None) -> str:
        target_dir = os.path.abspath(out_dir or self.threads_dir)
        os.makedirs(target_dir, exist_ok=True)
        thread = self.get_thread(thread_id)
        if not thread:
            raise ValueError(f"Thread #{thread_id} not found.")

        file_name = f"thread_{thread_id:04d}.json"
        file_path = os.path.join(target_dir, file_name)
        tmp_path = f"{file_path}.tmp.{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(thread, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, file_path)
        return file_path

    def register_agent(
        self,
        name: str,
        conversation_id: str,
        role: str = "",
        status: str = "active",
        auto_backup: bool = True
    ) -> Dict[str, Any]:
        iso_time = now_iso()
        valid_statuses = {"active", "idle", "busy", "retired"}
        st = status.strip().lower()
        if st not in valid_statuses:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {sorted(valid_statuses)}")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO agents (name, conversation_id, role, status, last_seen, registered_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    conversation_id = excluded.conversation_id,
                    role = CASE WHEN excluded.role != '' THEN excluded.role ELSE agents.role END,
                    status = excluded.status,
                    last_seen = excluded.last_seen
                """,
                (name.strip(), conversation_id.strip(), role.strip(), st, iso_time, iso_time)
            )

        if auto_backup:
            self.export_agents()

        agent = self.get_agent(name)
        return agent or {}

    def get_agent(self, name: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM agents WHERE name = ? COLLATE NOCASE", (name.strip(),)).fetchone()
            return dict(row) if row else None

    def list_agents(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM agents"
        params: List[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status.strip().lower())
        query += " ORDER BY name COLLATE NOCASE ASC"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def export_agents(self, out_file: Optional[str] = None) -> str:
        target_file = os.path.abspath(out_file or self.agents_file)
        os.makedirs(os.path.dirname(target_file), exist_ok=True)
        agents = self.list_agents(status=None)
        tmp_path = f"{target_file}.tmp.{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(agents, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, target_file)
        return target_file

    def restore_agents(self, in_file: Optional[str] = None) -> int:
        target_file = os.path.abspath(in_file or self.agents_file)
        with self._get_connection() as conn:
            return self._restore_agents_from_file(target_file, conn)

    def _restore_agents_from_file(self, target_file: str, conn: sqlite3.Connection) -> int:
        if not os.path.isfile(target_file):
            return 0
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                agents = json.load(f)
            cursor = conn.cursor()
            for a in agents:
                cursor.execute(
                    """
                    INSERT INTO agents (name, conversation_id, role, status, last_seen, registered_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        conversation_id = excluded.conversation_id,
                        role = excluded.role,
                        status = excluded.status,
                        last_seen = excluded.last_seen,
                        registered_at = excluded.registered_at
                    """,
                    (
                        a["name"].strip(),
                        a["conversation_id"].strip(),
                        a.get("role", "").strip(),
                        a.get("status", "active").strip().lower(),
                        a.get("last_seen", now_iso()),
                        a.get("registered_at", now_iso())
                    )
                )
            return len(agents)
        except Exception as ex:
            print(f"[AgentBoard Warning] Error loading agents file {target_file}: {ex}", file=sys.stderr)
            return 0

    def export_all(self, out_dir: Optional[str] = None, agents_file: Optional[str] = None) -> Dict[str, int]:
        target_dir = os.path.abspath(out_dir or self.threads_dir)
        os.makedirs(target_dir, exist_ok=True)
        threads = self.list_threads(limit=10000)
        for t in threads:
            self.export_thread(t["id"], target_dir)
        agents_count = len(self.list_agents())
        self.export_agents(agents_file)
        return {"threads": len(threads), "agents": agents_count}

    def restore(self, in_dir: Optional[str] = None, agents_file: Optional[str] = None) -> Dict[str, int]:
        target_dir = os.path.abspath(in_dir or self.threads_dir)
        target_agents = os.path.abspath(agents_file or self.agents_file)
        with self._get_connection() as conn:
            t_count = self._restore_from_dir(target_dir, conn)
            a_count = self._restore_agents_from_file(target_agents, conn)
            return {"threads": t_count, "agents": a_count}

    def _restore_from_dir(self, target_dir: str, conn: sqlite3.Connection) -> int:
        pattern = os.path.join(target_dir, "thread_*.json")
        files = sorted(glob.glob(pattern))
        if not files:
            return 0

        cursor = conn.cursor()
        for fpath in files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    t_data = json.load(f)

                t_id = t_data["id"]
                title = t_data["title"]
                category = t_data.get("category", "general")
                status = t_data.get("status", "open")
                author = t_data.get("author", "Unknown")
                author_id = t_data.get("author_id", "")
                created_at = t_data.get("created_at", now_iso())
                updated_at = t_data.get("updated_at", created_at)

                # Upsert thread
                cursor.execute(
                    """
                    INSERT INTO threads (id, title, category, status, author, author_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        category = excluded.category,
                        status = excluded.status,
                        author = excluded.author,
                        author_id = excluded.author_id,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at
                    """,
                    (t_id, title, category, status, author, author_id, created_at, updated_at)
                )

                # Upsert posts
                for p in t_data.get("posts", []):
                    p_id = p["id"]
                    parent_id = p.get("parent_post_id")
                    p_author = p.get("author", "Unknown")
                    p_author_id = p.get("author_id", "")
                    content = p.get("content", "")
                    tags = p.get("tags", "")
                    p_created_at = p.get("created_at", created_at)

                    cursor.execute(
                        """
                        INSERT INTO posts (id, thread_id, parent_post_id, author, author_id, content, tags, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            parent_post_id = excluded.parent_post_id,
                            author = excluded.author,
                            author_id = excluded.author_id,
                            content = excluded.content,
                            tags = excluded.tags,
                            created_at = excluded.created_at
                        """,
                        (p_id, t_id, parent_id, p_author, p_author_id, content, tags, p_created_at)
                    )

            except Exception as ex:
                print(f"[AgentBoard Warning] Error loading {fpath}: {ex}", file=sys.stderr)

        # Rebuild FTS index
        try:
            cursor.execute("INSERT INTO posts_fts(posts_fts) VALUES('rebuild');")
        except Exception:
            pass

        return len(files)

    def get_stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            t_count = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
            p_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            a_count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            cats = conn.execute("SELECT category, COUNT(*) FROM threads GROUP BY category").fetchall()
            statuses = conn.execute("SELECT status, COUNT(*) FROM threads GROUP BY status").fetchall()
            backup_count = len(glob.glob(os.path.join(self.threads_dir, "thread_*.json")))
            has_agents_file = os.path.isfile(self.agents_file)
            return {
                "db_path": self.db_path,
                "threads_dir": self.threads_dir,
                "agents_file": self.agents_file,
                "git_backup_files": backup_count,
                "git_agents_file_exists": has_agents_file,
                "registered_agents": a_count,
                "total_threads": t_count,
                "total_posts": p_count,
                "categories": {r[0]: r[1] for r in cats},
                "statuses": {r[0]: r[1] for r in statuses}
            }


def format_agent_table(agents: List[Dict[str, Any]]) -> str:
    if not agents:
        return "[AgentBoard] No registered agents found in directory."
    lines = []
    lines.append(f"[AgentBoard] Registered Agents Directory ({len(agents)}):\n")
    header = f"{'NAME':<24} {'STATUS':<10} {'CONVERSATION ID (UUID)':<38} {'ROLE'}"
    lines.append(header)
    lines.append("-" * 102)
    for a in agents:
        lines.append(f"{a['name']:<24} {a['status']:<10} {a['conversation_id']:<38} {a['role']}")
    return "\n".join(lines)


def format_thread_view(thread: Dict[str, Any]) -> str:
    lines = []
    lines.append("=" * 80)
    lines.append(f"THREAD #{thread['id']}: {thread['title']}")
    lines.append(f"Category: [{thread['category'].upper()}] | Status: [{thread['status'].upper()}] | Started By: {thread['author']} ({thread['created_at'][:19]})")
    lines.append("=" * 80)

    for i, post in enumerate(thread.get("posts", [])):
        reply_info = f" (in reply to #{post['parent_post_id']})" if post.get('parent_post_id') else ""
        lines.append(f"\n--- Post #{post['id']} by @{post['author']}{reply_info} at {post['created_at'][:19]} ---")
        if post.get("tags"):
            lines.append(f"Tags: [{post['tags']}]")
        lines.append("")
        for line in post['content'].splitlines():
            lines.append(f"  {line}")

    lines.append("\n" + "=" * 80)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AgentBoard: Shared Forum & Persistent Knowledge Base for Autonomous Agents")
    parser.add_argument("--db", default=None, help="Custom database path")
    parser.add_argument("--threads-dir", default=None, help="Custom directory for Git thread JSON files")
    parser.add_argument("--agents-file", default=None, help="Custom path for Git agents JSON file")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # new-thread
    p_new = subparsers.add_parser("new-thread", help="Create a new thread with an initial post")
    p_new.add_argument("--title", required=True, help="Thread title")
    p_new.add_argument("--category", default="general", help="Category (architecture, bugfix, review, benchmark, etc.)")
    p_new.add_argument("--author", required=True, help="Author name/role (e.g. Designer, Executor)")
    p_new.add_argument("--content", "-m", required=True, help="Post content/body")
    p_new.add_argument("--tags", default="", help="Comma-separated tags")
    p_new.add_argument("--author-id", default="", help="Optional agent conversation ID")
    p_new.add_argument("--no-backup", action="store_true", help="Disable auto-exporting thread JSON file")

    # reply
    p_rep = subparsers.add_parser("reply", help="Reply to an existing thread")
    p_rep.add_argument("thread_id", type=int, help="Thread ID to reply to")
    p_rep.add_argument("--author", required=True, help="Author name/role")
    p_rep.add_argument("--content", "-m", required=True, help="Post content/body")
    p_rep.add_argument("--reply-to", type=int, default=None, help="Optional parent post ID")
    p_rep.add_argument("--tags", default="", help="Comma-separated tags")
    p_rep.add_argument("--author-id", default="", help="Optional agent conversation ID")
    p_rep.add_argument("--no-backup", action="store_true", help="Disable auto-exporting thread JSON file")

    # list
    p_list = subparsers.add_parser("list", help="List recent threads")
    p_list.add_argument("--category", default=None, help="Filter by category")
    p_list.add_argument("--status", default=None, help="Filter by status (open, resolved, blocked, closed)")
    p_list.add_argument("--limit", type=int, default=25, help="Max threads to return")

    # view
    p_view = subparsers.add_parser("view", help="View full thread and all replies")
    p_view.add_argument("thread_id", type=int, help="Thread ID to view")

    # search
    p_srch = subparsers.add_parser("search", help="Full-text search across all posts")
    p_srch.add_argument("query", help="FTS5 search query")
    p_srch.add_argument("--limit", type=int, default=20, help="Max results")

    # set-status
    p_stat = subparsers.add_parser("set-status", help="Update thread status")
    p_stat.add_argument("thread_id", type=int, help="Thread ID")
    p_stat.add_argument("status", choices=["open", "in_progress", "resolved", "blocked", "closed"], help="New status")
    p_stat.add_argument("--no-backup", action="store_true", help="Disable auto-exporting thread JSON file")

    # register
    p_reg = subparsers.add_parser("register", help="Register or update an agent in the directory")
    p_reg.add_argument("--name", required=True, help="Agent name/handle (e.g. Designer, Executor)")
    p_reg.add_argument("--id", required=True, help="Agent conversation UUID for send_message")
    p_reg.add_argument("--role", default="", help="Description of agent role/responsibilities")
    p_reg.add_argument("--status", choices=["active", "idle", "busy", "retired"], default="active", help="Agent status (default: active)")
    p_reg.add_argument("--no-backup", action="store_true", help="Disable auto-exporting agents JSON file")

    # agents
    p_ag = subparsers.add_parser("agents", help="List registered agents in the directory")
    p_ag.add_argument("--status", choices=["active", "idle", "busy", "retired"], default=None, help="Filter by status")

    # whois
    p_who = subparsers.add_parser("whois", help="Resolve agent name to conversation ID and details")
    p_who.add_argument("name", help="Agent name (e.g. Executor, Designer)")
    p_who.add_argument("--id-only", action="store_true", help="Print only the conversation UUID (useful for scripts)")

    # backup
    p_bak = subparsers.add_parser("backup", help="Export all threads and agents to Git-tracked JSON files")
    p_bak.add_argument("--dir", default=None, help="Target directory for backup files (default: agentboard/threads)")

    # restore
    p_res = subparsers.add_parser("restore", help="Restore or rebuild SQLite database from Git-tracked JSON files")
    p_res.add_argument("--dir", default=None, help="Source directory for thread files (default: agentboard/threads)")

    # stats
    subparsers.add_parser("stats", help="Show board statistics")

    args = parser.parse_args()
    board = AgentBoard(db_path=args.db, threads_dir=args.threads_dir, agents_file=args.agents_file)

    try:
        if args.command == "new-thread":
            res = board.create_thread(
                title=args.title,
                category=args.category,
                author=args.author,
                content=args.content,
                tags=args.tags,
                author_id=args.author_id,
                auto_backup=not args.no_backup
            )
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(f"[AgentBoard] Created Thread #{res['thread_id']}: '{res['title']}' (Post #{res['post_id']})")
                if not args.no_backup:
                    print(f"  -> Exported to Git-tracked backup: agentboard/threads/thread_{res['thread_id']:04d}.json")

        elif args.command == "reply":
            res = board.add_post(
                thread_id=args.thread_id,
                author=args.author,
                content=args.content,
                parent_post_id=args.reply_to,
                tags=args.tags,
                author_id=args.author_id,
                auto_backup=not args.no_backup
            )
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(f"[AgentBoard] Added Post #{res['post_id']} to Thread #{res['thread_id']} by @{res['author']}")
                if not args.no_backup:
                    print(f"  -> Updated Git-tracked backup: agentboard/threads/thread_{res['thread_id']:04d}.json")

        elif args.command == "list":
            threads = board.list_threads(category=args.category, status=args.status, limit=args.limit)
            if args.json:
                print(json.dumps(threads, indent=2))
            else:
                if not threads:
                    print("[AgentBoard] No threads found matching criteria.")
                else:
                    print(f"[AgentBoard] Found {len(threads)} thread(s):\n")
                    header = f"{'ID':<5} {'CAT':<14} {'STATUS':<12} {'POSTS':<6} {'AUTHOR':<14} {'TITLE'}"
                    print(header)
                    print("-" * 80)
                    for t in threads:
                        print(f"#{t['id']:<4} {t['category']:<14} {t['status']:<12} {t['post_count']:<6} {t['author']:<14} {t['title']}")

        elif args.command == "view":
            thread = board.get_thread(args.thread_id)
            if not thread:
                print(f"[AgentBoard] Thread #{args.thread_id} not found.", file=sys.stderr)
                sys.exit(1)
            if args.json:
                print(json.dumps(thread, indent=2))
            else:
                print(format_thread_view(thread))

        elif args.command == "search":
            results = board.search(args.query, limit=args.limit)
            if args.json:
                print(json.dumps(results, indent=2))
            else:
                if not results:
                    print(f"[AgentBoard] No posts matched query: '{args.query}'")
                else:
                    print(f"[AgentBoard] Found {len(results)} matching post(s) for '{args.query}':\n")
                    for r in results:
                        print(f"[Post #{r['post_id']} in Thread #{r['thread_id']} ('{r['thread_title']}') by @{r['author']}]")
                        snippet = r['content'][:140] + ("..." if len(r['content']) > 140 else "")
                        print(f"  {snippet}\n")

        elif args.command == "set-status":
            ok = board.set_thread_status(args.thread_id, args.status, auto_backup=not args.no_backup)
            if ok:
                print(f"[AgentBoard] Thread #{args.thread_id} status updated to '{args.status}'")
                if not args.no_backup:
                    print(f"  -> Updated Git-tracked backup: agentboard/threads/thread_{args.thread_id:04d}.json")
            else:
                print(f"[AgentBoard] Thread #{args.thread_id} not found.", file=sys.stderr)
                sys.exit(1)

        elif args.command == "register":
            agent = board.register_agent(
                name=args.name,
                conversation_id=args.id,
                role=args.role,
                status=args.status,
                auto_backup=not args.no_backup
            )
            if args.json:
                print(json.dumps(agent, indent=2))
            else:
                print(f"[AgentBoard] Registered Agent '@{agent['name']}':")
                print(f"  Conversation ID: {agent['conversation_id']}")
                print(f"  Role:            {agent['role']}")
                print(f"  Status:          {agent['status']}")
                if not args.no_backup:
                    print(f"  -> Exported to Git-tracked directory: {board.agents_file}")

        elif args.command == "agents":
            agents = board.list_agents(status=args.status)
            if args.json:
                print(json.dumps(agents, indent=2))
            else:
                print(format_agent_table(agents))

        elif args.command == "whois":
            agent = board.get_agent(args.name)
            if not agent:
                print(f"[AgentBoard] Agent '{args.name}' not found in directory.", file=sys.stderr)
                sys.exit(1)
            if args.id_only:
                print(agent["conversation_id"])
            elif args.json:
                print(json.dumps(agent, indent=2))
            else:
                print(f"[AgentBoard] Agent: {agent['name']}")
                print(f"  Conversation ID: {agent['conversation_id']}")
                print(f"  Role:            {agent['role']}")
                print(f"  Status:          {agent['status']}")
                print(f"  Last Seen:       {agent['last_seen']}")
                print(f"  Registered:      {agent['registered_at']}")

        elif args.command == "backup":
            res = board.export_all(out_dir=args.dir)
            target = args.dir or board.threads_dir
            print(f"[AgentBoard] Successfully exported {res['threads']} thread(s) into {target}")
            print(f"[AgentBoard] Successfully exported {res['agents']} agent(s) into {board.agents_file}")

        elif args.command == "restore":
            res = board.restore(in_dir=args.dir)
            src = args.dir or board.threads_dir
            print(f"[AgentBoard] Successfully restored {res['threads']} thread(s) from {src} into {board.db_path}")
            print(f"[AgentBoard] Successfully restored {res['agents']} agent(s) from {board.agents_file} into {board.db_path}")

        elif args.command == "stats":
            stats = board.get_stats()
            if args.json:
                print(json.dumps(stats, indent=2))
            else:
                print("[AgentBoard] Statistics:")
                print(f"  Database Path:      {stats['db_path']}")
                print(f"  Threads Directory:  {stats['threads_dir']}")
                print(f"  Agents File:        {stats['agents_file']}")
                print(f"  Git Backup Files:   {stats['git_backup_files']}")
                print(f"  Git Agents Exists:  {stats['git_agents_file_exists']}")
                print(f"  Registered Agents:  {stats['registered_agents']}")
                print(f"  Total Threads:      {stats['total_threads']}")
                print(f"  Total Posts:        {stats['total_posts']}")
                print(f"  Categories:         {stats['categories']}")
                print(f"  Statuses:           {stats['statuses']}")

    except Exception as e:
        print(f"[AgentBoard Error] {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
