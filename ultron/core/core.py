#!/usr/bin/env python3
"""
ULTRON Core (ultron/core/core.py)
Pure Git-native org registry, N-layer Hive team/role scaffolder, lifecycle coordinator,
and append-only JSONL message board for ULTRON (Universal Layered Team & Role Orchestration Network).

Storage Architecture (Zero SQLite / Zero External Dependencies):
- Org & Role Definitions (Git-tracked):
    ultron/hive/.../<team-slug>/team.json
    ultron/hive/.../<team-slug>/roles/<role-slug>/role.json
- Live Session UUID Bindings (Gitignored ephemeral runtime state):
    ultron/core/.runtime/sessions.json
- Message Board Threads (Git-tracked, conflict-free via *.jsonl merge=union):
    ultron/core/threads/<thread_id>.jsonl  (1 append-only JSON event per line)
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Dict, Iterator, List, Mapping, Optional, Set, Tuple

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

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


def now_iso() -> str:
    """UTC ISO-8601 timestamp with microsecond precision for deterministic event ordering."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_thread_id() -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"t-{day}-{os.urandom(4).hex()}"


def generate_post_id() -> str:
    return f"p-{os.urandom(4).hex()}"


def generate_event_id() -> str:
    return f"e-{os.urandom(6).hex()}"


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
    tmp_path = target_path.with_name(
        f".{target_path.name}.tmp.{os.getpid()}.{os.urandom(3).hex()}"
    )
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def append_jsonl_event(target_path: Path, event: Mapping[str, Any]) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with open(target_path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


class UltronCore:
    def __init__(
        self,
        repo_root: Optional[Path | str] = None,
        hive_dir: Optional[Path | str] = None,
        threads_dir: Optional[Path | str] = None,
        runtime_dir: Optional[Path | str] = None,
        templates_dir: Optional[Path | str] = None,
    ) -> None:
        env_root = os.environ.get("ULTRON_REPO_ROOT")
        self.repo_root = Path(repo_root or env_root or DEFAULT_REPO_ROOT).resolve()
        default_core = self.repo_root / "ultron" / "core"
        default_hive = self.repo_root / "ultron" / "hive"

        self.hive_dir = Path(
            hive_dir or os.environ.get("ULTRON_HIVE_DIR") or default_hive
        ).resolve()
        self.threads_dir = Path(
            threads_dir or os.environ.get("ULTRON_THREADS_DIR") or (default_core / "threads")
        ).resolve()
        self.runtime_dir = Path(
            runtime_dir or os.environ.get("ULTRON_RUNTIME_DIR") or (default_core / ".runtime")
        ).resolve()
        self.sessions_file = self.runtime_dir / "sessions.json"
        self.lock_file = self.runtime_dir / ".lock"
        self.templates_dir = Path(templates_dir or TEMPLATES_DIR).resolve()

        self.hive_dir.mkdir(parents=True, exist_ok=True)
        self.threads_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        # Ensure threads/.gitattributes exists so *.jsonl merges union-style automatically
        gitattr = self.threads_dir / ".gitattributes"
        if not gitattr.exists():
            gitattr.write_text(
                "# Union-merge append-only JSONL thread logs across Git branches without conflict\n"
                "*.jsonl merge=union\n",
                encoding="utf-8",
            )

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

    def _resolve_target_repo(self, raw_target: str) -> str:
        """Resolve an optional external target repository path (~, relative, or absolute) to an absolute path string."""
        cleaned = (raw_target or "").strip()
        if not cleaned:
            return ""
        expanded = Path(cleaned).expanduser()
        if expanded.is_absolute():
            return str(expanded.resolve())
        return str((self.repo_root / expanded).resolve())

    def _load_template(self, filename: str) -> str:
        tpath = self.templates_dir / filename
        if not tpath.is_file():
            raise FileNotFoundError(f"Missing ULTRON template file: {tpath}")
        return tpath.read_text(encoding="utf-8")

    @contextmanager
    def _lock(self, exclusive: bool = True) -> Iterator[None]:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        with open(self.lock_file, "a+", encoding="utf-8") as lf:
            if fcntl is not None:
                mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(lf.fileno(), mode)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    # ------------------------------------------------------------------
    # Ephemeral Runtime Session State (.runtime/sessions.json)
    # ------------------------------------------------------------------

    def _read_sessions_unlocked(self) -> Dict[str, Dict[str, Any]]:
        if not self.sessions_file.is_file():
            return {"agents": {}}
        try:
            raw = json.loads(self.sessions_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Corrupt runtime session file '{self.sessions_file}': {exc}"
            ) from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("agents", {}), dict):
            raise ValueError(f"Invalid schema in '{self.sessions_file}'.")
        return {"agents": dict(raw.get("agents", {}))}

    def _write_sessions_unlocked(self, sessions: Mapping[str, Any]) -> None:
        atomic_write_json(self.sessions_file, {"agents": dict(sessions.get("agents", {}))})

    # ------------------------------------------------------------------
    # Recursive N-Layer Hive Discovery (team.json & role.json)
    # ------------------------------------------------------------------

    def _scan_state_unlocked(
        self,
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """
        Walk ultron/hive/ recursively to load all persistent teams and roles,
        and overlay ephemeral session UUIDs/statuses from .runtime/sessions.json.
        Returns (teams_by_slug, agents_by_id, sessions_data).
        """
        sessions = self._read_sessions_unlocked()
        live_agents = sessions["agents"]

        teams_by_slug: Dict[str, Dict[str, Any]] = {}
        agents_by_id: Dict[str, Dict[str, Any]] = {}

        # Include ULTRON PRIME if registered in runtime sessions
        if PRIME_ID in live_agents:
            p_sess = live_agents[PRIME_ID]
            cid = str(p_sess.get("conversation_id", "")).strip()
            p_status = "active" if cid and p_sess.get("status") == "active" else "disabled"
            reg_at = str(p_sess.get("registered_at") or now_iso())
            seen_at = str(p_sess.get("last_seen") or reg_at)
            agents_by_id[PRIME_ID] = {
                "agent_id": PRIME_ID,
                "conversation_id": cid if p_status == "active" else "",
                "last_seen": seen_at,
                "mcp_tools": True,
                "model": "inherit",
                "registered_at": reg_at,
                "responsibilities": "Ultimate Leader of Teams, Roles, and Operational Nodes",
                "role": "prime",
                "role_path": "ultron/core",
                "status": p_status,
                "target_repo": "",
                "target_repo_abs": "",
                "team_slug": None,
                "title": "ULTRON PRIME",
                "write_tools": True,
            }

        def walk_team_dir(team_dir: Path, expected_parent: Optional[str], lineage: List[str]) -> None:
            t_manifest = team_dir / "team.json"
            if not t_manifest.is_file():
                return
            try:
                raw_t = json.loads(t_manifest.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Corrupt JSON in '{t_manifest}': {exc}") from exc

            slug = validate_slug(str(raw_t.get("slug", "")), "team slug")
            if slug != team_dir.name:
                raise ValueError(
                    f"Team directory '{team_dir.name}' mismatches team.json slug '{slug}'."
                )
            if slug in teams_by_slug:
                raise ValueError(
                    f"Duplicate team slug '{slug}' detected across Hive ('{t_manifest}')."
                )

            stored_parent = (raw_t.get("parent_team") or "").strip().lower() or None
            if stored_parent != expected_parent:
                raise ValueError(
                    f"Team '{slug}' parent_team '{stored_parent}' mismatches directory parent '{expected_parent}'."
                )

            model = str(raw_t.get("default_model", "flash")).strip().lower()
            if model not in VALID_MODELS:
                raise ValueError(f"Invalid default_model '{model}' in '{t_manifest}'.")
            ws = str(raw_t.get("workspace_mode", "inherit")).strip().lower()
            if ws not in VALID_WORKSPACES:
                raise ValueError(f"Invalid workspace_mode '{ws}' in '{t_manifest}'.")

            curr_lineage = [*lineage, slug]
            hive_rel = self._rel_posix(team_dir)
            created_at = str(raw_t.get("created_at") or now_iso())
            updated_at = str(raw_t.get("updated_at") or created_at)
            inherited_target_repo = (
                teams_by_slug[expected_parent]["target_repo"]
                if expected_parent and expected_parent in teams_by_slug
                else ""
            )
            team_target_repo = (
                str(raw_t.get("target_repo", "")).strip() or inherited_target_repo
            )
            team_target_repo_abs = self._resolve_target_repo(team_target_repo)

            # Load flat intra-team roles under roles/*/role.json
            roles_root = team_dir / "roles"
            team_roles: List[Dict[str, Any]] = []
            if roles_root.is_dir():
                for role_dir in sorted(roles_root.iterdir()):
                    if not role_dir.is_dir() or role_dir.name.startswith("."):
                        continue
                    r_manifest = role_dir / "role.json"
                    if not r_manifest.is_file():
                        continue
                    try:
                        raw_r = json.loads(r_manifest.read_text(encoding="utf-8"))
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"Corrupt JSON in '{r_manifest}': {exc}") from exc

                    r_slug = validate_role_slug(str(raw_r.get("role", role_dir.name)))
                    if r_slug != role_dir.name:
                        raise ValueError(
                            f"Role directory '{role_dir.name}' mismatches role.json role '{r_slug}'."
                        )
                    aid = f"{slug}/{r_slug}"
                    r_model = str(raw_r.get("model", model)).strip().lower()
                    if r_model not in VALID_MODELS:
                        raise ValueError(f"Invalid model '{r_model}' in '{r_manifest}'.")

                    r_reg_at = str(raw_r.get("registered_at") or created_at)
                    sess = live_agents.get(aid, {})
                    cid = str(sess.get("conversation_id", "")).strip()
                    r_status = (
                        "active" if cid and sess.get("status") == "active" else "disabled"
                    )
                    r_seen = str(sess.get("last_seen") or r_reg_at)
                    r_target_repo = (
                        str(raw_r.get("target_repo", "")).strip() or team_target_repo
                    )
                    r_target_repo_abs = self._resolve_target_repo(r_target_repo)

                    role_obj = {
                        "agent_id": aid,
                        "conversation_id": cid if r_status == "active" else "",
                        "last_seen": r_seen,
                        "mcp_tools": bool(raw_r.get("mcp_tools", True)),
                        "model": r_model,
                        "registered_at": r_reg_at,
                        "responsibilities": str(raw_r.get("responsibilities", "")).strip(),
                        "role": r_slug,
                        "role_path": self._rel_posix(role_dir),
                        "status": r_status,
                        "target_repo": r_target_repo,
                        "target_repo_abs": r_target_repo_abs,
                        "team_slug": slug,
                        "title": str(raw_r.get("title", "")).strip(),
                        "write_tools": bool(raw_r.get("write_tools", True)),
                    }
                    agents_by_id[aid] = role_obj
                    team_roles.append(role_obj)

            team_roles.sort(key=lambda r: (0 if r["role"] == "lead" else 1, r["role"]))
            team_status = (
                "active"
                if any(r["status"] == "active" and r["conversation_id"] for r in team_roles)
                else "disabled"
            )

            teams_by_slug[slug] = {
                "created_at": created_at,
                "default_model": model,
                "hive_path": hive_rel,
                "layer": len(curr_lineage),
                "lineage": curr_lineage,
                "mission": str(raw_t.get("mission", "")).strip(),
                "name": str(raw_t.get("name", slug)).strip(),
                "parent_team": expected_parent,
                "roles": team_roles,
                "slug": slug,
                "status": team_status,
                "target_repo": team_target_repo,
                "target_repo_abs": team_target_repo_abs,
                "updated_at": updated_at,
                "workspace_mode": ws,
                "child_teams": [],
            }

            # Recurse into child teams (teams/<child-slug>/team.json)
            children_root = team_dir / "teams"
            if children_root.is_dir():
                for child_dir in sorted(children_root.iterdir()):
                    if child_dir.is_dir() and not child_dir.name.startswith("."):
                        walk_team_dir(child_dir, slug, curr_lineage)

        if self.hive_dir.is_dir():
            for top_dir in sorted(self.hive_dir.iterdir()):
                if top_dir.is_dir() and not top_dir.name.startswith("."):
                    walk_team_dir(top_dir, None, [])

        # Populate child_teams summaries
        for t in sorted(teams_by_slug.values(), key=lambda item: item["slug"]):
            p_slug = t["parent_team"]
            if p_slug and p_slug in teams_by_slug:
                teams_by_slug[p_slug]["child_teams"].append(
                    {"name": t["name"], "slug": t["slug"], "status": t["status"]}
                )

        return teams_by_slug, agents_by_id, sessions

    @staticmethod
    def _get_descendant_slugs(
        teams_by_slug: Mapping[str, Dict[str, Any]], root_slug: str
    ) -> List[str]:
        descendants: List[str] = []
        queue = [root_slug]
        seen: Set[str] = {root_slug}
        while queue:
            curr = queue.pop(0)
            children = sorted(
                t["slug"]
                for t in teams_by_slug.values()
                if t["parent_team"] == curr
            )
            for c_slug in children:
                if c_slug not in seen:
                    seen.add(c_slug)
                    descendants.append(c_slug)
                    queue.append(c_slug)
        return descendants

    # ------------------------------------------------------------------
    # Org Graph & Team / Role Scaffolding
    # ------------------------------------------------------------------

    def register_prime(self, conversation_id: str) -> Dict[str, Any]:
        cid = conversation_id.strip()
        if not cid:
            raise ValueError("conversation_id cannot be empty for register-prime.")
        iso = now_iso()
        with self._lock(exclusive=True):
            sessions = self._read_sessions_unlocked()
            prev = sessions["agents"].get(PRIME_ID, {})
            sessions["agents"][PRIME_ID] = {
                "conversation_id": cid,
                "last_seen": iso,
                "registered_at": prev.get("registered_at") or iso,
                "status": "active",
            }
            self._write_sessions_unlocked(sessions)
            _, agents_by_id, _ = self._scan_state_unlocked()
            return agents_by_id[PRIME_ID]

    def create_team(
        self,
        slug: str,
        name: str,
        mission: str,
        parent_team: Optional[str] = None,
        default_model: str = "flash",
        workspace_mode: str = "inherit",
        lead_responsibilities: str = "",
        target_repo: str = "",
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
            raise ValueError(
                f"Invalid model '{default_model}'. Must be one of {sorted(VALID_MODELS)}."
            )
        ws = workspace_mode.strip().lower()
        if ws not in VALID_WORKSPACES:
            raise ValueError(
                f"Invalid workspace_mode '{workspace_mode}'. Must be one of {sorted(VALID_WORKSPACES)}."
            )

        clean_parent = validate_slug(parent_team, "parent_team") if parent_team else None
        clean_target_repo = (target_repo or "").strip()
        iso = now_iso()

        with self._lock(exclusive=True):
            teams_by_slug, _, sessions = self._scan_state_unlocked()
            if clean_slug in teams_by_slug:
                raise ValueError(f"Team '{clean_slug}' already exists.")

            stale_keys = [
                k for k in sessions["agents"] if k.startswith(f"{clean_slug}/")
            ]
            if stale_keys:
                for k in stale_keys:
                    sessions["agents"].pop(k, None)
                self._write_sessions_unlocked(sessions)

            if clean_parent:
                parent_obj = teams_by_slug.get(clean_parent)
                if not parent_obj:
                    raise ValueError(f"Parent team '{clean_parent}' does not exist.")
                parent_abs = self._abs_from_rel(parent_obj["hive_path"])
                team_dir = parent_abs / "teams" / clean_slug
                layer = parent_obj["layer"] + 1
                if not clean_target_repo and parent_obj.get("target_repo"):
                    clean_target_repo = parent_obj["target_repo"]
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

            (team_dir / "teams").mkdir(parents=True, exist_ok=True)
            (lead_dir / "workspace").mkdir(parents=True, exist_ok=True)
            (team_dir / "teams" / ".gitkeep").touch(exist_ok=True)
            (lead_dir / "workspace" / ".gitkeep").touch(exist_ok=True)

            target_repo_display = (
                clean_target_repo
                if clean_target_repo
                else "Local ULTRON Repository (default)"
            )
            team_agents_md = render_template(
                self._load_template("team_agents.md.tmpl"),
                {
                    "TEAM_NAME": clean_name,
                    "TEAM_MISSION": clean_mission,
                    "TEAM_SLUG": clean_slug,
                    "PARENT_TEAM_DISPLAY": clean_parent or f"{PRIME_ID} (Layer 1 root)",
                    "HIVE_PATH": hive_rel,
                    "TARGET_REPO_DISPLAY": target_repo_display,
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

            team_manifest: Dict[str, Any] = {
                "created_at": iso,
                "default_model": model,
                "hive_path": hive_rel,
                "layer": layer,
                "mission": clean_mission,
                "name": clean_name,
                "parent_team": clean_parent,
                "slug": clean_slug,
                "target_repo": clean_target_repo,
                "updated_at": iso,
                "workspace_mode": ws,
            }
            role_manifest: Dict[str, Any] = {
                "agent_id": lead_id,
                "mcp_tools": True,
                "model": model,
                "registered_at": iso,
                "responsibilities": lead_resp,
                "role": "lead",
                "role_path": lead_rel,
                "team_slug": clean_slug,
                "title": lead_title,
                "write_tools": True,
            }
            atomic_write_json(team_dir / "team.json", team_manifest)
            atomic_write_json(lead_dir / "role.json", role_manifest)

            teams_after, _, _ = self._scan_state_unlocked()
            return teams_after[clean_slug]

    def add_role(
        self,
        team_slug: str,
        role: str,
        title: str,
        responsibilities: str,
        model: Optional[str] = None,
        write_tools: bool = True,
        mcp_tools: bool = True,
        target_repo: str = "",
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

        clean_target_repo = (target_repo or "").strip()
        aid = f"{clean_team}/{clean_role}"
        iso = now_iso()

        with self._lock(exclusive=True):
            teams_by_slug, agents_by_id, sessions = self._scan_state_unlocked()
            team_obj = teams_by_slug.get(clean_team)
            if not team_obj:
                raise ValueError(f"Team '{clean_team}' does not exist.")
            if aid in agents_by_id:
                raise ValueError(f"Role '{aid}' already exists.")

            if aid in sessions["agents"]:
                sessions["agents"].pop(aid, None)
                self._write_sessions_unlocked(sessions)

            chosen_model = (model or team_obj["default_model"]).strip().lower()
            if chosen_model not in VALID_MODELS:
                raise ValueError(
                    f"Invalid model '{chosen_model}'. Must be one of {sorted(VALID_MODELS)}."
                )

            team_dir = self._abs_from_rel(team_obj["hive_path"])
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
                    "TEAM_NAME": team_obj["name"],
                    "TEAM_SLUG": clean_team,
                    "ROLE_SLUG": clean_role,
                    "ROLE_WORKSPACE_PATH": ws_rel,
                    "RESPONSIBILITIES": clean_resp,
                },
            )
            role_agents_path = role_dir / "AGENTS.md"
            if not role_agents_path.exists():
                role_agents_path.write_text(member_md, encoding="utf-8")

            role_manifest: Dict[str, Any] = {
                "agent_id": aid,
                "mcp_tools": bool(mcp_tools),
                "model": chosen_model,
                "registered_at": iso,
                "responsibilities": clean_resp,
                "role": clean_role,
                "role_path": role_rel,
                "team_slug": clean_team,
                "title": clean_title,
                "write_tools": bool(write_tools),
            }
            if clean_target_repo:
                role_manifest["target_repo"] = clean_target_repo
            atomic_write_json(role_dir / "role.json", role_manifest)

            # Update team.json updated_at
            t_manifest_path = team_dir / "team.json"
            t_manifest = json.loads(t_manifest_path.read_text(encoding="utf-8"))
            t_manifest["updated_at"] = iso
            atomic_write_json(t_manifest_path, t_manifest)

            _, agents_after, _ = self._scan_state_unlocked()
            return agents_after[aid]

    def set_target_repo(
        self,
        team_slug: str,
        target_repo: str = "",
        role: Optional[str] = None,
        cascade: bool = False,
    ) -> Dict[str, Any]:
        """Set or clear the external target repository for a team (optionally cascading) or a specific role."""
        clean_team = validate_slug(team_slug, "team slug")
        clean_role = validate_role_slug(role) if role else None
        clean_target = (target_repo or "").strip()
        iso = now_iso()

        with self._lock(exclusive=True):
            teams_by_slug, agents_by_id, _ = self._scan_state_unlocked()
            team_obj = teams_by_slug.get(clean_team)
            if not team_obj:
                raise ValueError(f"Team '{clean_team}' does not exist.")

            if clean_role:
                if cascade:
                    raise ValueError("--cascade cannot be combined with --role.")
                aid = f"{clean_team}/{clean_role}"
                role_obj = agents_by_id.get(aid)
                if not role_obj:
                    raise ValueError(f"Role '{aid}' does not exist.")
                role_dir = self._abs_from_rel(role_obj["role_path"])
                r_manifest_path = role_dir / "role.json"
                r_manifest = json.loads(r_manifest_path.read_text(encoding="utf-8"))
                if clean_target:
                    r_manifest["target_repo"] = clean_target
                else:
                    r_manifest.pop("target_repo", None)
                atomic_write_json(r_manifest_path, r_manifest)
                _, agents_after, _ = self._scan_state_unlocked()
                return agents_after[aid]

            target_slugs = (
                [clean_team, *self._get_descendant_slugs(teams_by_slug, clean_team)]
                if cascade
                else [clean_team]
            )
            for t_slug in target_slugs:
                t_dir = self._abs_from_rel(teams_by_slug[t_slug]["hive_path"])
                t_manifest_path = t_dir / "team.json"
                t_manifest = json.loads(t_manifest_path.read_text(encoding="utf-8"))
                t_manifest["target_repo"] = clean_target
                t_manifest["updated_at"] = iso
                atomic_write_json(t_manifest_path, t_manifest)

            teams_after, _, _ = self._scan_state_unlocked()
            return teams_after[clean_team]

    def get_team(self, slug: str) -> Optional[Dict[str, Any]]:
        clean = validate_slug(slug, "team slug")
        with self._lock(exclusive=False):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            return teams_by_slug.get(clean)

    def list_teams(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if status:
            st = status.strip().lower()
            if st not in VALID_TEAM_STATUSES:
                raise ValueError(f"Invalid status '{status}'.")
        else:
            st = None

        with self._lock(exclusive=False):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            teams = [
                t
                for t in teams_by_slug.values()
                if st is None or t["status"] == st
            ]
            teams.sort(key=lambda item: (item["layer"], item["slug"]))
            return teams

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        aid = normalize_agent_id(agent_id)
        with self._lock(exclusive=False):
            _, agents_by_id, _ = self._scan_state_unlocked()
            return agents_by_id.get(aid)

    def list_agents(
        self, team_slug: Optional[str] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        clean_team = validate_slug(team_slug, "team slug") if team_slug else None
        if status:
            st = status.strip().lower()
            if st not in VALID_AGENT_STATUSES:
                raise ValueError(f"Invalid status '{status}'.")
        else:
            st = None

        with self._lock(exclusive=False):
            _, agents_by_id, _ = self._scan_state_unlocked()
            items = [
                a
                for a in agents_by_id.values()
                if (clean_team is None or a["team_slug"] == clean_team)
                and (st is None or a["status"] == st)
            ]
            items.sort(
                key=lambda r: (
                    0 if r["agent_id"] == PRIME_ID else 1,
                    r["team_slug"] or "",
                    0 if r["role"] == "lead" else 1,
                    r["role"],
                )
            )
            return items

    # ------------------------------------------------------------------
    # Lifecycle Operations: Contacts, Render-Spawn, Activate, Disable, Remove
    # ------------------------------------------------------------------

    def get_contacts(self, agent_id: str) -> Dict[str, Any]:
        aid = normalize_agent_id(agent_id)
        with self._lock(exclusive=False):
            teams_by_slug, agents_by_id, _ = self._scan_state_unlocked()
            agent = agents_by_id.get(aid)
            if not agent and aid != PRIME_ID:
                raise ValueError(f"Agent '{aid}' is not registered.")

            prime_info = agents_by_id.get(PRIME_ID)

            if aid == PRIME_ID:
                l1_leads = [
                    agents_by_id[f"{t['slug']}/lead"]
                    for t in sorted(teams_by_slug.values(), key=lambda x: x["slug"])
                    if t["parent_team"] is None and f"{t['slug']}/lead" in agents_by_id
                ]
                return {
                    "agent_id": PRIME_ID,
                    "role": "prime",
                    "reports_to": "user",
                    "layer1_team_leads": l1_leads,
                }

            assert agent is not None
            t_slug = agent["team_slug"]
            team = teams_by_slug[t_slug]
            layer = team["layer"]

            if agent["role"] != "lead":
                return {
                    "agent_id": aid,
                    "team_slug": t_slug,
                    "layer": layer,
                    "role": agent["role"],
                    "reports_to": agents_by_id.get(f"{t_slug}/lead"),
                    "direct_peers_allowed": False,
                    "note": f"Coordinate and escalate strictly through your Team Lead ('{t_slug}/lead').",
                }

            if team["parent_team"]:
                superior = agents_by_id.get(f"{team['parent_team']}/lead")
            else:
                superior = prime_info

            teammates = [r for r in team["roles"] if r["role"] != "lead"]
            child_leads = [
                agents_by_id[f"{ct['slug']}/lead"]
                for ct in team["child_teams"]
                if f"{ct['slug']}/lead" in agents_by_id
            ]
            parent_disabled = bool(superior is None or superior["status"] != "active")
            return {
                "agent_id": aid,
                "team_slug": t_slug,
                "layer": layer,
                "role": "lead",
                "reports_to": superior,
                "parent_disabled_warning": parent_disabled,
                "prime_fallback": prime_info if parent_disabled else None,
                "team_members": teammates,
                "child_team_leads": child_leads,
            }

    def render_spawn(
        self,
        team_slug: str,
        role: Optional[str] = None,
        mission_brief: str = "",
    ) -> List[Dict[str, Any]]:
        clean_team = validate_slug(team_slug, "team slug")
        clean_role = validate_role_slug(role) if role else None

        with self._lock(exclusive=False):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            team = teams_by_slug.get(clean_team)
            if not team:
                raise ValueError(f"Team '{clean_team}' does not exist.")

            layer = team["layer"]
            lineage_slugs: List[str] = team["lineage"]
            lineage_display = " -> ".join([PRIME_ID, *lineage_slugs])

            role_objs = [
                r
                for r in team["roles"]
                if clean_role is None or r["role"] == clean_role
            ]
            if not role_objs:
                target = f"{clean_team}/{clean_role}" if clean_role else clean_team
                raise ValueError(f"No roles found for '{target}'.")

            charter_blocks: List[str] = []
            for anc_slug in lineage_slugs:
                anc = teams_by_slug[anc_slug]
                anc_dir = self._abs_from_rel(anc["hive_path"])
                anc_agents_file = anc_dir / "AGENTS.md"
                if anc_agents_file.is_file():
                    content = anc_agents_file.read_text(encoding="utf-8").strip()
                    charter_blocks.append(
                        f"### [{anc['slug']}] (`{anc['hive_path']}/AGENTS.md`)\n{content}"
                    )
            inherited_charters = (
                "\n\n".join(charter_blocks) if charter_blocks else "(No team charters found)"
            )

            teammate_ids = [r["agent_id"] for r in team["roles"] if r["role"] != "lead"]
            child_lead_ids = [f"{ct['slug']}/lead" for ct in team["child_teams"]]

        spawn_tmpl = self._load_template("spawn_prompt.md.tmpl")
        specs: List[Dict[str, Any]] = []

        for r in role_objs:
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
                superior_id = (
                    f"{team['parent_team']}/lead" if team["parent_team"] else PRIME_ID
                )
                members_str = (
                    ", ".join(f"`{m}`" for m in teammate_ids)
                    if teammate_ids
                    else "(none provisioned yet)"
                )
                children_str = (
                    ", ".join(f"`{c}`" for c in child_lead_ids)
                    if child_lead_ids
                    else "(none)"
                )
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

            r_target_repo = r.get("target_repo") or ""
            r_target_repo_abs = r.get("target_repo_abs") or ""
            ultron_root_str = str(self.repo_root)
            if r_target_repo and r_target_repo_abs:
                target_repo_summary = (
                    f"`{r_target_repo_abs}` (configured as `{r_target_repo}`)\n"
                    f"  - **Dual-Directory Execution Rule:** Your shell sessions (`run_command`) start in the ULTRON HQ root (`{ultron_root_str}`).\n"
                    f"  - Run all `python3 ultron/core/core.py ...` board and doorbell commands directly from the default working directory.\n"
                    f"  - Run all project build, test, and Git commands inside the target repository: `cd \"{r_target_repo_abs}\" && <command>`.\n"
                    f"  - Pass absolute paths under `{r_target_repo_abs}/...` when calling `read_file`, `edit_file`, `write_file`, `grep_search`, or `find_by_name` on project files."
                )
            else:
                target_repo_summary = f"Local ULTRON Repository (`{ultron_root_str}`)"

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
                    "TARGET_REPO_SUMMARY": target_repo_summary,
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
            if r_target_repo_abs:
                initial_prompt += (
                    f"2. Note your assigned target project repository at `{r_target_repo_abs}` "
                    f"(shell commands start in ULTRON HQ `{ultron_root_str}`).\n"
                )
            step_num = 3 if r_target_repo_abs else 2
            if mission_brief.strip():
                initial_prompt += f"{step_num}. Initial directive: {mission_brief.strip()}\n"
            else:
                initial_prompt += (
                    f"{step_num}. Confirm readiness in a brief reply to ULTRON PRIME and await doorbelled tasks on the board."
                )

            specs.append(
                {
                    "agent_id": aid,
                    "team_slug": clean_team,
                    "role": r_slug,
                    "read_only_mode": is_read_only,
                    "target_repo": r_target_repo,
                    "target_repo_abs": r_target_repo_abs,
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
        with self._lock(exclusive=True):
            teams_by_slug, agents_by_id, sessions = self._scan_state_unlocked()
            a_obj = agents_by_id.get(aid)
            if not a_obj:
                raise ValueError(f"Agent '{aid}' does not exist.")
            t_slug = a_obj["team_slug"]
            t_obj = teams_by_slug[t_slug]

            if t_obj["parent_team"] and not allow_detached:
                parent_obj = teams_by_slug.get(t_obj["parent_team"])
                if not parent_obj or parent_obj["status"] != "active":
                    raise ValueError(
                        f"Cannot activate '{aid}': parent team '{t_obj['parent_team']}' is disabled. "
                        f"Activate '{t_obj['parent_team']}' first or pass --allow-detached."
                    )

            if a_obj["role"] != "lead" and not allow_detached:
                lead_obj = agents_by_id.get(f"{t_slug}/lead")
                if not lead_obj or lead_obj["status"] != "active":
                    raise ValueError(
                        f"Cannot activate specialist '{aid}' while Team Lead '{t_slug}/lead' is disabled. "
                        f"Activate '{t_slug}/lead' first (or use activate-team)."
                    )

            sessions["agents"][aid] = {
                "conversation_id": cid,
                "last_seen": iso,
                "status": "active",
            }
            self._write_sessions_unlocked(sessions)
            _, agents_after, _ = self._scan_state_unlocked()
            return agents_after[aid]

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
                    raise ValueError(
                        f"Agent '{norm_id}' does not belong to team '{clean_team}'."
                    )
                r_slug = norm_id.split("/", 1)[1]
            else:
                r_slug = validate_role_slug(key)
            normalized_map[r_slug] = cid

        iso = now_iso()
        with self._lock(exclusive=True):
            teams_by_slug, _, sessions = self._scan_state_unlocked()
            t_obj = teams_by_slug.get(clean_team)
            if not t_obj:
                raise ValueError(f"Team '{clean_team}' does not exist.")

            if t_obj["parent_team"] and not allow_detached:
                parent_obj = teams_by_slug.get(t_obj["parent_team"])
                if not parent_obj or parent_obj["status"] != "active":
                    raise ValueError(
                        f"Cannot activate team '{clean_team}': parent team '{t_obj['parent_team']}' is disabled. "
                        f"Activate '{t_obj['parent_team']}' first or pass --allow-detached."
                    )

            existing_roles = {r["role"]: r for r in t_obj["roles"]}
            unknown = sorted(set(normalized_map.keys()) - set(existing_roles.keys()))
            if unknown:
                raise ValueError(f"Unknown role(s) for team '{clean_team}': {unknown}")

            lead_will_be_active = (
                "lead" in normalized_map or existing_roles["lead"]["status"] == "active"
            )
            if not lead_will_be_active and not allow_detached:
                raise ValueError(
                    f"Team activation for '{clean_team}' must include 'lead' UUID (or 'lead' must already be active), "
                    f"or pass --allow-detached."
                )

            missing_roles = sorted(
                r_slug
                for r_slug, r_obj in existing_roles.items()
                if r_slug not in normalized_map and r_obj["status"] != "active"
            )
            if missing_roles and not partial:
                raise ValueError(
                    f"Missing UUID(s) for role(s) {missing_roles} in team '{clean_team}'. "
                    f"Provide all role UUIDs or pass --partial."
                )

            for r_slug, cid in normalized_map.items():
                sessions["agents"][f"{clean_team}/{r_slug}"] = {
                    "conversation_id": cid,
                    "last_seen": iso,
                    "status": "active",
                }
            self._write_sessions_unlocked(sessions)
            teams_after, _, _ = self._scan_state_unlocked()
            return teams_after[clean_team]

    def _prepare_disable_unlocked(
        self,
        teams_by_slug: Mapping[str, Dict[str, Any]],
        agents_by_id: Mapping[str, Dict[str, Any]],
        clean_team: str,
        cascade: bool,
    ) -> Dict[str, Any]:
        if clean_team not in teams_by_slug:
            raise ValueError(f"Team '{clean_team}' does not exist.")

        descendants = self._get_descendant_slugs(teams_by_slug, clean_team)
        active_descendants = [
            d for d in descendants if teams_by_slug[d]["status"] == "active"
        ]
        if active_descendants and not cascade:
            raise ValueError(
                f"Cannot disable team '{clean_team}': active child teams exist ({active_descendants}). "
                f"Re-run with --cascade to disable the entire subtree."
            )

        target_teams = [clean_team] + (descendants if cascade else [])
        target_set = set(target_teams)
        active_agents = [
            {
                "agent_id": a["agent_id"],
                "conversation_id": a["conversation_id"],
                "role": a["role"],
                "team_slug": a["team_slug"],
            }
            for a in sorted(agents_by_id.values(), key=lambda x: x["agent_id"])
            if a["team_slug"] in target_set and a["conversation_id"]
        ]

        uuids: List[str] = []
        seen_uuids: Set[str] = set()
        for item in active_agents:
            cid = item["conversation_id"].strip()
            if cid and cid not in seen_uuids:
                seen_uuids.add(cid)
                uuids.append(cid)

        return {
            "agents_to_kill": active_agents,
            "cascade": cascade,
            "conversation_ids_to_kill": uuids,
            "team_slug": clean_team,
            "teams_affected": target_teams,
        }

    def prepare_disable(self, team_slug: str, cascade: bool = False) -> Dict[str, Any]:
        clean_team = validate_slug(team_slug, "team slug")
        with self._lock(exclusive=False):
            teams_by_slug, agents_by_id, _ = self._scan_state_unlocked()
            return self._prepare_disable_unlocked(
                teams_by_slug, agents_by_id, clean_team, cascade
            )

    def disable_team(self, team_slug: str, cascade: bool = False) -> Dict[str, Any]:
        clean_team = validate_slug(team_slug, "team slug")
        iso = now_iso()
        with self._lock(exclusive=True):
            teams_by_slug, agents_by_id, sessions = self._scan_state_unlocked()
            plan = self._prepare_disable_unlocked(
                teams_by_slug, agents_by_id, clean_team, cascade
            )
            target_set = set(plan["teams_affected"])
            for aid, a_obj in agents_by_id.items():
                if a_obj["team_slug"] in target_set and aid in sessions["agents"]:
                    sessions["agents"][aid] = {
                        "conversation_id": "",
                        "last_seen": iso,
                        "status": "disabled",
                    }
            self._write_sessions_unlocked(sessions)
            return plan

    def disable_agent(self, agent_id: str) -> Dict[str, Any]:
        aid = normalize_agent_id(agent_id)
        if aid == PRIME_ID:
            raise ValueError(f"Cannot disable '{PRIME_ID}'.")
        iso = now_iso()
        with self._lock(exclusive=True):
            teams_by_slug, agents_by_id, sessions = self._scan_state_unlocked()
            a_obj = agents_by_id.get(aid)
            if not a_obj:
                raise ValueError(f"Agent '{aid}' does not exist.")
            t_slug = a_obj["team_slug"]
            t_obj = teams_by_slug[t_slug]
            if a_obj["role"] == "lead":
                active_peers = [
                    r["agent_id"]
                    for r in t_obj["roles"]
                    if r["role"] != "lead" and r["status"] == "active"
                ]
                if active_peers:
                    raise ValueError(
                        f"Cannot disable Team Lead '{aid}' while specialists are still active "
                        f"({active_peers}). Use 'disable-team {t_slug}' instead."
                    )
            old_uuid = a_obj["conversation_id"]
            sessions["agents"][aid] = {
                "conversation_id": "",
                "last_seen": iso,
                "status": "disabled",
            }
            self._write_sessions_unlocked(sessions)
            return {
                "agent_id": aid,
                "previous_conversation_id": old_uuid,
                "status": "disabled",
            }

    def remove_team(
        self,
        team_slug: str,
        cascade: bool = False,
        delete_files: bool = False,
    ) -> Dict[str, Any]:
        clean_team = validate_slug(team_slug, "team slug")
        with self._lock(exclusive=True):
            teams_by_slug, _, sessions = self._scan_state_unlocked()
            t_obj = teams_by_slug.get(clean_team)
            if not t_obj:
                raise ValueError(f"Team '{clean_team}' does not exist.")

            descendants = self._get_descendant_slugs(teams_by_slug, clean_team)
            if descendants and not cascade:
                raise ValueError(
                    f"Cannot remove team '{clean_team}': child teams exist ({descendants}). "
                    f"Pass --cascade to remove the entire subtree."
                )

            target_slugs = [clean_team, *descendants]
            active_any = [
                s for s in target_slugs if teams_by_slug[s]["status"] == "active"
            ]
            if active_any:
                raise ValueError(
                    f"Cannot remove active team(s) {active_any}. Disable and kill live sessions first."
                )

            # Clean runtime session entries for removed teams
            target_set = set(target_slugs)
            for aid in list(sessions["agents"].keys()):
                if "/" in aid and aid.split("/", 1)[0] in target_set:
                    sessions["agents"].pop(aid, None)
            self._write_sessions_unlocked(sessions)

            root_hive_dir = self._abs_from_rel(t_obj["hive_path"])
            if delete_files:
                if root_hive_dir.is_dir():
                    shutil.rmtree(root_hive_dir)
            else:
                # Deregister team.json & role.json manifests while leaving AGENTS.md & workspace/ intact
                for s in reversed(target_slugs):
                    s_dir = self._abs_from_rel(teams_by_slug[s]["hive_path"])
                    for r_json in (s_dir / "roles").glob("*/role.json"):
                        r_json.unlink(missing_ok=True)
                    (s_dir / "team.json").unlink(missing_ok=True)

            return {
                "deleted_files": delete_files,
                "removed_teams": target_slugs,
            }

    # ------------------------------------------------------------------
    # Append-Only JSONL Message Board (Conflict-Free via merge=union)
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
    def _can_access_thread(
        viewer_id: str, unrestricted: bool, thread_obj: Mapping[str, Any]
    ) -> bool:
        if unrestricted or viewer_id == PRIME_ID:
            return True
        vis = (thread_obj.get("visibility") or "team").lower()
        if vis == "global":
            return True
        viewer_team = viewer_id.split("/", 1)[0] if "/" in viewer_id else ""
        if vis == "team":
            t_slug = (thread_obj.get("team_slug") or "").lower()
            w_slug = (thread_obj.get("with_team") or "").lower()
            return bool(viewer_team and viewer_team in {t_slug, w_slug})
        if vis == "personal":
            owner = (thread_obj.get("owner_agent") or "").lower()
            return viewer_id.lower() == owner
        return False

    def _resolve_thread_path_unlocked(self, thread_ref: str | int) -> Optional[Path]:
        raw = str(thread_ref).strip()
        if raw.startswith("#"):
            raw = raw[1:].strip()
        if not raw:
            return None
        clean = raw.lower()

        exact = self.threads_dir / f"{clean}.jsonl"
        if exact.is_file():
            return exact

        matches: List[Path] = []
        if self.threads_dir.is_dir():
            for fpath in sorted(self.threads_dir.glob("*.jsonl")):
                stem = fpath.stem.lower()
                short_hex = stem.rsplit("-", 1)[-1]
                if (
                    stem.startswith(clean)
                    or stem.endswith(clean)
                    or short_hex.startswith(clean)
                ):
                    matches.append(fpath)

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous thread reference '{thread_ref}': matches {[m.stem for m in matches]}."
            )
        return None

    @staticmethod
    def _fold_thread_jsonl(fpath: Path) -> Dict[str, Any]:
        """
        Deterministically fold append-only JSONL events into a materialized thread dict.
        Sorting follow-up events by (created_at, event_id) makes Git `merge=union`
        merges across branches 100% commutative and deterministic.
        """
        raw_lines = fpath.read_text(encoding="utf-8").splitlines()
        events: List[Dict[str, Any]] = []
        seen_event_ids: Set[str] = set()

        for line_no, raw_line in enumerate(raw_lines, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                ev = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Corrupt JSONL in '{fpath.name}' at line {line_no}: {exc}"
                ) from exc
            if not isinstance(ev, dict):
                raise ValueError(
                    f"Expected JSON object in '{fpath.name}' at line {line_no}."
                )
            ev_id = str(ev.get("event_id") or f"line-{line_no}")
            if ev_id in seen_event_ids:
                continue
            seen_event_ids.add(ev_id)
            events.append(ev)

        root_events = [e for e in events if e.get("type") == "thread"]
        if len(root_events) != 1:
            raise ValueError(
                f"Invalid thread file '{fpath.name}': expected exactly 1 root 'thread' event, found {len(root_events)}."
            )
        root = root_events[0]
        tid = str(root.get("thread_id") or fpath.stem)
        created_at = str(root["created_at"])

        vis = str(root.get("visibility", "team")).strip().lower()
        if vis not in VALID_VISIBILITIES:
            raise ValueError(f"Invalid visibility '{vis}' in '{fpath.name}'.")
        status = str(root.get("status", "open")).strip().lower()
        if status not in VALID_THREAD_STATUSES:
            raise ValueError(f"Invalid thread status '{status}' in '{fpath.name}'.")

        team_slug = (root.get("team_slug") or "") or None
        with_team = (root.get("with_team") or "") or None
        owner_agent = (root.get("owner_agent") or "") or None

        posts: List[Dict[str, Any]] = [
            {
                "author": str(root["author"]).lower(),
                "author_id": str(root.get("author_id") or ""),
                "content": str(root.get("content") or ""),
                "created_at": created_at,
                "id": str(root["post_id"]),
                "parent_post_id": None,
                "tags": str(root.get("tags") or ""),
                "thread_id": tid,
            }
        ]

        follow_ups = [e for e in events if e.get("type") != "thread"]
        follow_ups.sort(
            key=lambda e: (str(e.get("created_at") or ""), str(e.get("event_id") or ""))
        )

        updated_at = created_at
        for ev in follow_ups:
            ev_type = ev.get("type")
            ev_ts = str(ev.get("created_at") or created_at)
            if ev_ts > updated_at:
                updated_at = ev_ts

            if ev_type == "post":
                posts.append(
                    {
                        "author": str(ev["author"]).lower(),
                        "author_id": str(ev.get("author_id") or ""),
                        "content": str(ev.get("content") or ""),
                        "created_at": ev_ts,
                        "id": str(ev["post_id"]),
                        "parent_post_id": (ev.get("parent_post_id") or "") or None,
                        "tags": str(ev.get("tags") or ""),
                        "thread_id": tid,
                    }
                )
            elif ev_type == "status":
                new_st = str(ev["status"]).strip().lower()
                if new_st not in VALID_THREAD_STATUSES:
                    raise ValueError(
                        f"Invalid status event '{new_st}' in '{fpath.name}'."
                    )
                status = new_st
            elif ev_type == "reclassify":
                new_vis = str(ev["visibility"]).strip().lower()
                if new_vis not in VALID_VISIBILITIES:
                    raise ValueError(
                        f"Invalid reclassify visibility '{new_vis}' in '{fpath.name}'."
                    )
                vis = new_vis
                team_slug = (ev.get("team_slug") or "") or None
                with_team = (ev.get("with_team") or "") or None
                owner_agent = (ev.get("owner_agent") or "") or None
            else:
                raise ValueError(
                    f"Unknown event type '{ev_type}' in '{fpath.name}'."
                )

        return {
            "author": str(root["author"]).lower(),
            "author_id": str(root.get("author_id") or ""),
            "category": str(root.get("category") or "general").lower(),
            "created_at": created_at,
            "id": tid,
            "owner_agent": owner_agent,
            "post_count": len(posts),
            "posts": posts,
            "status": status,
            "team_slug": team_slug,
            "title": str(root["title"]),
            "updated_at": updated_at,
            "visibility": vis,
            "with_team": with_team,
        }

    def _load_all_threads_unlocked(self) -> List[Dict[str, Any]]:
        if not self.threads_dir.is_dir():
            return []
        threads = [
            self._fold_thread_jsonl(fpath)
            for fpath in sorted(self.threads_dir.glob("*.jsonl"))
            if fpath.is_file()
        ]
        threads.sort(key=lambda t: (t["updated_at"], t["id"]), reverse=True)
        return threads

    def _resolve_author_and_touch_unlocked(
        self,
        agents_by_id: Mapping[str, Dict[str, Any]],
        sessions: Dict[str, Dict[str, Any]],
        author: str,
        author_id: str,
        iso_time: str,
    ) -> Tuple[str, Optional[str], str]:
        norm_author = normalize_agent_id(author)
        a_obj = agents_by_id.get(norm_author)
        if not a_obj and norm_author != PRIME_ID:
            raise ValueError(
                f"Author '{norm_author}' is not a registered ULTRON agent. Create the team/role first."
            )
        resolved_uuid = author_id.strip()
        if a_obj and not resolved_uuid:
            resolved_uuid = a_obj["conversation_id"]
        if norm_author in sessions["agents"]:
            sessions["agents"][norm_author]["last_seen"] = iso_time
            self._write_sessions_unlocked(sessions)
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
    ) -> Dict[str, Any]:
        clean_title = title.strip()
        clean_content = content.strip()
        if not clean_title:
            raise ValueError("Thread title cannot be empty.")
        if not clean_content:
            raise ValueError("Thread content cannot be empty.")

        iso = now_iso()
        with self._lock(exclusive=True):
            teams_by_slug, agents_by_id, sessions = self._scan_state_unlocked()
            norm_author, author_team, resolved_uuid = self._resolve_author_and_touch_unlocked(
                agents_by_id, sessions, author, author_id, iso
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

            resolved_team: Optional[str] = (
                validate_slug(team_slug, "team") if team_slug else None
            )
            resolved_with: Optional[str] = (
                validate_slug(with_team, "with_team") if with_team else None
            )
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

                if resolved_team not in teams_by_slug:
                    raise ValueError(f"Team '{resolved_team}' does not exist.")

                if resolved_with:
                    if resolved_with == resolved_team:
                        raise ValueError(
                            "--with-team cannot be the same as the owning team."
                        )
                    if resolved_with not in teams_by_slug:
                        raise ValueError(
                            f"Target --with-team '{resolved_with}' does not exist."
                        )

            elif chosen_vis == "global":
                if with_team:
                    raise ValueError("--with-team is only valid for --visibility team.")
                if resolved_team and resolved_team not in teams_by_slug:
                    raise ValueError(f"Team '{resolved_team}' does not exist.")
                if not resolved_team and author_team:
                    resolved_team = author_team

            thread_id = generate_thread_id()
            while (self.threads_dir / f"{thread_id}.jsonl").exists():
                thread_id = generate_thread_id()
            post_id = generate_post_id()

            root_event = {
                "author": norm_author,
                "author_id": resolved_uuid,
                "category": category.strip().lower(),
                "content": clean_content,
                "created_at": iso,
                "event_id": generate_event_id(),
                "owner_agent": resolved_owner or "",
                "post_id": post_id,
                "status": "open",
                "tags": tags.strip(),
                "team_slug": resolved_team or "",
                "thread_id": thread_id,
                "title": clean_title,
                "type": "thread",
                "visibility": chosen_vis,
                "with_team": resolved_with or "",
            }
            append_jsonl_event(self.threads_dir / f"{thread_id}.jsonl", root_event)

        return {
            "author": norm_author,
            "author_id": resolved_uuid,
            "category": category.strip().lower(),
            "created_at": iso,
            "owner_agent": resolved_owner,
            "post_id": post_id,
            "team_slug": resolved_team,
            "thread_id": thread_id,
            "title": clean_title,
            "visibility": chosen_vis,
            "with_team": resolved_with,
        }

    def add_post(
        self,
        thread_id: str | int,
        author: str,
        content: str,
        parent_post_id: Optional[str | int] = None,
        tags: str = "",
        author_id: str = "",
    ) -> Dict[str, Any]:
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("Post content cannot be empty.")

        iso = now_iso()
        with self._lock(exclusive=True):
            fpath = self._resolve_thread_path_unlocked(thread_id)
            if not fpath:
                raise ValueError(f"Thread '{thread_id}' does not exist.")
            t_obj = self._fold_thread_jsonl(fpath)
            canonical_tid = t_obj["id"]

            _, agents_by_id, sessions = self._scan_state_unlocked()
            norm_author, _, resolved_uuid = self._resolve_author_and_touch_unlocked(
                agents_by_id, sessions, author, author_id, iso
            )
            if not self._can_access_thread(
                norm_author, norm_author == PRIME_ID, t_obj
            ):
                raise PermissionError(
                    f"Author '{norm_author}' is not authorized to access or reply to Thread '{canonical_tid}' "
                    f"(visibility='{t_obj['visibility']}')."
                )

            resolved_parent_post: Optional[str] = None
            if parent_post_id is not None and str(parent_post_id).strip():
                raw_pp = str(parent_post_id).strip().lstrip("#").lower()
                matching_posts = [
                    p["id"]
                    for p in t_obj["posts"]
                    if p["id"].lower() == raw_pp or p["id"].lower().endswith(raw_pp)
                ]
                if not matching_posts:
                    raise ValueError(
                        f"Parent post '{parent_post_id}' does not exist in Thread '{canonical_tid}'."
                    )
                if len(matching_posts) > 1:
                    raise ValueError(
                        f"Ambiguous parent post '{parent_post_id}': matches {matching_posts}."
                    )
                resolved_parent_post = matching_posts[0]

            existing_pids = {p["id"] for p in t_obj["posts"]}
            post_id = generate_post_id()
            while post_id in existing_pids:
                post_id = generate_post_id()

            post_event = {
                "author": norm_author,
                "author_id": resolved_uuid,
                "content": clean_content,
                "created_at": iso,
                "event_id": generate_event_id(),
                "parent_post_id": resolved_parent_post or "",
                "post_id": post_id,
                "tags": tags.strip(),
                "thread_id": canonical_tid,
                "type": "post",
            }
            append_jsonl_event(fpath, post_event)

        return {
            "author": norm_author,
            "author_id": resolved_uuid,
            "created_at": iso,
            "post_id": post_id,
            "thread_id": canonical_tid,
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

        vis_filter: Optional[str] = None
        if visibility:
            vis_filter = visibility.strip().lower()
            if vis_filter not in VALID_VISIBILITIES:
                raise ValueError(f"Invalid visibility '{visibility}'.")

        team_filter = validate_slug(team_slug, "team") if team_slug else None
        cat_filter = category.strip().lower() if category else None

        status_filter: Optional[str] = None
        if status:
            status_filter = status.strip().lower()
            if status_filter not in VALID_THREAD_STATUSES:
                raise ValueError(f"Invalid thread status '{status}'.")

        with self._lock(exclusive=False):
            all_threads = self._load_all_threads_unlocked()

        results: List[Dict[str, Any]] = []
        for t in all_threads:
            if not self._can_access_thread(viewer_id, unrestricted, t):
                continue
            if vis_filter and t["visibility"] != vis_filter:
                continue
            if team_filter and team_filter not in {
                (t["team_slug"] or "").lower(),
                (t["with_team"] or "").lower(),
            }:
                continue
            if cat_filter and t["category"] != cat_filter:
                continue
            if status_filter and t["status"] != status_filter:
                continue

            summary = {k: v for k, v in t.items() if k != "posts"}
            results.append(summary)
            if len(results) >= limit:
                break
        return results

    def get_thread(
        self,
        thread_id: str | int,
        as_agent: Optional[str] = None,
        show_all: bool = False,
    ) -> Optional[Dict[str, Any]]:
        viewer_id, unrestricted = self._resolve_viewer(as_agent, show_all)
        with self._lock(exclusive=False):
            fpath = self._resolve_thread_path_unlocked(thread_id)
            if not fpath:
                return None
            t_obj = self._fold_thread_jsonl(fpath)

        if not self._can_access_thread(viewer_id, unrestricted, t_obj):
            raise PermissionError(
                f"Agent '{viewer_id}' is not authorized to view Thread '{t_obj['id']}' "
                f"(visibility='{t_obj['visibility']}')."
            )
        return t_obj

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
        clean_q = query_str.strip()
        if not clean_q:
            raise ValueError("Search query cannot be empty.")

        vis_filter: Optional[str] = None
        if visibility:
            vis_filter = visibility.strip().lower()
            if vis_filter not in VALID_VISIBILITIES:
                raise ValueError(f"Invalid visibility '{visibility}'.")
        team_filter = validate_slug(team_slug, "team") if team_slug else None

        q_lower = clean_q.lower()
        tokens = [tok for tok in re.split(r"\s+", q_lower) if tok]

        with self._lock(exclusive=False):
            all_threads = self._load_all_threads_unlocked()

        scored_hits: List[Tuple[int, str, str, Dict[str, Any]]] = []
        for t in all_threads:
            if not self._can_access_thread(viewer_id, unrestricted, t):
                continue
            if vis_filter and t["visibility"] != vis_filter:
                continue
            if team_filter and team_filter not in {
                (t["team_slug"] or "").lower(),
                (t["with_team"] or "").lower(),
            }:
                continue

            title_lower = t["title"].lower()
            for p in t["posts"]:
                content_lower = p["content"].lower()
                tags_lower = p["tags"].lower()
                combined = f"{title_lower}\n{tags_lower}\n{content_lower}"

                score = 0
                if q_lower in content_lower:
                    score += 4
                if q_lower in title_lower or q_lower in tags_lower:
                    score += 3
                if score == 0 and len(tokens) > 1 and all(tok in combined for tok in tokens):
                    score = 1 + sum(1 for tok in tokens if tok in content_lower)

                if score > 0:
                    hit = {
                        "author": p["author"],
                        "category": t["category"],
                        "content": p["content"],
                        "created_at": p["created_at"],
                        "owner_agent": t["owner_agent"],
                        "post_id": p["id"],
                        "tags": p["tags"],
                        "team_slug": t["team_slug"],
                        "thread_id": t["id"],
                        "thread_title": t["title"],
                        "visibility": t["visibility"],
                        "with_team": t["with_team"],
                    }
                    scored_hits.append((score, p["created_at"], p["id"], hit))

        scored_hits.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return [item[3] for item in scored_hits[:limit]]

    def set_thread_status(
        self,
        thread_id: str | int,
        status: str,
        as_agent: Optional[str] = None,
        show_all: bool = False,
    ) -> bool:
        st = status.strip().lower()
        if st not in VALID_THREAD_STATUSES:
            raise ValueError(
                f"Invalid thread status '{status}'. Must be one of {sorted(VALID_THREAD_STATUSES)}."
            )
        viewer_id, unrestricted = self._resolve_viewer(as_agent, show_all)
        iso = now_iso()

        with self._lock(exclusive=True):
            fpath = self._resolve_thread_path_unlocked(thread_id)
            if not fpath:
                return False
            t_obj = self._fold_thread_jsonl(fpath)
            if not self._can_access_thread(viewer_id, unrestricted, t_obj):
                raise PermissionError(
                    f"Agent '{viewer_id}' is not authorized to modify Thread '{t_obj['id']}'."
                )
            status_event = {
                "actor": viewer_id,
                "created_at": iso,
                "event_id": generate_event_id(),
                "status": st,
                "thread_id": t_obj["id"],
                "type": "status",
            }
            append_jsonl_event(fpath, status_event)
        return True

    def reclassify_thread(
        self,
        thread_id: str | int,
        visibility: str,
        team_slug: Optional[str] = None,
        with_team: Optional[str] = None,
        owner_agent: Optional[str] = None,
        as_agent: Optional[str] = None,
        show_all: bool = False,
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
        with self._lock(exclusive=True):
            fpath = self._resolve_thread_path_unlocked(thread_id)
            if not fpath:
                raise ValueError(f"Thread '{thread_id}' does not exist.")
            t_obj = self._fold_thread_jsonl(fpath)
            teams_by_slug, agents_by_id, _ = self._scan_state_unlocked()

            new_team: Optional[str] = None
            new_with: Optional[str] = None
            new_owner: Optional[str] = None

            if vis == "personal":
                if with_team:
                    raise ValueError("--with-team cannot be set on a 'personal' thread.")
                candidate_owner = normalize_agent_id(
                    owner_agent or t_obj["owner_agent"] or t_obj["author"]
                )
                if candidate_owner != PRIME_ID:
                    owner_obj = agents_by_id.get(candidate_owner)
                    if not owner_obj:
                        raise ValueError(
                            f"Target owner agent '{candidate_owner}' does not exist."
                        )
                    new_team = owner_obj["team_slug"]
                else:
                    new_team = None
                new_owner = candidate_owner

            elif vis == "team":
                candidate_team = team_slug or t_obj["team_slug"]
                if not candidate_team and "/" in t_obj["author"]:
                    candidate_team = t_obj["author"].split("/", 1)[0]
                if not candidate_team:
                    raise ValueError("Reclassifying to 'team' requires --team <slug>.")
                new_team = validate_slug(candidate_team, "team")
                if new_team not in teams_by_slug:
                    raise ValueError(f"Target team '{new_team}' does not exist.")

                if with_team:
                    new_with = validate_slug(with_team, "with_team")
                    if new_with == new_team:
                        raise ValueError("--with-team cannot equal --team.")
                    if new_with not in teams_by_slug:
                        raise ValueError(
                            f"Target --with-team '{new_with}' does not exist."
                        )

            elif vis == "global":
                if with_team:
                    raise ValueError("--with-team cannot be set on a 'global' thread.")
                if team_slug:
                    new_team = validate_slug(team_slug, "team")
                    if new_team not in teams_by_slug:
                        raise ValueError(f"Target team '{new_team}' does not exist.")
                else:
                    new_team = t_obj["team_slug"]

            reclass_event = {
                "actor": viewer_id,
                "created_at": iso,
                "event_id": generate_event_id(),
                "owner_agent": new_owner or "",
                "team_slug": new_team or "",
                "thread_id": t_obj["id"],
                "type": "reclassify",
                "visibility": vis,
                "with_team": new_with or "",
            }
            append_jsonl_event(fpath, reclass_event)
            return self._fold_thread_jsonl(fpath)

    def verify(self, prune_orphans: bool = False) -> Dict[str, Any]:
        """Validate integrity of Hive manifests, runtime sessions, JSONL threads, and .gitattributes."""
        with self._lock(exclusive=prune_orphans):
            teams_by_slug, agents_by_id, sessions = self._scan_state_unlocked()
            for slug, t_obj in teams_by_slug.items():
                if f"{slug}/lead" not in agents_by_id:
                    raise ValueError(f"Team '{slug}' is missing required role '{slug}/lead'.")
                t_dir = self._abs_from_rel(t_obj["hive_path"])
                if not (t_dir / "AGENTS.md").is_file():
                    raise ValueError(f"Team '{slug}' is missing '{t_obj['hive_path']}/AGENTS.md'.")

            orphan_ids: List[str] = []
            for s_aid, s_entry in list(sessions["agents"].items()):
                norm_s_aid = normalize_agent_id(s_aid)
                if not isinstance(s_entry, dict):
                    raise ValueError(
                        f"Invalid runtime session entry for '{s_aid}': expected JSON object."
                    )
                s_status = str(s_entry.get("status", "disabled")).strip().lower()
                if s_status not in VALID_AGENT_STATUSES:
                    raise ValueError(
                        f"Invalid runtime status '{s_status}' for '{s_aid}' in sessions.json."
                    )
                s_cid = str(s_entry.get("conversation_id", "")).strip()
                if s_status == "active" and not s_cid:
                    raise ValueError(
                        f"Runtime session '{s_aid}' has status='active' with empty conversation_id."
                    )
                if norm_s_aid != PRIME_ID and norm_s_aid not in agents_by_id:
                    orphan_ids.append(s_aid)

            pruned_orphans: List[str] = []
            if orphan_ids:
                if prune_orphans:
                    for oid in orphan_ids:
                        sessions["agents"].pop(oid, None)
                    self._write_sessions_unlocked(sessions)
                    pruned_orphans = sorted(orphan_ids)
                else:
                    raise ValueError(
                        f"Found orphan runtime session(s) not present in Hive: {sorted(orphan_ids)}. "
                        f"Run 'verify --prune-orphans' to clean."
                    )

            threads = self._load_all_threads_unlocked()
            gitattr = self.threads_dir / ".gitattributes"
            has_union = (
                gitattr.is_file()
                and "merge=union" in gitattr.read_text(encoding="utf-8")
            )
            if not has_union:
                raise ValueError(
                    f"Missing '*.jsonl merge=union' in '{gitattr}'."
                )

            return {
                "agents": len(agents_by_id),
                "gitattributes_union_merge": has_union,
                "ok": True,
                "orphan_sessions": 0,
                "posts": sum(t["post_count"] for t in threads),
                "pruned_orphan_sessions": pruned_orphans,
                "teams": len(teams_by_slug),
                "threads": len(threads),
            }

    def get_stats(self) -> Dict[str, Any]:
        with self._lock(exclusive=False):
            teams_by_slug, agents_by_id, _ = self._scan_state_unlocked()
            threads = self._load_all_threads_unlocked()

        vis_counts: Dict[str, int] = {}
        cat_counts: Dict[str, int] = {}
        status_counts: Dict[str, int] = {}
        total_posts = 0
        for t in threads:
            total_posts += t["post_count"]
            vis_counts[t["visibility"]] = vis_counts.get(t["visibility"], 0) + 1
            cat_counts[t["category"]] = cat_counts.get(t["category"], 0) + 1
            status_counts[t["status"]] = status_counts.get(t["status"], 0) + 1

        return {
            "active_agents": sum(1 for a in agents_by_id.values() if a["status"] == "active"),
            "active_teams": sum(1 for t in teams_by_slug.values() if t["status"] == "active"),
            "categories": cat_counts,
            "hive_dir": str(self.hive_dir),
            "repo_root": str(self.repo_root),
            "sessions_file": str(self.sessions_file),
            "statuses": status_counts,
            "threads_dir": str(self.threads_dir),
            "total_agents": len(agents_by_id),
            "total_posts": total_posts,
            "total_teams": len(teams_by_slug),
            "total_threads": len(threads),
            "visibilities": vis_counts,
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
            repo_suffix = f" repo={t['target_repo']}" if t.get("target_repo") else ""
            lines.append(
                f"{prefix}{connector}[L{t['layer']}] {t['slug']} ({t['name']}) "
                f"[{t['status'].upper()} | {active_roles}/{len(t['roles'])} active] "
                f"roles: [{role_names}]{repo_suffix}"
            )
            next_prefix = prefix + ("    " if is_last else "│   ")
            render_branch(t["slug"], next_prefix)

    render_branch(None, "  ")
    return "\n".join(lines)


def format_agent_table(agents: List[Dict[str, Any]]) -> str:
    if not agents:
        return "[ULTRON] No registered agents/roles found."
    lines = [f"[ULTRON] Registered Roles & Sessions ({len(agents)}):\n"]
    header = (
        f"{'AGENT ID':<28} {'STATUS':<10} {'MODEL':<10} "
        f"{'CONVERSATION ID (UUID)':<38} {'TITLE'}"
    )
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
    lines.append(f"THREAD {thread['id']}: {thread['title']}")
    lines.append(
        f"Scope: [{format_scope_badge(thread)}] | Category: [{thread['category'].upper()}] | "
        f"Status: [{thread['status'].upper()}] | By: {thread['author']} ({thread['created_at'][:19]})"
    )
    lines.append("=" * 84)
    for post in thread.get("posts", []):
        reply_info = (
            f" (reply to {post['parent_post_id']})" if post.get("parent_post_id") else ""
        )
        lines.append(
            f"\n--- Post {post['id']} by @{post['author']}{reply_info} at {post['created_at'][:19]} ---"
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
    common.add_argument(
        "--root", default=argparse.SUPPRESS, help="Override ULTRON repository root"
    )
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit machine-readable JSON output",
    )

    parser = argparse.ArgumentParser(
        description="ULTRON Core: Pure Git-Native Org Registry, N-Layer Hive Scaffolder & JSONL Message Board",
        parents=[common],
    )
    parser.set_defaults(root=None, json=False)
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
    p_ct.add_argument(
        "--parent",
        default=None,
        help="Parent team slug (omit for Layer 1 under ULTRON PRIME)",
    )
    p_ct.add_argument(
        "--model",
        default="flash",
        choices=sorted(VALID_MODELS),
        help="Default model tier (default: flash)",
    )
    p_ct.add_argument(
        "--workspace",
        default="inherit",
        choices=sorted(VALID_WORKSPACES),
        help="Workspace mode (default: inherit)",
    )
    p_ct.add_argument(
        "--lead-responsibilities",
        default="",
        help="Optional custom Team Lead responsibilities",
    )
    p_ct.add_argument(
        "--target-repo",
        default="",
        help="Optional external target repository path (e.g. ~/Dev/XCOMBench)",
    )

    # add-role
    p_ar = add_cmd("add-role", "Add a specialist role to a team")
    p_ar.add_argument("--team", required=True, help="Team slug")
    p_ar.add_argument(
        "--role", required=True, help="Role slug (e.g. coder, reviewer, designer)"
    )
    p_ar.add_argument("--title", required=True, help="Human-readable role title")
    p_ar.add_argument(
        "--responsibilities", required=True, help="Role duties and deliverables"
    )
    p_ar.add_argument(
        "--model",
        default=None,
        choices=sorted(VALID_MODELS),
        help="Override model for this role",
    )
    p_ar.add_argument(
        "--read-only",
        action="store_true",
        help="Enforce [READ-ONLY ROLE MODE] prompt guardrails while preserving run_command for core.py",
    )
    p_ar.add_argument(
        "--no-mcp", action="store_true", help="Disable MCP tools (EnableMCPTools=False)"
    )
    p_ar.add_argument(
        "--target-repo",
        default="",
        help="Optional role-level target repository override",
    )

    # set-target-repo
    p_str = add_cmd(
        "set-target-repo",
        "Set or clear the external target repository for a team or role",
    )
    p_str.add_argument("team", help="Team slug")
    p_str.add_argument(
        "target_repo",
        nargs="?",
        default="",
        help="Target repository path (e.g. ~/Dev/XCOMBench); omit with --clear",
    )
    p_str.add_argument(
        "--role", default=None, help="Optional single role slug to override"
    )
    p_str.add_argument(
        "--cascade",
        action="store_true",
        help="Apply target repository to all descendant child teams",
    )
    p_str.add_argument(
        "--clear",
        action="store_true",
        help="Clear target repository back to local ULTRON repo",
    )

    # teams
    p_tms = add_cmd("teams", "List registered teams")
    p_tms.add_argument(
        "--status", default=None, choices=sorted(VALID_TEAM_STATUSES), help="Filter by status"
    )

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
    p_rs.add_argument(
        "--brief", default="", help="Optional initial directive appended to startup prompt"
    )

    # activate-team
    p_at = add_cmd("activate-team", "Bind live Antigravity UUIDs and mark a team active")
    p_at.add_argument("team", help="Team slug")
    p_at.add_argument(
        "--uuids",
        required=True,
        help='JSON object mapping role -> UUID (e.g. \'{"lead":"...","coder":"..."}\')',
    )
    p_at.add_argument(
        "--allow-detached",
        action="store_true",
        help="Allow activation even if parent team is disabled",
    )
    p_at.add_argument("--partial", action="store_true", help="Allow partial role activation")

    # activate-agent
    p_aa = add_cmd("activate-agent", "Bind a live Antigravity UUID to a single role")
    p_aa.add_argument("agent_id", help="Agent ID (<team>/<role> or ultron-prime)")
    p_aa.add_argument("--id", required=True, help="Conversation UUID")
    p_aa.add_argument(
        "--allow-detached",
        action="store_true",
        help="Allow activation if parent/lead is disabled",
    )

    # prepare-disable
    p_pd = add_cmd("prepare-disable", "List live UUIDs to kill before disabling a team")
    p_pd.add_argument("team", help="Team slug")
    p_pd.add_argument(
        "--cascade", action="store_true", help="Include all descendant child teams"
    )

    # disable-team
    p_dt = add_cmd(
        "disable-team", "Clear UUIDs and mark a team disabled after killing sessions"
    )
    p_dt.add_argument("team", help="Team slug")
    p_dt.add_argument(
        "--cascade", action="store_true", help="Disable entire descendant subtree"
    )

    # disable-agent
    p_da = add_cmd("disable-agent", "Disable a single specialist role")
    p_da.add_argument("agent_id", help="Agent ID (<team>/<role>)")

    # remove-team
    p_rm = add_cmd(
        "remove-team", "Remove a disabled team from registry (preserves board threads)"
    )
    p_rm.add_argument("team", help="Team slug")
    p_rm.add_argument(
        "--cascade", action="store_true", help="Remove child teams recursively"
    )
    p_rm.add_argument(
        "--delete-files",
        action="store_true",
        help="Also delete ultron/hive/<team> folder on disk",
    )

    # agents
    p_ag = add_cmd("agents", "List registered roles and live session UUIDs")
    p_ag.add_argument("--team", default=None, help="Filter by team slug")
    p_ag.add_argument(
        "--status", default=None, choices=sorted(VALID_AGENT_STATUSES), help="Filter by status"
    )

    # whois
    p_who = add_cmd("whois", "Resolve <team>/<role> or ultron-prime to live session UUID")
    p_who.add_argument("agent_id", help="Agent ID (e.g. platform/lead or ultron-prime)")
    p_who.add_argument(
        "--id-only",
        action="store_true",
        help="Print ONLY raw UUID to stdout (errors go strictly to stderr)",
    )

    # contacts
    p_con = add_cmd(
        "contacts", "Show chain-of-command contacts and live UUIDs for an agent"
    )
    p_con.add_argument("agent_id", help="Agent ID (e.g. platform/lead)")

    # new-thread
    p_new = add_cmd("new-thread", "Create a visibility-scoped JSONL board thread")
    p_new.add_argument("--title", required=True, help="Thread title")
    p_new.add_argument(
        "--author", required=True, help="Canonical author ID (<team>/<role> or ultron-prime)"
    )
    p_new.add_argument("--content", "-m", required=True, help="Initial post content")
    p_new.add_argument(
        "--category",
        default="general",
        help="Category (task, architecture, review, escalation, lesson, etc.)",
    )
    p_new.add_argument(
        "--visibility",
        default=None,
        choices=sorted(VALID_VISIBILITIES),
        help="Visibility (personal | team | global)",
    )
    p_new.add_argument(
        "--team", default=None, help="Owning team slug (inferred from author if omitted)"
    )
    p_new.add_argument(
        "--with-team",
        default=None,
        help="Secondary team slug for parent/child handoffs (team visibility only)",
    )
    p_new.add_argument("--tags", default="", help="Comma-separated tags")
    p_new.add_argument("--author-id", default="", help="Optional conversation UUID override")

    # reply
    p_rep = add_cmd("reply", "Append a reply to an existing JSONL thread")
    p_rep.add_argument("thread_id", help="Thread ID (full ID or unique short suffix/prefix)")
    p_rep.add_argument(
        "--author", required=True, help="Canonical author ID (<team>/<role> or ultron-prime)"
    )
    p_rep.add_argument("--content", "-m", required=True, help="Reply body")
    p_rep.add_argument("--reply-to", default=None, help="Optional parent post ID")
    p_rep.add_argument("--tags", default="", help="Comma-separated tags")
    p_rep.add_argument("--author-id", default="", help="Optional conversation UUID override")

    # list
    p_lst = add_cmd("list", "List visible threads (--as <agent_id> or --all required)")
    p_lst.add_argument(
        "--as", dest="as_agent", default=None, help="Caller agent ID (<team>/<role> or ultron-prime)"
    )
    p_lst.add_argument(
        "--all",
        dest="show_all",
        action="store_true",
        help="Unfiltered view (ULTRON PRIME / Curator)",
    )
    p_lst.add_argument(
        "--visibility",
        default=None,
        choices=sorted(VALID_VISIBILITIES),
        help="Filter by visibility",
    )
    p_lst.add_argument("--team", default=None, help="Filter by team involvement")
    p_lst.add_argument("--category", default=None, help="Filter by category")
    p_lst.add_argument(
        "--status", default=None, choices=sorted(VALID_THREAD_STATUSES), help="Filter by status"
    )
    p_lst.add_argument("--limit", type=int, default=25, help="Max threads to return")

    # view
    p_vw = add_cmd("view", "View full thread and replies (--as <agent_id> or --all required)")
    p_vw.add_argument("thread_id", help="Thread ID (full ID or unique short suffix/prefix)")
    p_vw.add_argument("--as", dest="as_agent", default=None, help="Caller agent ID")
    p_vw.add_argument(
        "--all",
        dest="show_all",
        action="store_true",
        help="Unfiltered view (ULTRON PRIME / Curator)",
    )

    # search
    p_sr = add_cmd("search", "Search across visible threads (--as <agent_id> or --all required)")
    p_sr.add_argument("query", help="Search query")
    p_sr.add_argument("--as", dest="as_agent", default=None, help="Caller agent ID")
    p_sr.add_argument(
        "--all",
        dest="show_all",
        action="store_true",
        help="Unfiltered view (ULTRON PRIME / Curator)",
    )
    p_sr.add_argument(
        "--visibility",
        default=None,
        choices=sorted(VALID_VISIBILITIES),
        help="Filter by visibility",
    )
    p_sr.add_argument("--team", default=None, help="Filter by team involvement")
    p_sr.add_argument("--limit", type=int, default=20, help="Max results")

    # set-status (alias: status)
    p_st = add_cmd(
        "set-status", "Append a thread status update event", aliases=["status"]
    )
    p_st.add_argument("thread_id", help="Thread ID (full ID or unique short suffix/prefix)")
    p_st.add_argument("status", choices=sorted(VALID_THREAD_STATUSES), help="New status")
    p_st.add_argument("--as", dest="as_agent", default=None, help="Caller agent ID")
    p_st.add_argument(
        "--all", dest="show_all", action="store_true", help="Unfiltered access (ULTRON PRIME)"
    )

    # reclassify
    p_rc = add_cmd(
        "reclassify", "Append a visibility/scope reclassification event (ULTRON PRIME / Curator)"
    )
    p_rc.add_argument("thread_id", help="Thread ID (full ID or unique short suffix/prefix)")
    p_rc.add_argument(
        "--visibility",
        required=True,
        choices=sorted(VALID_VISIBILITIES),
        help="Target visibility",
    )
    p_rc.add_argument("--team", default=None, help="Target owning team slug")
    p_rc.add_argument(
        "--with-team", default=None, help="Target secondary team slug (team visibility)"
    )
    p_rc.add_argument(
        "--owner", default=None, help="Target owner agent_id (personal visibility)"
    )
    p_rc.add_argument(
        "--as", dest="as_agent", default=None, help="Caller agent ID (must be ultron-prime)"
    )
    p_rc.add_argument(
        "--all", dest="show_all", action="store_true", help="Authorized ULTRON PRIME override"
    )

    # verify & stats
    p_ver = add_cmd(
        "verify",
        "Verify integrity of Hive manifests, runtime sessions, JSONL threads, and .gitattributes",
    )
    p_ver.add_argument(
        "--prune-orphans",
        action="store_true",
        help="Prune stale runtime session entries not present in ultron/hive/",
    )
    add_cmd("stats", "Show ULTRON Core & Hive statistics")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        core = UltronCore(repo_root=args.root)
        cmd = args.command

        if cmd == "register-prime":
            res = core.register_prime(args.id)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Registered {PRIME_ID} -> {res['conversation_id']} (status=active)"
                )

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
                target_repo=args.target_repo,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                repo_note = f" [target_repo={res['target_repo']}]" if res.get("target_repo") else ""
                print(
                    f"[ULTRON] Created Team '{res['slug']}' (Layer {res['layer']}) at {res['hive_path']} "
                    f"with role '{res['slug']}/lead' [status=disabled]{repo_note}"
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
                target_repo=args.target_repo,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                repo_note = f", target_repo={res['target_repo']}" if res.get("target_repo") else ""
                print(
                    f"[ULTRON] Added Role '{res['agent_id']}' ({res['title']}) at {res['role_path']} "
                    f"[model={res['model']}, write={res['write_tools']}, status=disabled{repo_note}]"
                )

        elif cmd == "set-target-repo":
            if not args.clear and not (args.target_repo or "").strip():
                raise ValueError(
                    "Provide a <target_repo> path or pass --clear to reset to local ULTRON repo."
                )
            chosen_repo = "" if args.clear else args.target_repo
            res = core.set_target_repo(
                team_slug=args.team,
                target_repo=chosen_repo,
                role=args.role,
                cascade=args.cascade,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                target_label = f"{args.team}/{args.role}" if args.role else args.team
                display_repo = res.get("target_repo") or "Local ULTRON Repository (default)"
                print(f"[ULTRON] Updated target_repo for '{target_label}' -> {display_repo}")

        elif cmd == "teams":
            res = core.list_teams(status=args.status)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            elif not res:
                print("[ULTRON] No teams registered.")
            else:
                for t in res:
                    repo_suffix = f" repo={t['target_repo']}" if t.get("target_repo") else ""
                    print(
                        f"[L{t['layer']}] {t['slug']:<20} status={t['status']:<10} "
                        f"parent={t['parent_team'] or PRIME_ID:<16} path={t['hive_path']}{repo_suffix}"
                    )

        elif cmd == "team-info":
            res = core.get_team(args.slug)
            if not res:
                print(f"[ULTRON Error] Team '{args.slug}' not found.", file=sys.stderr)
                return 1
            print(json.dumps(res, indent=2, sort_keys=True))

        elif cmd in ("render-spawn", "prepare-spawn"):
            specs = core.render_spawn(
                team_slug=args.team, role=args.role, mission_brief=args.brief
            )
            if args.json:
                print(json.dumps(specs, indent=2, sort_keys=True))
            else:
                for s in specs:
                    print("=" * 80)
                    print(
                        f"SPAWN SPEC FOR: {s['agent_id']} (TypeName={s['define_subagent']['Name']})"
                    )
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
                print(
                    f"[ULTRON] ConversationIds to kill ({len(res['conversation_ids_to_kill'])}):"
                )
                for cid in res["conversation_ids_to_kill"]:
                    print(f"  {cid}")

        elif cmd == "disable-team":
            res = core.disable_team(team_slug=args.team, cascade=args.cascade)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Disabled team(s) {res['teams_affected']} "
                    f"(cleared {len(res['conversation_ids_to_kill'])} live UUID(s); Hive files & JSONL threads preserved)."
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
                print(
                    f"[ULTRON Error] Agent '{args.agent_id}' is not registered.",
                    file=sys.stderr,
                )
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
                    f"[ULTRON] Created Thread {res['thread_id']} [{format_scope_badge(res)}]: "
                    f"'{res['title']}' (Post {res['post_id']})"
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
                    f"[ULTRON] Added Post {res['post_id']} to Thread {res['thread_id']} by @{res['author']}"
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
                header = (
                    f"{'ID':<21} {'SCOPE':<24} {'CAT':<12} "
                    f"{'STATUS':<12} {'POSTS':<6} {'AUTHOR':<18} {'TITLE'}"
                )
                print(header)
                print("-" * 118)
                for t in threads:
                    print(
                        f"{t['id']:<21} {format_scope_badge(t):<24} {t['category']:<12} "
                        f"{t['status']:<12} {t['post_count']:<6} {t['author']:<18} {t['title']}"
                    )

        elif cmd == "view":
            thread = core.get_thread(
                thread_id=args.thread_id,
                as_agent=args.as_agent,
                show_all=args.show_all,
            )
            if not thread:
                print(
                    f"[ULTRON Error] Thread '{args.thread_id}' not found.",
                    file=sys.stderr,
                )
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
                    snippet = r["content"][:140] + (
                        "..." if len(r["content"]) > 140 else ""
                    )
                    print(
                        f"[Post {r['post_id']} in Thread {r['thread_id']} "
                        f"({format_scope_badge(r)}) '{r['thread_title']}' by @{r['author']}]"
                    )
                    print(f"  {snippet}\n")

        elif cmd in ("set-status", "status"):
            has_identity = bool(
                args.as_agent or os.environ.get("ULTRON_AGENT_ID") or args.show_all
            )
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
                print(
                    f"[ULTRON Error] Thread '{args.thread_id}' not found.",
                    file=sys.stderr,
                )
                return 1
            print(f"[ULTRON] Thread '{args.thread_id}' status updated to '{args.status}'.")

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
                    f"[ULTRON] Reclassified Thread {res['id']} -> [{format_scope_badge(res)}]"
                )

        elif cmd == "verify":
            res = core.verify(prune_orphans=args.prune_orphans)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Integrity Verified: {res['teams']} team(s), {res['agents']} role(s), "
                    f"{res['threads']} JSONL thread(s) ({res['posts']} post(s)), "
                    f"pruned_orphans={len(res['pruned_orphan_sessions'])}, "
                    f"merge=union={res['gitattributes_union_merge']}."
                )

        elif cmd == "stats":
            stats = core.get_stats()
            if args.json:
                print(json.dumps(stats, indent=2, sort_keys=True))
            else:
                print("[ULTRON] System Statistics:")
                print(f"  Repo Root:        {stats['repo_root']}")
                print(f"  Hive Directory:   {stats['hive_dir']}")
                print(f"  Threads Dir:      {stats['threads_dir']}")
                print(f"  Runtime Sessions: {stats['sessions_file']}")
                print(
                    f"  Teams:            {stats['active_teams']} active / {stats['total_teams']} total"
                )
                print(
                    f"  Agents / Roles:   {stats['active_agents']} active / {stats['total_agents']} total"
                )
                print(
                    f"  Threads:          {stats['total_threads']} (Visibilities: {stats['visibilities']})"
                )
                print(f"  Posts:            {stats['total_posts']}")

        return 0

    except (ValueError, PermissionError, FileNotFoundError, RuntimeError) as exc:
        print(f"[ULTRON Error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
