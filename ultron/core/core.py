#!/usr/bin/env python3
"""
ULTRON Core (ultron/core/core.py)
Pure Git-native org registry, N-layer Hive team/role scaffolder, lifecycle coordinator,
and append-only JSONL message board for ULTRON (Universal Layered Team & Role Orchestration Network).

Storage Architecture (Zero SQLite / Zero External Dependencies):
- Org & Role Definitions (Git-tracked):
    ultron/hive/.../<team-slug>/team.json
    ultron/hive/.../<team-slug>/roles/<role-slug>/role.json
- Live Session Bindings: doorbell address, session ID, harness (Gitignored ephemeral runtime state):
    ultron/core/.runtime/sessions.json
- Message Board Threads (Git-tracked, conflict-free via *.jsonl merge=union):
    ultron/core/threads/<thread_id>.jsonl  (1 append-only JSON event per line)
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
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

MODEL_TIERS = ("small", "medium", "large")
LEGACY_MODEL_ALIASES = {"flash_lite": "small", "flash": "medium", "pro": "large"}
VALID_MODELS = {"inherit", *MODEL_TIERS}
MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:/@-]{1,127}$")
DEFAULT_MODEL_TIER = "medium"
CLAUDE_MODEL_FOR_TIER = {"small": "haiku", "medium": "sonnet", "large": "opus"}
OPENCODE_MODEL_TIER_ENVS = {
    "small": "ULTRON_OPENCODE_MODEL_SMALL",
    "medium": "ULTRON_OPENCODE_MODEL_MEDIUM",
    "large": "ULTRON_OPENCODE_MODEL_LARGE",
}
# Antigravity native `swarm` supports the full model roster (`swarm(action="models", all=true)`).
# Map portable tiers to balanced defaults while also allowing explicit model IDs via --model / set-model:
# - small  -> gemini-4-hydrogen-medium
# - medium -> inherit (omits `model` in swarm(action="add") so workers follow Prime's active model)
# - large  -> gemini-4-argon-medium
ANTIGRAVITY_MODEL_FOR_TIER = {
    "small": "gemini-4-hydrogen-medium",
    "medium": "inherit",
    "large": "gemini-4-argon-medium",
}
VALID_WORKSPACES = {"inherit", "share", "branch"}
ROLE_CONTEXT_FILENAME = "role_context.generated.md"
ROLE_CONTEXT_IMPORT = f"@{ROLE_CONTEXT_FILENAME}"
HARNESS_TOOLS = {
    "antigravity": {
        "shell": "run_command", "read": "read_file", "write": "write_file", "edit": "edit_file",
        "grep": "grep_search", "find": "find_by_name", "doorbell": "post_message",
    },
    "claude-code": {
        "shell": "Bash", "read": "Read", "write": "Write", "edit": "Edit",
        "grep": "Grep", "find": "Glob", "doorbell": "SendMessage",
    },
}
CLAUDE_BIN_ENV = "ULTRON_CLAUDE_BIN"
HARNESS_ENV = "ULTRON_HARNESS"
BG_SESSION_ID_RE = re.compile(r"claude attach\s+([A-Za-z0-9_-]+)")
ANTIGRAVITY_ENV_MARKERS = ("ANTIGRAVITY_AGENT", "ANTIGRAVITY_CONVERSATION_ID")
AGENTAPI_BIN_ENV = "ULTRON_AGENTAPI_BIN"
ANTIGRAVITY_DAEMON_DIR_ENV = "ULTRON_ANTIGRAVITY_DAEMON_DIR"
CLAUDE_DOORBELL_MODEL = "haiku"
ROLE_ID_ENV = "ULTRON_AGENT_ID"
PRIME_ONLY_COMMANDS = frozenset({
    "activate-agent", "activate-team", "add-role", "create-project", "create-team", "disable-agent",
    "disable-team", "link-project", "log-decision", "register-prime", "remove-project", "remove-team",
    "review-decision", "set-campaign", "set-harness", "set-lifespan", "set-model", "set-project", "set-target-repo",
    "spawn-team", "stop-team", "ui", "update-project",
})
SUPPRESSING_MEMORY_FILES = ("CLAUDE.md", "CLAUDE.local.md")
ROLE_CLAUDE_SETTINGS = {
    "worktree": {"bgIsolation": "none"},
    "permissions": {"deny": ["Agent", "Bash(claude:*)", "Bash(claude *)"]},
}
VALID_TEAM_STATUSES = {"active", "disabled"}
VALID_TEAM_LIFESPANS = {"permanent", "ephemeral"}
DEFAULT_TEAM_LIFESPAN = "permanent"
VALID_AGENT_STATUSES = {"active", "disabled"}
VALID_PROJECT_STATUSES = {"active", "paused", "archived"}
VALID_PROJECT_RELATIONS = {"depends_on", "related_to", "shares_assets_with", "part_of"}
VALID_DECISION_ORIGINS = {"user_guided", "prime_autonomous"}
VALID_DECISION_REVIEW_STATUSES = {"approved", "pending_review", "needs_improvement", "overruled"}
VALID_DECISION_SCOPES = {"global", "project", "team"}
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


def generate_decision_id() -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"d-{day}-{os.urandom(4).hex()}"


def render_template(template_text: str, values: Mapping[str, Any]) -> str:
    """Single-pass {{KEY}} substitution safe against literal braces in user content."""
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"Missing template placeholder '{{{{{key}}}}}'")
        return str(values[key])

    return PLACEHOLDER_RE.sub(_replace, template_text)


def normalize_model(value: str, source: str = "") -> str:
    cleaned = str(value).strip().lower()
    cleaned = LEGACY_MODEL_ALIASES.get(cleaned, cleaned)
    if cleaned in VALID_MODELS or (
        MODEL_ID_RE.match(cleaned)
        and ".." not in cleaned
        and "//" not in cleaned
        and not cleaned.endswith("/")
    ):
        return cleaned
    where = f" in {source}" if source else ""
    raise ValueError(
        f"Invalid model '{value}'{where}. Must be one of {sorted(VALID_MODELS)} "
        f"(legacy aliases: {sorted(LEGACY_MODEL_ALIASES)}) or an explicit model ID "
        f"matching {MODEL_ID_RE.pattern}."
    )


def resolve_opencode_model(model: str) -> Optional[Dict[str, str]]:
    """Resolve a normalized ULTRON model string to an OpenCode {'providerID', 'modelID'} dict.

    - 'inherit' returns None (omit model so OpenCode uses the server's opencode.json default).
    - Generic tiers ('small', 'medium', 'large') resolve via ULTRON_OPENCODE_MODEL_<TIER> env var;
      if unset, fail loud so local/BYOK models are never silently guessed.
    - Explicit models must use 'provider/model' format (e.g. 'ollama/qwen3-coder:32b').
    """
    cleaned = normalize_model(model)
    if cleaned == "inherit":
        return None
    if cleaned in MODEL_TIERS:
        env_var = OPENCODE_MODEL_TIER_ENVS[cleaned]
        override = os.environ.get(env_var, "").strip()
        if not override:
            raise ValueError(
                f"OpenCode has no built-in default for tier '{cleaned}'. "
                f"Set an explicit 'provider/model' (via --model or 'core.py set-model <team> <provider/model>'), "
                f"use 'inherit' to follow opencode.json's default model, or export {env_var}=<provider/model>."
            )
        override_clean = normalize_model(override, source=env_var)
        if override_clean == "inherit":
            return None
        if override_clean in MODEL_TIERS:
            raise ValueError(
                f"{env_var}='{override}' cannot point to another generic tier; use 'provider/model' or 'inherit'."
            )
        cleaned = override_clean

    if "/" not in cleaned:
        raise ValueError(
            f"OpenCode explicit model '{cleaned}' must be in 'provider/model' format "
            f"(e.g. 'ollama/qwen3-coder:32b' or 'vllm/deepseek-r1-32b'), or 'inherit'."
        )
    provider_id, model_id = cleaned.split("/", 1)
    if not provider_id or not model_id:
        raise ValueError(
            f"OpenCode explicit model '{cleaned}' must have non-empty provider and model IDs ('provider/model')."
        )
    return {"providerID": provider_id, "modelID": model_id}


def resolve_antigravity_model(model: str) -> Optional[str]:
    """Resolve a normalized model tier or explicit model ID for Antigravity swarm(action='add').

    Returns None when the worker should inherit Prime's active model (omit `model`).
    """
    if model == "inherit":
        return None
    mapped = ANTIGRAVITY_MODEL_FOR_TIER.get(model, model)
    return None if mapped == "inherit" else mapped


def swarm_name_for(agent_id: str) -> str:
    """Deterministically map an ULTRON agent_id to a valid Antigravity swarm roster name.

    Swarm worker names must be lowercase, start with a letter or digit, be <= 24 chars of
    [a-z0-9_-], and never be 'all', 'coordinator', or 'coordinator-*'.
    ULTRON PRIME maps to 'coordinator' (the swarm coordinator handle).
    """
    if agent_id == PRIME_ID:
        return "coordinator"
    team_slug, role_slug = agent_id.split("/", 1)
    base = f"{team_slug}-{role_slug}".lower()
    if base in {"all", "coordinator"} or base.startswith("coordinator-"):
        base = f"u-{base}"
    if len(base) <= 24:
        return base
    digest = hashlib.sha256(agent_id.encode("utf-8")).hexdigest()[:4]
    prefix = base[:19].rstrip("-_") or "u"
    return f"{prefix}-{digest}"


def with_role_context_import(charter_md: str) -> str:
    if ROLE_CONTEXT_IMPORT in charter_md.splitlines():
        return charter_md
    return charter_md.rstrip("\n") + f"\n\n{ROLE_CONTEXT_IMPORT}\n"


def without_role_context_import(charter_md: str) -> str:
    return "\n".join(l for l in charter_md.splitlines() if l.strip() != ROLE_CONTEXT_IMPORT).rstrip()


def session_name_for(agent_id: str) -> str:
    team_slug, role_slug = agent_id.split("/", 1)
    return f"ultron--{team_slug}--{role_slug}"


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


def normalize_project_subpath(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if "\x00" in cleaned:
        raise ValueError("Invalid project subpath: null byte not allowed.")
    if not cleaned.replace("\\", "/").strip("/"):
        return ""
    if cleaned.startswith(("/", "~", "\\\\")) or (
        len(cleaned) >= 2 and cleaned[1] == ":" and cleaned[0].isalpha()
    ):
        raise ValueError(
            f"Invalid project subpath '{value}': must be relative to the repository root."
        )
    parts = [seg for seg in cleaned.replace("\\", "/").split("/") if seg]
    for seg in parts:
        if seg in (".", ".."):
            raise ValueError(
                f"Invalid project subpath '{value}': path traversal segment '{seg}' is not allowed."
            )
    return "/".join(parts)


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


PROJECT_GUIDELINE_FILENAMES = ("AGENTS.md", "CLAUDE.md", ".cursorrules", "CONTRIBUTING.md")


def detect_target_repo_guidelines(repo_abs: str | Path) -> Tuple[List[str], str]:
    """Detect project-specific guideline files in the target repository root."""
    path = Path(repo_abs)
    if not path.is_dir():
        return [], (
            "  - **Project Guidelines:** None detected at repository root (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`). "
            "Inspect `README.md` or repository docs for project conventions and commit standards."
        )
    found = [f for f in PROJECT_GUIDELINE_FILENAMES if (path / f).is_file()]
    if found:
        joined = ", ".join(f"`{f}`" for f in found)
        note = (
            f"  - **Project Guidelines Detected:** {joined} at `{path}`.\n"
            f"  - **Mandatory Adherence:** You MUST read and strictly follow these developer guidelines for all coding conventions, "
            f"commit cadences (e.g. frequent small commits), testing standards, and architectural invariants in this repository."
        )
    else:
        note = (
            "  - **Project Guidelines:** None detected at repository root (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`). "
            "Inspect `README.md` or repository docs for project conventions and commit standards."
        )
    return found, note


class HarnessAdapter:
    name = ""
    tools: Mapping[str, str] = {}
    model_for_tier: Mapping[str, str] = {}

    def core_cmd(self, core: "UltronCore") -> str:
        raise NotImplementedError

    def target_repo_summary(self, core: "UltronCore", ctx: Mapping[str, Any]) -> str:
        raise NotImplementedError

    def build_spec(self, core: "UltronCore", ctx: Mapping[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def spawn(self, core: "UltronCore", team: Mapping[str, Any], specs: List[Dict[str, Any]]) -> Dict[str, Any]:
        raise NotImplementedError

    def stop(
        self, core: "UltronCore", plan: Dict[str, Any], sessions: Mapping[str, Any], cascade: bool
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def role_paths(self, core: "UltronCore", ctx: Mapping[str, Any]) -> Tuple[str, str, str]:
        raise NotImplementedError

    launches_from_cli = False

    def probe(self, agents: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
        raise NotImplementedError

    def shell_doorbell(self, address: str, text: str) -> None:
        raise NotImplementedError

    def doorbell_address(self, ctx: Mapping[str, Any]) -> str:
        raise NotImplementedError

    cron_tool: str = ""

    def doorbell_call(self) -> str:
        raise NotImplementedError

    def doorbell_resolve_cmd(self, core: "UltronCore") -> str:
        return f"{self.core_cmd(core)} whois <target_agent_id> --id-only"

    def charters_block(self, ctx: Mapping[str, Any]) -> str:
        raise NotImplementedError

    def render_role_context(self, core: "UltronCore", ctx: Mapping[str, Any]) -> str:
        r, team = ctx["role"], ctx["team"]
        role_dir, workspace, shell_start = self.role_paths(core, ctx)
        return render_template(
            core._load_template("role_context.md.tmpl"),
            {
                "AGENT_ID": ctx["agent_id"],
                "DOORBELL_ADDRESS": self.doorbell_address(ctx),
                "TEAM_NAME": team["name"],
                "TEAM_SLUG": ctx["team_slug"],
                "LAYER": str(ctx["layer"]),
                "ROLE_SLUG": r["role"],
                "ROLE_TITLE": r["title"],
                "LINEAGE_DISPLAY": ctx["lineage_display"],
                "ROLE_DIR": role_dir,
                "ROLE_WORKSPACE": workspace,
                "SHELL_START_DIR": shell_start,
                "TARGET_REPO_SUMMARY": self.target_repo_summary(core, ctx),
                "CORE_CMD": self.core_cmd(core),
                "ROUTING_SUMMARY": self.routing_summary(core, ctx),
                "DOORBELL_RESOLVE_CMD": self.doorbell_resolve_cmd(core),
                "DOORBELL_CALL": self.doorbell_call(),
                "TOOL_DOORBELL": self.tools["doorbell"],
                "CRON_TOOL": self.cron_tool,
                "PROJECT_DECISIONS_BLOCK": ctx.get("project_decisions_block", ""),
                "CHARTERS_BLOCK": self.charters_block(ctx),
            },
        )

    def read_only_note(self, core: "UltronCore") -> str:
        t = self.tools
        return (
            f"\n- **[READ-ONLY ROLE MODE]:** Do NOT call `{t['write']}` or `{t['edit']}` on repository source code. "
            f"Use `{t['shell']}` strictly for `{self.core_cmd(core)}` board operations and non-mutating inspection/test commands."
        )

    def routing_summary(self, core: "UltronCore", ctx: Mapping[str, Any]) -> str:
        return ctx["routing_summary"] + (self.read_only_note(core) if ctx["read_only"] else "")


class AntigravityAdapter(HarnessAdapter):
    name = "antigravity"
    tools = HARNESS_TOOLS["antigravity"]
    model_for_tier = ANTIGRAVITY_MODEL_FOR_TIER
    cron_tool = "schedule"

    def spawn(self, core: "UltronCore", team: Mapping[str, Any], specs: List[Dict[str, Any]]) -> Dict[str, Any]:
        for sp in specs:
            Path(sp["role_context_path"]).write_text(sp["role_context"], encoding="utf-8")
        return {
            "harness": self.name,
            "team_slug": team["slug"],
            "status": "awaiting_prime",
            "specs": specs,
            "next_steps": [
                f"Optional (first team): swarm(action=\"title\", title=\"ULTRON: {team['slug']}\").",
                "For each spec: swarm(**spec['swarm_add']) (verify models with swarm(action='models', all=true) if needed).",
                f"Bind the returned conversation_id UUIDs: activate-team {team['slug']} --uuids '{{\"<role>\": \"<uuid>\", ...}}'",
                "Arm a recurring Safety Cron (`schedule`, e.g. '*/10 * * * *') while the team works, and commit & push ultron/hive/ and ultron/core/threads/ to origin.",
            ],
        }

    def stop(
        self, core: "UltronCore", plan: Dict[str, Any], sessions: Mapping[str, Any], cascade: bool
    ) -> Dict[str, Any]:
        cascade_flag = " --cascade" if cascade else ""
        swarm_names = [swarm_name_for(a["agent_id"]) for a in plan["agents_to_kill"]]
        kill_calls = ", ".join(f'swarm(action="kill", name="{n}")' for n in swarm_names)
        return {
            **plan,
            "harness": self.name,
            "status": "awaiting_prime",
            "swarm_names_to_kill": swarm_names,
            "stop_failures": {},
            "missing_session_ids": [],
            "next_steps": [
                f"Kill each swarm worker: {kill_calls}" if kill_calls else "No live swarm workers to kill.",
                f"disable-team {plan['team_slug']}{cascade_flag}",
                "Commit & push ultron/hive/ and ultron/core/threads/ to origin (and cancel the Safety Cron if no active teams remain).",
            ],
        }

    def probe(self, agents: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
        swarm_names = sorted(swarm_name_for(aid) for aid in agents)
        return {
            "harness": self.name,
            "agents": {aid: {"state": "unknown", "detail": "probe from Antigravity"} for aid in agents},
            "next_steps": [
                f"swarm(action=\"status\") and verify these workers are waiting/working (not stopped/killed): {swarm_names}",
                "Checkpoint any new board posts or hive updates: git add ultron/core/threads ultron/hive && git commit && git push.",
            ],
        }

    @staticmethod
    def agentapi_bin() -> str:
        explicit = os.environ.get(AGENTAPI_BIN_ENV, "").strip()
        if explicit:
            return explicit
        return shutil.which("agentapi") or str(Path.home() / ".gemini" / "antigravity" / "bin" / "agentapi")

    @staticmethod
    def live_daemon_env() -> Dict[str, str]:
        if os.environ.get("ANTIGRAVITY_LS_ADDRESS") and os.environ.get("ANTIGRAVITY_CSRF_TOKEN"):
            return {}
        daemon_dir = Path(
            os.environ.get(ANTIGRAVITY_DAEMON_DIR_ENV, "").strip()
            or Path.home() / ".gemini" / "antigravity" / "daemon"
        )
        hubs = sorted(daemon_dir.glob("hub_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        for hub in hubs:
            try:
                meta = json.loads(hub.read_text(encoding="utf-8"))
                os.kill(int(meta["pid"]), 0)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            return {
                "ANTIGRAVITY_LS_ADDRESS": f"localhost:{meta['httpPort']}",
                "ANTIGRAVITY_CSRF_TOKEN": str(meta["csrfToken"]),
            }
        raise RuntimeError(f"No running Antigravity daemon found in '{daemon_dir}' (hub_*.json with a live pid).")

    def shell_doorbell(self, address: str, text: str) -> None:
        env = {**os.environ, **self.live_daemon_env()}
        res = subprocess.run(
            [self.agentapi_bin(), "send-message", address, text],
            capture_output=True, text=True, timeout=60, env=env, stdin=subprocess.DEVNULL,
        )
        if res.returncode != 0:
            raise RuntimeError(f"agentapi send-message failed (exit {res.returncode}): {(res.stderr or res.stdout).strip()}")

    def core_cmd(self, core: "UltronCore") -> str:
        return "python3 ultron/core/core.py"

    def role_paths(self, core: "UltronCore", ctx: Mapping[str, Any]) -> Tuple[str, str, str]:
        return ctx["role"]["role_path"], ctx["role_workspace_rel"], str(core.repo_root)

    def doorbell_address(self, ctx: Mapping[str, Any]) -> str:
        return (
            f"`@{swarm_name_for(ctx['agent_id'])}` (swarm board) / "
            "conversation UUID bound by `activate-team` (cross-harness)"
        )

    def doorbell_resolve_cmd(self, core: "UltronCore") -> str:
        return f"{self.core_cmd(core)} whois <target_agent_id> --swarm-name"

    def doorbell_call(self) -> str:
        return (
            'call `post_message(text="@<swarm_name> Doorbell: Posted on Thread <thread_id> (\'Title\')...")` '
            '(use `@coordinator` for `ultron-prime`)'
        )

    def charters_block(self, ctx: Mapping[str, Any]) -> str:
        return (
            f"\n---\n\n## Inherited Team & Ancestor Charters\n{ctx['inherited_charters']}\n\n---\n\n"
            f"## Role Charter (`{ctx['role']['role_path']}/AGENTS.md`)\n{without_role_context_import(ctx['role_charter'])}"
        )

    def target_repo_summary(self, core: "UltronCore", ctx: Mapping[str, Any]) -> str:
        ultron_root_str = str(core.repo_root)
        repo, repo_abs = ctx["target_repo"], ctx["target_repo_abs"]
        if not (repo and repo_abs):
            return f"Local ULTRON Repository (`{ultron_root_str}`)"
        _, guidelines_note = detect_target_repo_guidelines(repo_abs)
        return (
            f"`{repo_abs}` (configured as `{repo}`)\n"
            f"  - **Dual-Directory Execution Rule:** Your shell sessions (`run_command`) start in the ULTRON HQ root (`{ultron_root_str}`).\n"
            f"  - Run all `python3 ultron/core/core.py ...` board and doorbell commands directly from the default working directory.\n"
            f"  - Run all project build, test, and Git commands inside the target repository: `cd \"{repo_abs}\" && <command>`.\n"
            f"  - Pass absolute paths under `{repo_abs}/...` when calling `read_file`, `edit_file`, `write_file`, `grep_search`, or `find_by_name` on project files.\n"
            f"{guidelines_note}"
        )

    def build_spec(self, core: "UltronCore", ctx: Mapping[str, Any]) -> Dict[str, Any]:
        r, team, aid = ctx["role"], ctx["team"], ctx["agent_id"]
        clean_team, r_slug = ctx["team_slug"], r["role"]
        role_dir = ctx["role_dir"]
        repo_abs = ctx["target_repo_abs"]
        s_name = swarm_name_for(aid)
        role_context = self.render_role_context(core, ctx)
        role_context_path = str(role_dir.resolve() / ROLE_CONTEXT_FILENAME)

        brief_lines = [
            f"ULTRON role assignment: `{aid}` ({r['title']}, team `{clean_team}`, swarm `@{s_name}`).",
            f"1. IMMEDIATELY call `read_file` on `{role_context_path}` to load your full role charter, inherited charters, project decisions, and routing rules before doing anything else.",
            f"2. Run your startup hydration commands (`python3 ultron/core/core.py list --as {aid} --visibility personal`, `--visibility team`, `--visibility global`, and `directory {aid}`).",
            "3. Hard governance rule: Only ULTRON PRIME spawns or stops agents — NEVER call `swarm(action='add')` or `swarm(action='kill')`.",
        ]
        if repo_abs:
            brief_lines.append(
                f"4. Target project repository: `{repo_abs}` (shell commands start in ULTRON HQ `{core.repo_root}`)."
            )
            step_num = 5
        else:
            step_num = 4
        if ctx["mission_brief"]:
            brief_lines.append(f"{step_num}. Initial directive: {ctx['mission_brief']}")
        else:
            brief_lines.append(
                f"{step_num}. Post a brief readiness reply to `@coordinator` via `post_message`, then end your turn and await doorbelled tasks."
            )
        short_brief = "\n".join(brief_lines)

        resolved_model = resolve_antigravity_model(r["model"])
        swarm_add: Dict[str, Any] = {
            "action": "add",
            "name": s_name,
            "workspace": team["workspace_mode"],
            "brief": short_brief,
        }
        if resolved_model is not None:
            swarm_add["model"] = resolved_model

        return {
            "agent_id": aid,
            "team_slug": clean_team,
            "role": r_slug,
            "swarm_name": s_name,
            "read_only_mode": ctx["read_only"],
            "target_repo": ctx["target_repo"],
            "target_repo_abs": repo_abs,
            "role_context_path": role_context_path,
            "role_context": role_context,
            "swarm_add": swarm_add,
        }


class ClaudeCodeAdapter(HarnessAdapter):
    name = "claude-code"
    tools = HARNESS_TOOLS["claude-code"]
    model_for_tier = CLAUDE_MODEL_FOR_TIER
    cron_tool = "CronCreate"

    @staticmethod
    def check_auth_expiry(claude_bin: str) -> None:
        try:
            res = subprocess.run([claude_bin, "auth", "status"], capture_output=True, text=True, timeout=10)
            out = res.stdout.strip()
            if not out:
                return
            try:
                data = json.loads(out)
            except Exception:
                print(f"[ULTRON Warning] Could not parse 'claude auth status' output: {out[:100]}", file=sys.stderr)
                return
            if not data.get("loggedIn"):
                raise RuntimeError("Claude Code is not logged in. Renew with 'claude auth login' or use 'claude setup-token'.")
            expires_at_str = data.get("loginExpiresAt")
            if expires_at_str:
                from datetime import datetime, timezone
                try:
                    exp_dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                    now_dt = datetime.now(timezone.utc)
                    remaining = (exp_dt - now_dt).total_seconds()
                    if remaining < 48 * 3600:
                        hours = max(0, int(remaining / 3600))
                        print(
                            f"[ULTRON Warning] Claude Code login expires soon ({hours}h remaining at {expires_at_str}). "
                            f"Renew with 'claude auth login' or use 'claude setup-token' for unattended hives.",
                            file=sys.stderr,
                        )
                except Exception:
                    pass
        except RuntimeError:
            raise
        except Exception:
            pass

    @staticmethod
    def claude_bin() -> str:
        return os.environ.get(CLAUDE_BIN_ENV, "claude")

    @staticmethod
    def refuse_suppressing_memory_files(role_dir: Path) -> None:
        for folder in [role_dir, *role_dir.parents]:
            for name in SUPPRESSING_MEMORY_FILES:
                if (folder / name).is_file():
                    raise ValueError(
                        f"'{folder / name}' exists above role folder '{role_dir}'. Claude Code then ignores "
                        f"every AGENTS.md in the chain, so the role would boot without its charters. Remove it."
                    )

    def stop_session(self, session_id: str) -> Optional[str]:
        res = subprocess.run([self.claude_bin(), "stop", session_id], capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            return (res.stderr or res.stdout).strip() or f"exit code {res.returncode}"
        return None

    launches_from_cli = True

    @staticmethod
    def launch_env() -> Dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("ANTIGRAVITY_") and k != ROLE_ID_ENV}
        env[HARNESS_ENV] = "claude-code"
        return env

    def shell_doorbell(self, address: str, text: str) -> None:
        prompt = (
            f'Call the SendMessage tool once, with to="{address}" and message set to the text between '
            "the markers, copied byte for byte.\n<<<ULTRON_MSG\n"
            f"{text}\nULTRON_MSG>>>\n"
            'Then reply with exactly "sent", or the exact error text.'
        )
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        res = subprocess.run(
            [self.claude_bin(), "-p", prompt, "--model", CLAUDE_DOORBELL_MODEL,
             "--dangerously-skip-permissions", "--tools", "SendMessage"],
            capture_output=True, text=True, timeout=180, env=env, cwd=tempfile.gettempdir(),
            stdin=subprocess.DEVNULL,
        )
        lines = res.stdout.strip().splitlines()
        if res.returncode != 0 or not lines or lines[-1].strip() != "sent":
            raise RuntimeError(
                f"Claude Code doorbell to '{address}' failed (exit {res.returncode}): "
                f"{(res.stdout + res.stderr).strip()}"
            )

    def live_sessions(self) -> List[Dict[str, Any]]:
        res = subprocess.run([self.claude_bin(), "agents", "--json"], capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            raise RuntimeError(f"'claude agents --json' failed: {(res.stderr or res.stdout).strip()}")
        return [s for s in json.loads(res.stdout) if s.get("pid")]

    def probe(self, agents: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
        live = self.live_sessions()
        results: Dict[str, Dict[str, str]] = {}
        for aid, entry in agents.items():
            sid = str(entry.get("session_id", "")).strip()
            if not sid:
                results[aid] = {"state": "unknown", "detail": "no session id recorded"}
                continue
            match = next(
                (s for s in live if s.get("id") == sid or str(s.get("sessionId", "")).startswith(sid)), None
            )
            if match:
                results[aid] = {"state": "alive", "detail": str(match.get("status", ""))}
            else:
                results[aid] = {"state": "gone", "detail": f"session {sid} is not running"}
        return {"harness": self.name, "agents": results, "next_steps": []}

    def spawn(self, core: "UltronCore", team: Mapping[str, Any], specs: List[Dict[str, Any]]) -> Dict[str, Any]:
        if team["workspace_mode"] == "branch":
            raise ValueError(
                f"Team '{team['slug']}' uses workspace_mode 'branch', which the claude-code harness does not support yet."
            )
        for sp in specs:
            role_dir = Path(sp["role_dir"])
            self.refuse_suppressing_memory_files(role_dir)
            charter = role_dir / "AGENTS.md"
            if not charter.is_file() or ROLE_CONTEXT_IMPORT not in charter.read_text(encoding="utf-8").splitlines():
                raise ValueError(
                    f"'{charter}' must contain the line '{ROLE_CONTEXT_IMPORT}' so the role loads its context."
                )
        self.check_auth_expiry(self.claude_bin())
        for sp in specs:
            role_dir = Path(sp["role_dir"])
            (role_dir / ROLE_CONTEXT_FILENAME).write_text(sp["role_context"], encoding="utf-8")
            atomic_write_json(
                role_dir / ".claude" / "settings.json",
                {**ROLE_CLAUDE_SETTINGS, "env": {ROLE_ID_ENV: sp["agent_id"], HARNESS_ENV: self.name}},
            )

        was_archived = bool(team.get("archived", False))
        addresses = {sp["role"]: sp["session_name"] for sp in specs}
        core.activate_team(team["slug"], addresses, harness=self.name)
        launched: Dict[str, str] = {}
        for sp in specs:
            cmd = [self.claude_bin(), "--bg", sp["initial_prompt"], "-n", sp["session_name"],
                   "--dangerously-skip-permissions"]
            if sp["claude_model"]:
                cmd += ["--model", sp["claude_model"]]
            if sp["target_repo_abs"]:
                cmd.append(f"--add-dir={sp['target_repo_abs']}")
            res = subprocess.run(
                cmd, cwd=sp["role_dir"], capture_output=True, text=True, timeout=120, env=self.launch_env()
            )
            match = BG_SESSION_ID_RE.search(res.stdout)
            if res.returncode != 0 or not match:
                cleanup_errors = {
                    role: err for role, sid in launched.items() if (err := self.stop_session(sid))
                }
                core.disable_team(team["slug"], archive_ephemeral=was_archived)
                raise RuntimeError(
                    f"Launching '{sp['agent_id']}' failed (exit {res.returncode}): "
                    f"{(res.stderr or res.stdout).strip()}. Stopped already-launched roles {sorted(launched)}"
                    + (f"; stop failures: {cleanup_errors}" if cleanup_errors else ".")
                )
            launched[sp["role"]] = match.group(1)

        team_after = core.activate_team(team["slug"], addresses, session_ids=launched, harness=self.name)
        return {
            "harness": self.name,
            "team_slug": team["slug"],
            "sessions": [
                {"agent_id": sp["agent_id"], "session_name": sp["session_name"],
                 "session_id": launched[sp["role"]], "model": sp["claude_model"] or "inherit"}
                for sp in specs
            ],
            "status": team_after["status"],
            "next_steps": [],
        }

    def stop(
        self, core: "UltronCore", plan: Dict[str, Any], sessions: Mapping[str, Any], cascade: bool
    ) -> Dict[str, Any]:
        stop_failures: Dict[str, str] = {}
        missing_session_ids: List[str] = []
        for agent in plan["agents_to_kill"]:
            sid = str(sessions["agents"].get(agent["agent_id"], {}).get("session_id", "")).strip()
            if not sid:
                missing_session_ids.append(agent["agent_id"])
                continue
            err = self.stop_session(sid)
            if err:
                stop_failures[agent["agent_id"]] = err
        result = core.disable_team(plan["team_slug"], cascade=cascade)
        result.update(
            harness=self.name,
            status="disabled",
            stop_failures=stop_failures,
            missing_session_ids=missing_session_ids,
            next_steps=[],
        )
        return result

    def core_cmd(self, core: "UltronCore") -> str:
        return f'python3 "{core.repo_root / "ultron" / "core" / "core.py"}"'

    def role_paths(self, core: "UltronCore", ctx: Mapping[str, Any]) -> Tuple[str, str, str]:
        role_dir = ctx["role_dir"].resolve()
        return str(role_dir), str(role_dir / "workspace"), str(role_dir)

    def doorbell_address(self, ctx: Mapping[str, Any]) -> str:
        return f"`{session_name_for(ctx['agent_id'])}` (your session name)"

    def doorbell_call(self) -> str:
        return "call `SendMessage` with that address as `to`"

    def charters_block(self, ctx: Mapping[str, Any]) -> str:
        return "\nYour team, ancestor and role charters are already loaded from the `AGENTS.md` files in your folder chain."

    def target_repo_summary(self, core: "UltronCore", ctx: Mapping[str, Any]) -> str:
        repo, repo_abs = ctx["target_repo"], ctx["target_repo_abs"]
        if not (repo and repo_abs):
            return f"Local ULTRON Repository (`{core.repo_root}`)"
        t = self.tools
        _, guidelines_note = detect_target_repo_guidelines(repo_abs)
        return (
            f"`{repo_abs}` (configured as `{repo}`)\n"
            f"  - **Dual-Directory Execution Rule:** Your shell sessions start in your role folder (`{ctx['role_dir'].resolve()}`).\n"
            f"  - Run all project build, test, and Git commands inside the target repository: `cd \"{repo_abs}\" && <command>`.\n"
            f"  - Pass absolute paths under `{repo_abs}/...` to `{t['read']}`, `{t['edit']}`, `{t['write']}`, `{t['grep']}` and `{t['find']}`.\n"
            f"{guidelines_note}"
        )

    def build_spec(self, core: "UltronCore", ctx: Mapping[str, Any]) -> Dict[str, Any]:
        r, team, aid = ctx["role"], ctx["team"], ctx["agent_id"]
        role_dir = ctx["role_dir"]
        session_name = session_name_for(aid)
        role_context = self.render_role_context(core, ctx)
        boot_prompt = (
            f"Boot sequence for `{aid}` ({r['title']}): run the Mandatory Startup Hydration "
            f"commands from your role context.\n"
        )
        if ctx["mission_brief"]:
            boot_prompt += f"Initial directive: {ctx['mission_brief']}\n"
        else:
            boot_prompt += "Then await doorbelled tasks on the board; end your turn without polling."
        return {
            "agent_id": aid,
            "team_slug": ctx["team_slug"],
            "role": r["role"],
            "read_only_mode": ctx["read_only"],
            "target_repo": ctx["target_repo"],
            "target_repo_abs": ctx["target_repo_abs"],
            "role_dir": str(role_dir.resolve()),
            "session_name": session_name,
            "model_tier": r["model"],
            "claude_model": "" if r["model"] == "inherit" else self.model_for_tier.get(r["model"], r["model"]),
            "workspace_mode": team["workspace_mode"],
            "role_context": role_context,
            "initial_prompt": boot_prompt,
        }


HARNESS_ADAPTERS = {a.name: a for a in (AntigravityAdapter(), ClaudeCodeAdapter())}


def resolve_harness(explicit: Optional[str] = None, core: Optional["UltronCore"] = None) -> str:
    chosen = (explicit or os.environ.get(HARNESS_ENV, "")).strip()
    if not chosen and any(os.environ.get(v) for v in ANTIGRAVITY_ENV_MARKERS):
        chosen = "antigravity"
    if not chosen and os.environ.get("CLAUDE_CODE_SESSION_ID"):
        chosen = "claude-code"
    if not chosen and core is not None:
        chosen = core.get_prime_harness()
    if not chosen:
        raise ValueError(
            f"Cannot tell which harness runs ULTRON. Pass --harness or set {HARNESS_ENV} "
            f"(one of {sorted(HARNESS_ADAPTERS)})."
        )
    harness_adapter(chosen)
    return chosen


def resolve_harness_or_blank(explicit: Optional[str] = None, core: Optional["UltronCore"] = None) -> str:
    if explicit:
        return resolve_harness(explicit)
    try:
        return resolve_harness(None, core)
    except ValueError:
        return ""


def harness_adapter(harness: str) -> HarnessAdapter:
    if harness not in HARNESS_ADAPTERS:
        raise ValueError(f"Unknown harness '{harness}'. Must be one of {sorted(HARNESS_ADAPTERS)}.")
    return HARNESS_ADAPTERS[harness]


class UltronCore:
    def __init__(
        self,
        repo_root: Optional[Path | str] = None,
        hive_dir: Optional[Path | str] = None,
        threads_dir: Optional[Path | str] = None,
        runtime_dir: Optional[Path | str] = None,
        templates_dir: Optional[Path | str] = None,
        projects_dir: Optional[Path | str] = None,
        decisions_dir: Optional[Path | str] = None,
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
        self.projects_dir = Path(
            projects_dir or os.environ.get("ULTRON_PROJECTS_DIR") or (default_core / "projects")
        ).resolve()
        self.decisions_dir = Path(
            decisions_dir or os.environ.get("ULTRON_DECISIONS_DIR") or (default_core / "decisions")
        ).resolve()
        self.blueprints_dir = Path(
            os.environ.get("ULTRON_BLUEPRINTS_DIR") or (default_core / "blueprints")
        ).resolve()
        self._builtin_blueprints_dir = (CORE_DIR / "blueprints").resolve()

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
        and overlay ephemeral session bindings/statuses from .runtime/sessions.json.
        Returns (teams_by_slug, agents_by_id, sessions_data).
        """
        sessions = self._read_sessions_unlocked()
        live_agents = sessions["agents"]
        projects_by_slug = self._scan_projects_unlocked()

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
                "swarm_name": swarm_name_for(PRIME_ID),
                "harness": str(p_sess.get("harness", "")) if p_status == "active" else "",
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

            model = normalize_model(
                raw_t.get("default_model", DEFAULT_MODEL_TIER), f"'{t_manifest}'"
            )
            ws = str(raw_t.get("workspace_mode") or "inherit").strip().lower()
            if ws not in VALID_WORKSPACES:
                raise ValueError(f"Invalid workspace_mode '{ws}' in '{t_manifest}'.")
            team_harness = str(raw_t.get("harness") or "").strip()
            if team_harness and team_harness not in HARNESS_ADAPTERS:
                raise ValueError(f"Invalid harness '{team_harness}' in '{t_manifest}'.")

            lifespan = (
                str(raw_t.get("lifespan") or DEFAULT_TEAM_LIFESPAN).strip().lower()
                or DEFAULT_TEAM_LIFESPAN
            )
            if lifespan not in VALID_TEAM_LIFESPANS:
                raise ValueError(f"Invalid lifespan '{lifespan}' in '{t_manifest}'.")
            archived = bool(raw_t.get("archived", False))

            raw_project = str(raw_t.get("project") or "").strip().lower()
            inherited_project = (
                teams_by_slug[expected_parent]["project"]
                if expected_parent and expected_parent in teams_by_slug
                else ""
            )
            team_project = raw_project or inherited_project
            resolved_proj_obj = projects_by_slug.get(team_project) if team_project else None
            effective_proj_repo = (
                resolved_proj_obj["effective_target_path"] if resolved_proj_obj else ""
            )
            project_missing = bool(team_project and team_project not in projects_by_slug)

            curr_lineage = [*lineage, slug]
            hive_rel = self._rel_posix(team_dir)
            created_at = str(raw_t.get("created_at") or now_iso())
            updated_at = str(raw_t.get("updated_at") or created_at)
            raw_target_repo = str(raw_t.get("target_repo") or "").strip()
            inherited_target_repo = (
                teams_by_slug[expected_parent]["target_repo"]
                if expected_parent and expected_parent in teams_by_slug
                else ""
            )
            team_target_repo = (
                raw_target_repo or effective_proj_repo or inherited_target_repo
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
                    r_model = normalize_model(raw_r.get("model", model), f"'{r_manifest}'")

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
                        "swarm_name": swarm_name_for(aid),
                        "harness": str(sess.get("harness", "")) if r_status == "active" else "",
                        "target_repo": r_target_repo,
                        "target_repo_abs": r_target_repo_abs,
                        "team_slug": slug,
                        "title": str(raw_r.get("title") or "").strip(),
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
                "archived": archived,
                "blueprint": str(raw_t.get("blueprint") or "").strip(),
                "campaign": str(raw_t.get("campaign") or "off").strip().lower() or "off",
                "created_at": created_at,
                "default_model": model,
                "harness": team_harness,
                "hive_path": hive_rel,
                "layer": len(curr_lineage),
                "lifespan": lifespan,
                "lineage": curr_lineage,
                "mission": str(raw_t.get("mission") or "").strip(),
                "name": str(raw_t.get("name") or slug).strip(),
                "parent_team": expected_parent,
                "project": team_project,
                "project_missing": project_missing,
                "raw_project": raw_project,
                "raw_target_repo": raw_target_repo,
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
    # Projects Catalog (ultron/core/projects/<slug>.json)
    # ------------------------------------------------------------------

    def _scan_projects_unlocked(
        self, teams_by_slug: Optional[Mapping[str, Dict[str, Any]]] = None
    ) -> Dict[str, Dict[str, Any]]:
        raw_projects: Dict[str, Dict[str, Any]] = {}
        if self.projects_dir.is_dir():
            for p_file in sorted(self.projects_dir.glob("*.json")):
                if p_file.name.startswith("."):
                    continue
                try:
                    raw = json.loads(p_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Corrupt JSON in '{p_file}': {exc}") from exc
                if not isinstance(raw, dict):
                    raise ValueError(f"Invalid schema in '{p_file}': expected JSON object.")
                slug = validate_slug(str(raw.get("slug", "")), "project slug")
                if slug != p_file.stem:
                    raise ValueError(
                        f"Project file '{p_file.name}' mismatches slug '{slug}'."
                    )
                status = str(raw.get("status") or "active").strip().lower() or "active"
                if status not in VALID_PROJECT_STATUSES:
                    raise ValueError(f"Invalid status '{status}' in '{p_file}'.")
                raw_parent = (raw.get("parent_project") or "").strip().lower() or None
                if raw_parent:
                    validate_slug(raw_parent, "parent_project")
                rels_raw = raw.get("relationships", [])
                if not isinstance(rels_raw, list):
                    raise ValueError(f"Invalid relationships list in '{p_file}'.")
                rels: List[Dict[str, str]] = []
                for rel in rels_raw:
                    if not isinstance(rel, dict):
                        raise ValueError(f"Invalid relationship entry in '{p_file}'.")
                    r_type = str(rel.get("relation") or "").strip().lower()
                    if r_type not in VALID_PROJECT_RELATIONS:
                        raise ValueError(
                            f"Invalid relationship type '{r_type}' in '{p_file}'."
                        )
                    r_target = validate_slug(str(rel.get("target") or ""), "relationship target")
                    if r_target == slug:
                        raise ValueError(f"Project '{slug}' cannot link to itself.")
                    rels.append(
                        {
                            "note": str(rel.get("note") or "").strip(),
                            "relation": r_type,
                            "target": r_target,
                        }
                    )
                rels.sort(key=lambda item: (item["relation"], item["target"]))

                raw_projects[slug] = {
                    "created_at": str(raw.get("created_at") or now_iso()),
                    "description": str(raw.get("description") or "").strip(),
                    "name": str(raw.get("name") or slug).strip() or slug,
                    "parent_project": raw_parent,
                    "project_path": self._rel_posix(p_file),
                    "relationships": rels,
                    "repo_path": str(raw.get("repo_path") or "").strip(),
                    "slug": slug,
                    "status": status,
                    "subpath": normalize_project_subpath(str(raw.get("subpath") or "")),
                    "updated_at": str(raw.get("updated_at") or raw.get("created_at") or now_iso()),
                }

        # Validate parent existence + compute cycle-free lineage and cumulative paths
        lineages: Dict[str, List[str]] = {}

        def compute_lineage(slug: str, visiting: Set[str]) -> List[str]:
            if slug in lineages:
                return lineages[slug]
            if slug in visiting:
                raise ValueError(f"Cycle detected in project hierarchy at '{slug}'.")
            visiting.add(slug)
            p_obj = raw_projects[slug]
            parent = p_obj["parent_project"]
            if parent:
                if parent not in raw_projects:
                    raise ValueError(
                        f"Project '{slug}' references missing parent_project '{parent}'."
                    )
                lin = [*compute_lineage(parent, visiting), slug]
            else:
                lin = [slug]
            visiting.remove(slug)
            lineages[slug] = lin
            return lin

        projects_by_slug: Dict[str, Dict[str, Any]] = {}
        for slug in sorted(raw_projects):
            lin = compute_lineage(slug, set())
            base_repo = ""
            segments: List[str] = []
            for anc_slug in lin:
                anc = raw_projects[anc_slug]
                if anc["repo_path"]:
                    base_repo = anc["repo_path"]
                    segments = []
                if anc["subpath"] and base_repo:
                    segments.append(anc["subpath"])
            effective_target = (
                f"{base_repo.rstrip('/\\\\')}/{'/'.join(segments)}"
                if base_repo and segments
                else base_repo
            )
            p_data = dict(raw_projects[slug])
            p_data.update(
                {
                    "effective_repo_path": base_repo,
                    "effective_target_path": effective_target,
                    "layer": len(lin),
                    "lineage": lin,
                    "subprojects": [],
                    "target_path_abs": self._resolve_target_repo(effective_target),
                    "teams": [],
                }
            )
            projects_by_slug[slug] = p_data

        for slug in sorted(projects_by_slug):
            p_obj = projects_by_slug[slug]
            parent = p_obj["parent_project"]
            if parent and parent in projects_by_slug:
                projects_by_slug[parent]["subprojects"].append(
                    {"name": p_obj["name"], "slug": slug, "status": p_obj["status"]}
                )

        if teams_by_slug:
            for t_slug in sorted(teams_by_slug):
                t_obj = teams_by_slug[t_slug]
                p_slug = t_obj.get("project") or ""
                if p_slug and p_slug in projects_by_slug and not t_obj.get("archived", False):
                    projects_by_slug[p_slug]["teams"].append(
                        {
                            "lifespan": t_obj.get("lifespan", "permanent"),
                            "name": t_obj["name"],
                            "slug": t_slug,
                            "status": t_obj["status"],
                        }
                    )

        return projects_by_slug

    @staticmethod
    def _project_descendants(
        projects_by_slug: Mapping[str, Dict[str, Any]], root_slug: str
    ) -> List[str]:
        descendants: List[str] = []
        queue = [root_slug]
        seen: Set[str] = {root_slug}
        while queue:
            curr = queue.pop(0)
            children = sorted(
                s for s, p in projects_by_slug.items() if p["parent_project"] == curr
            )
            for child in children:
                if child not in seen:
                    seen.add(child)
                    descendants.append(child)
                    queue.append(child)
        return descendants

    def create_project(
        self,
        slug: str,
        name: str,
        description: str = "",
        repo_path: str = "",
        subpath: str = "",
        parent_project: Optional[str] = None,
        status: str = "active",
    ) -> Dict[str, Any]:
        clean_slug = validate_slug(slug, "project slug")
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Project name cannot be empty.")
        clean_status = (status or "active").strip().lower()
        if clean_status not in VALID_PROJECT_STATUSES:
            raise ValueError(
                f"Invalid project status '{status}'. Must be one of {sorted(VALID_PROJECT_STATUSES)}."
            )
        clean_subpath = normalize_project_subpath(subpath)
        clean_parent = (
            validate_slug(parent_project, "parent_project")
            if parent_project and parent_project.strip()
            else None
        )
        if clean_parent == clean_slug:
            raise ValueError(f"Project '{clean_slug}' cannot be its own parent.")

        iso = now_iso()
        with self._lock(exclusive=True):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            projects = self._scan_projects_unlocked(teams_by_slug)
            if clean_slug in projects:
                raise ValueError(f"Project '{clean_slug}' already exists.")
            if clean_parent:
                p_obj = projects.get(clean_parent)
                if not p_obj:
                    raise ValueError(f"Parent project '{clean_parent}' does not exist.")
                if p_obj["status"] == "archived":
                    raise ValueError(
                        f"Cannot attach subproject '{clean_slug}' under archived project '{clean_parent}'."
                    )

            self.projects_dir.mkdir(parents=True, exist_ok=True)
            manifest: Dict[str, Any] = {
                "created_at": iso,
                "description": (description or "").strip(),
                "name": clean_name,
                "parent_project": clean_parent,
                "relationships": [],
                "repo_path": (repo_path or "").strip(),
                "slug": clean_slug,
                "status": clean_status,
                "subpath": clean_subpath,
                "updated_at": iso,
            }
            atomic_write_json(self.projects_dir / f"{clean_slug}.json", manifest)
            return self._scan_projects_unlocked(teams_by_slug)[clean_slug]

    def update_project(
        self,
        slug: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        repo_path: Optional[str] = None,
        subpath: Optional[str] = None,
        parent_project: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        clean_slug = validate_slug(slug, "project slug")
        iso = now_iso()
        with self._lock(exclusive=True):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            projects = self._scan_projects_unlocked(teams_by_slug)
            existing = projects.get(clean_slug)
            if not existing:
                raise ValueError(f"Project '{clean_slug}' does not exist.")

            p_file = self.projects_dir / f"{clean_slug}.json"
            raw = json.loads(p_file.read_text(encoding="utf-8"))

            if name is not None:
                clean_name = name.strip()
                if not clean_name:
                    raise ValueError("Project name cannot be empty.")
                raw["name"] = clean_name
            if description is not None:
                raw["description"] = description.strip()
            if repo_path is not None:
                raw["repo_path"] = repo_path.strip()
            if subpath is not None:
                raw["subpath"] = normalize_project_subpath(subpath)
            if parent_project is not None:
                clean_parent = (
                    validate_slug(parent_project, "parent_project")
                    if parent_project.strip()
                    else None
                )
                if clean_parent == clean_slug:
                    raise ValueError(f"Project '{clean_slug}' cannot be its own parent.")
                if clean_parent:
                    parent_obj = projects.get(clean_parent)
                    if not parent_obj:
                        raise ValueError(f"Parent project '{clean_parent}' does not exist.")
                    if parent_obj["status"] == "archived":
                        raise ValueError(
                            f"Cannot re-parent '{clean_slug}' under archived project '{clean_parent}'."
                        )
                    if clean_slug in parent_obj["lineage"]:
                        raise ValueError(
                            f"Cycle detected: cannot set '{clean_slug}' parent_project to descendant '{clean_parent}'."
                        )
                raw["parent_project"] = clean_parent
            if status is not None:
                clean_status = status.strip().lower()
                if clean_status not in VALID_PROJECT_STATUSES:
                    raise ValueError(
                        f"Invalid project status '{status}'. Must be one of {sorted(VALID_PROJECT_STATUSES)}."
                    )
                if clean_status == "archived":
                    active_kids = [
                        c["slug"] for c in existing["subprojects"] if c["status"] != "archived"
                    ]
                    if active_kids:
                        raise ValueError(
                            f"Cannot archive project '{clean_slug}': non-archived subprojects exist ({active_kids})."
                        )
                else:
                    eff_parent = raw.get("parent_project")
                    if eff_parent and projects[eff_parent]["status"] == "archived":
                        raise ValueError(
                            f"Cannot set project '{clean_slug}' to '{clean_status}' under archived parent project '{eff_parent}'."
                        )
                raw["status"] = clean_status

            raw["updated_at"] = iso
            atomic_write_json(p_file, raw)
            return self._scan_projects_unlocked(teams_by_slug)[clean_slug]

    def link_projects(
        self,
        source_slug: str,
        target_slug: str,
        relation: str = "depends_on",
        note: str = "",
        unlink: bool = False,
    ) -> Dict[str, Any]:
        src = validate_slug(source_slug, "source project")
        tgt = validate_slug(target_slug, "target project")
        if src == tgt:
            raise ValueError(f"Project '{src}' cannot link to itself.")
        clean_rel = (relation or "depends_on").strip().lower()
        if clean_rel not in VALID_PROJECT_RELATIONS:
            raise ValueError(
                f"Invalid relationship '{relation}'. Must be one of {sorted(VALID_PROJECT_RELATIONS)}."
            )

        with self._lock(exclusive=True):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            projects = self._scan_projects_unlocked(teams_by_slug)
            if src not in projects:
                raise ValueError(f"Source project '{src}' does not exist.")
            if tgt not in projects:
                raise ValueError(f"Target project '{tgt}' does not exist.")

            p_file = self.projects_dir / f"{src}.json"
            raw = json.loads(p_file.read_text(encoding="utf-8"))
            rels = [
                r
                for r in raw.get("relationships", [])
                if not (r.get("target") == tgt and r.get("relation") == clean_rel)
            ]
            if not unlink:
                rels.append({"note": (note or "").strip(), "relation": clean_rel, "target": tgt})
            rels.sort(key=lambda item: (item["relation"], item["target"]))
            raw["relationships"] = rels
            raw["updated_at"] = now_iso()
            atomic_write_json(p_file, raw)
            return self._scan_projects_unlocked(teams_by_slug)[src]

    def get_project(self, slug: str) -> Optional[Dict[str, Any]]:
        clean = validate_slug(slug, "project slug")
        with self._lock(exclusive=False):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            return self._scan_projects_unlocked(teams_by_slug).get(clean)

    def list_projects(
        self,
        status: Optional[str] = None,
        parent_project: Optional[str] = None,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        st: Optional[str] = None
        if status:
            st = status.strip().lower()
            if st not in VALID_PROJECT_STATUSES:
                raise ValueError(f"Invalid project status '{status}'.")
        clean_parent = (
            validate_slug(parent_project, "parent_project") if parent_project else None
        )

        with self._lock(exclusive=False):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            projects = self._scan_projects_unlocked(teams_by_slug)

        items = [
            p
            for p in projects.values()
            if (st is not None and p["status"] == st)
            or (st is None and (include_archived or p["status"] != "archived"))
        ]
        if clean_parent:
            items = [p for p in items if p["parent_project"] == clean_parent]
        items.sort(key=lambda item: (item["layer"], item["slug"]))
        return items

    def remove_project(self, slug: str, cascade: bool = False) -> Dict[str, Any]:
        clean = validate_slug(slug, "project slug")
        with self._lock(exclusive=True):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            projects = self._scan_projects_unlocked(teams_by_slug)
            if clean not in projects:
                raise ValueError(f"Project '{clean}' does not exist.")
            descendants = self._project_descendants(projects, clean)
            if descendants and not cascade:
                raise ValueError(
                    f"Cannot remove project '{clean}': subprojects exist ({descendants}). "
                    f"Re-run with --cascade to remove the entire subtree."
                )
            target_slugs = [clean, *descendants]
            target_set = set(target_slugs)

            bound_teams = sorted(
                t_slug
                for t_slug, t_obj in teams_by_slug.items()
                if t_obj.get("project") in target_set
            )
            if bound_teams:
                raise ValueError(
                    f"Cannot remove project(s) {target_slugs}: team(s) {bound_teams} are still bound to them. "
                    f"Run set-project --clear or remove-team first."
                )

            for rem_slug in target_slugs:
                (self.projects_dir / f"{rem_slug}.json").unlink(missing_ok=True)

            pruned_from: List[str] = []
            for surv_slug in sorted(set(projects) - target_set):
                p_file = self.projects_dir / f"{surv_slug}.json"
                if not p_file.is_file():
                    continue
                raw = json.loads(p_file.read_text(encoding="utf-8"))
                orig_rels = raw.get("relationships", [])
                filtered_rels = [r for r in orig_rels if r.get("target") not in target_set]
                if len(filtered_rels) != len(orig_rels):
                    raw["relationships"] = filtered_rels
                    raw["updated_at"] = now_iso()
                    atomic_write_json(p_file, raw)
                    pruned_from.append(surv_slug)

            return {"pruned_relationships_in": pruned_from, "removed_projects": target_slugs}

    # ------------------------------------------------------------------
    # Blueprint Discovery & Authoring (ultron/core/blueprints/)
    # ------------------------------------------------------------------

    def _load_blueprint_dir(self, bp_dir: Path) -> Dict[str, Any]:
        manifest_path = bp_dir / "blueprint.json"
        if not manifest_path.is_file():
            raise ValueError(f"Blueprint directory '{bp_dir}' is missing 'blueprint.json'.")
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt JSON in '{manifest_path}': {exc}") from exc

        slug = validate_slug(str(raw.get("slug", bp_dir.name)), "blueprint slug")
        if slug != bp_dir.name:
            raise ValueError(
                f"Blueprint folder '{bp_dir.name}' mismatches blueprint.json slug '{slug}'."
            )
        roles_raw = raw.get("roles", [])
        if not isinstance(roles_raw, list) or not roles_raw:
            raise ValueError(f"Blueprint '{slug}' must define a non-empty 'roles' list.")

        roles: List[Dict[str, Any]] = []
        seen_roles: Set[str] = set()
        for r in roles_raw:
            r_slug = validate_role_slug(str(r.get("role", "")))
            if r_slug in seen_roles:
                raise ValueError(f"Duplicate role '{r_slug}' in blueprint '{slug}'.")
            seen_roles.add(r_slug)
            r_model = normalize_model(
                r.get("default_model", DEFAULT_MODEL_TIER),
                f"role '{r_slug}' of blueprint '{slug}'",
            )
            tmpl_rel = str(r.get("template", f"roles/{r_slug}.md.tmpl")).strip()
            tmpl_path = (bp_dir / tmpl_rel).resolve()
            if not tmpl_path.is_file():
                raise ValueError(
                    f"Blueprint '{slug}' role '{r_slug}' is missing template file '{tmpl_rel}'."
                )
            roles.append(
                {
                    "default_model": r_model,
                    "mcp_tools": bool(r.get("mcp_tools", True)),
                    "responsibilities": str(r.get("responsibilities", "")).strip(),
                    "role": r_slug,
                    "template": tmpl_rel,
                    "title": str(r.get("title", r_slug)).strip(),
                    "write_tools": bool(r.get("write_tools", True)),
                }
            )
        if "lead" not in seen_roles:
            raise ValueError(f"Blueprint '{slug}' must include a 'lead' role.")

        team_tmpl = bp_dir / "team_agents.md.tmpl"
        if not team_tmpl.is_file():
            raise ValueError(
                f"Blueprint '{slug}' is missing 'team_agents.md.tmpl'."
            )

        return {
            "blueprint_path": str(bp_dir),
            "description": str(raw.get("description", "")).strip(),
            "name": str(raw.get("name", slug)).strip(),
            "role_names": [r["role"] for r in roles],
            "roles": roles,
            "slug": slug,
            "when_to_use": str(raw.get("when_to_use", "")).strip(),
            "workflow_summary": str(raw.get("workflow_summary", "")).strip(),
        }

    def list_blueprints(self) -> List[Dict[str, Any]]:
        by_slug: Dict[str, Dict[str, Any]] = {}
        search_dirs = [self._builtin_blueprints_dir]
        if self.blueprints_dir != self._builtin_blueprints_dir:
            search_dirs.append(self.blueprints_dir)
        for root_dir in search_dirs:
            if not root_dir.is_dir():
                continue
            for child in sorted(root_dir.iterdir()):
                if (
                    child.is_dir()
                    and not child.name.startswith(".")
                    and (child / "blueprint.json").is_file()
                ):
                    bp = self._load_blueprint_dir(child)
                    by_slug[bp["slug"]] = bp
        return [by_slug[k] for k in sorted(by_slug)]

    def get_blueprint(self, blueprint_slug: str) -> Dict[str, Any]:
        clean = validate_slug(blueprint_slug, "blueprint slug")
        for root_dir in (self.blueprints_dir, self._builtin_blueprints_dir):
            bp_dir = root_dir / clean
            if bp_dir.is_dir() and (bp_dir / "blueprint.json").is_file():
                return self._load_blueprint_dir(bp_dir)
        available = [b["slug"] for b in self.list_blueprints()]
        raise ValueError(
            f"Blueprint '{clean}' not found in '{self.blueprints_dir}'. Available: {available}"
        )

    def save_blueprint(
        self,
        team_slug: str,
        blueprint_slug: str,
        name: str,
        description: str,
        when_to_use: str = "",
        workflow_summary: str = "",
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Export an existing Hive team's roster and charters into a reusable blueprint."""
        clean_team = validate_slug(team_slug, "team slug")
        clean_bp = validate_slug(blueprint_slug, "blueprint slug")
        clean_name = name.strip()
        clean_desc = description.strip()
        if not clean_name:
            raise ValueError("Blueprint name cannot be empty.")
        if not clean_desc:
            raise ValueError("Blueprint description cannot be empty.")

        with self._lock(exclusive=True):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            team = teams_by_slug.get(clean_team)
            if not team:
                raise ValueError(f"Team '{clean_team}' does not exist.")

            bp_dir = self.blueprints_dir / clean_bp
            if bp_dir.exists() and not overwrite:
                raise ValueError(
                    f"Blueprint '{clean_bp}' already exists at '{bp_dir}'. Pass --overwrite to replace."
                )

            (bp_dir / "roles").mkdir(parents=True, exist_ok=True)
            team_dir = self._abs_from_rel(team["hive_path"])
            team_agents_src = (team_dir / "AGENTS.md").read_text(encoding="utf-8")

            # Parameterize team-specific literals back to template tokens
            target_display = team["target_repo"] or "Local ULTRON Repository (default)"
            parent_display = team["parent_team"] or f"{PRIME_ID} (Layer 1 root)"
            team_tmpl = (
                team_agents_src.replace(team["name"], "{{TEAM_NAME}}")
                .replace(team["mission"], "{{TEAM_MISSION}}")
                .replace(team["hive_path"], "{{HIVE_PATH}}")
                .replace(
                    f"- **Parent Team:** `{parent_display}`",
                    "- **Parent Team:** `{{PARENT_TEAM_DISPLAY}}`",
                )
                .replace(
                    f"- **Target Project Repository:** `{target_display}`",
                    "- **Target Project Repository:** `{{TARGET_REPO_DISPLAY}}`",
                )
                .replace(clean_team, "{{TEAM_SLUG}}")
            )
            (bp_dir / "team_agents.md.tmpl").write_text(team_tmpl, encoding="utf-8")

            bp_roles: List[Dict[str, Any]] = []
            for r in team["roles"]:
                r_slug = r["role"]
                r_dir = self._abs_from_rel(r["role_path"])
                r_ws_rel = self._rel_posix(r_dir / "workspace")
                r_src = (r_dir / "AGENTS.md").read_text(encoding="utf-8")
                r_tmpl = (
                    r_src.replace(r["title"], "{{ROLE_TITLE}}")
                    .replace(r["agent_id"], "{{AGENT_ID}}")
                    .replace(team["name"], "{{TEAM_NAME}}")
                    .replace(r_ws_rel, "{{ROLE_WORKSPACE_PATH}}")
                    .replace(r["responsibilities"], "{{RESPONSIBILITIES}}")
                    .replace(clean_team, "{{TEAM_SLUG}}")
                )
                rel_tmpl_path = f"roles/{r_slug}.md.tmpl"
                (bp_dir / rel_tmpl_path).write_text(r_tmpl, encoding="utf-8")
                bp_roles.append(
                    {
                        "default_model": r["model"],
                        "mcp_tools": bool(r["mcp_tools"]),
                        "responsibilities": r["responsibilities"],
                        "role": r_slug,
                        "template": rel_tmpl_path,
                        "title": r["title"],
                        "write_tools": bool(r["write_tools"]),
                    }
                )

            manifest = {
                "description": clean_desc,
                "name": clean_name,
                "roles": bp_roles,
                "slug": clean_bp,
                "when_to_use": when_to_use.strip() or f"Reusable team blueprint exported from '{clean_team}'.",
                "workflow_summary": workflow_summary.strip(),
            }
            atomic_write_json(bp_dir / "blueprint.json", manifest)
            return self._load_blueprint_dir(bp_dir)

    # ------------------------------------------------------------------
    # Org Graph & Team / Role Scaffolding
    # ------------------------------------------------------------------

    def register_prime(self, conversation_id: str, harness: str = "") -> Dict[str, Any]:
        if harness:
            harness_adapter(harness)
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
            if harness:
                sessions["agents"][PRIME_ID]["harness"] = harness
            self._write_sessions_unlocked(sessions)
            _, agents_by_id, _ = self._scan_state_unlocked()
            return agents_by_id[PRIME_ID]

    def create_team(
        self,
        slug: str,
        name: str = "",
        mission: str = "",
        parent_team: Optional[str] = None,
        default_model: str = DEFAULT_MODEL_TIER,
        workspace_mode: str = "inherit",
        lead_responsibilities: str = "",
        target_repo: str = "",
        blueprint: Optional[str] = None,
        harness: str = "",
        lifespan: str = DEFAULT_TEAM_LIFESPAN,
        project: str = "",
    ) -> Dict[str, Any]:
        clean_slug = validate_slug(slug, "team slug")
        clean_harness = harness_adapter(harness.strip()).name if harness.strip() else ""
        bp_obj = self.get_blueprint(blueprint) if blueprint else None
        clean_bp = bp_obj["slug"] if bp_obj else ""

        clean_name = name.strip() or (f"{bp_obj['name']} ({clean_slug})" if bp_obj else "")
        clean_mission = mission.strip()
        if not clean_name:
            raise ValueError("Team name cannot be empty.")
        if not clean_mission:
            raise ValueError("Team mission cannot be empty.")

        model = normalize_model(default_model)
        ws = workspace_mode.strip().lower()
        if ws not in VALID_WORKSPACES:
            raise ValueError(
                f"Invalid workspace_mode '{workspace_mode}'. Must be one of {sorted(VALID_WORKSPACES)}."
            )
        clean_lifespan = (lifespan or DEFAULT_TEAM_LIFESPAN).strip().lower()
        if clean_lifespan not in VALID_TEAM_LIFESPANS:
            raise ValueError(
                f"Invalid team lifespan '{lifespan}'. Must be one of {sorted(VALID_TEAM_LIFESPANS)}."
            )
        clean_project = validate_slug(project, "project slug") if (project or "").strip() else ""

        clean_parent = validate_slug(parent_team, "parent_team") if parent_team else None
        clean_target_repo = (target_repo or "").strip()
        iso = now_iso()

        with self._lock(exclusive=True):
            teams_by_slug, _, sessions = self._scan_state_unlocked()
            projects_by_slug = self._scan_projects_unlocked(teams_by_slug)
            if clean_slug in teams_by_slug:
                raise ValueError(f"Team '{clean_slug}' already exists.")
            if clean_project and clean_project not in projects_by_slug:
                raise ValueError(f"Project '{clean_project}' does not exist.")

            stale_keys = [
                k for k in sessions["agents"] if k.startswith(f"{clean_slug}/")
            ]
            if stale_keys:
                for k in stale_keys:
                    sessions["agents"].pop(k, None)
                self._write_sessions_unlocked(sessions)

            parent_target_repo = ""
            parent_project = ""
            if clean_parent:
                parent_obj = teams_by_slug.get(clean_parent)
                if not parent_obj:
                    raise ValueError(f"Parent team '{clean_parent}' does not exist.")
                parent_abs = self._abs_from_rel(parent_obj["hive_path"])
                team_dir = parent_abs / "teams" / clean_slug
                layer = parent_obj["layer"] + 1
                parent_target_repo = parent_obj.get("target_repo", "")
                parent_project = parent_obj.get("project", "")
            else:
                team_dir = self.hive_dir / clean_slug
                layer = 1

            hive_rel = self._rel_posix(team_dir)
            (team_dir / "teams").mkdir(parents=True, exist_ok=True)
            (team_dir / "teams" / ".gitkeep").touch(exist_ok=True)

            effective_project = clean_project or parent_project
            proj_target_repo = (
                projects_by_slug[effective_project]["effective_target_path"]
                if effective_project and effective_project in projects_by_slug
                else ""
            )
            display_target_repo = clean_target_repo or proj_target_repo or parent_target_repo
            target_repo_display = (
                display_target_repo
                if display_target_repo
                else "Local ULTRON Repository (default)"
            )
            parent_display = clean_parent or f"{PRIME_ID} (Layer 1 root)"

            if bp_obj:
                bp_dir = Path(bp_obj["blueprint_path"])
                team_tmpl_text = (bp_dir / "team_agents.md.tmpl").read_text(encoding="utf-8")
            else:
                team_tmpl_text = self._load_template("team_agents.md.tmpl")

            team_agents_md = render_template(
                team_tmpl_text,
                {
                    "TEAM_NAME": clean_name,
                    "TEAM_MISSION": clean_mission,
                    "TEAM_SLUG": clean_slug,
                    "PARENT_TEAM_DISPLAY": parent_display,
                    "HIVE_PATH": hive_rel,
                    "TARGET_REPO_DISPLAY": target_repo_display,
                },
            )
            team_agents_path = team_dir / "AGENTS.md"
            if not team_agents_path.exists():
                team_agents_path.write_text(team_agents_md, encoding="utf-8")

            team_manifest: Dict[str, Any] = {
                "blueprint": clean_bp,
                "campaign": "off",
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
            if clean_lifespan != DEFAULT_TEAM_LIFESPAN:
                team_manifest["lifespan"] = clean_lifespan
            if clean_project:
                team_manifest["project"] = clean_project
            if clean_harness:
                team_manifest["harness"] = clean_harness
            atomic_write_json(team_dir / "team.json", team_manifest)

            if bp_obj:
                bp_dir = Path(bp_obj["blueprint_path"])
                for r_spec in bp_obj["roles"]:
                    r_slug = r_spec["role"]
                    r_dir = team_dir / "roles" / r_slug
                    r_rel = self._rel_posix(r_dir)
                    r_ws_rel = self._rel_posix(r_dir / "workspace")
                    (r_dir / "workspace").mkdir(parents=True, exist_ok=True)
                    (r_dir / "workspace" / ".gitkeep").touch(exist_ok=True)

                    r_id = f"{clean_slug}/{r_slug}"
                    r_title = r_spec["title"]
                    if r_slug == "lead" and lead_responsibilities.strip():
                        r_resp = lead_responsibilities.strip()
                    else:
                        r_resp = r_spec["responsibilities"]

                    r_tmpl_text = (bp_dir / r_spec["template"]).read_text(encoding="utf-8")
                    r_md = render_template(
                        r_tmpl_text,
                        {
                            "ROLE_TITLE": r_title,
                            "AGENT_ID": r_id,
                            "TEAM_NAME": clean_name,
                            "TEAM_SLUG": clean_slug,
                            "ROLE_SLUG": r_slug,
                            "ROLE_WORKSPACE_PATH": r_ws_rel,
                            "RESPONSIBILITIES": r_resp,
                        },
                    )
                    r_agents_path = r_dir / "AGENTS.md"
                    if not r_agents_path.exists():
                        r_agents_path.write_text(with_role_context_import(r_md), encoding="utf-8")

                    r_model = model if model != DEFAULT_MODEL_TIER else r_spec["default_model"]
                    r_manifest: Dict[str, Any] = {
                        "agent_id": r_id,
                        "mcp_tools": bool(r_spec["mcp_tools"]),
                        "model": r_model,
                        "registered_at": iso,
                        "responsibilities": r_resp,
                        "role": r_slug,
                        "role_path": r_rel,
                        "team_slug": clean_slug,
                        "title": r_title,
                        "write_tools": bool(r_spec["write_tools"]),
                    }
                    atomic_write_json(r_dir / "role.json", r_manifest)
            else:
                lead_dir = team_dir / "roles" / "lead"
                lead_rel = self._rel_posix(lead_dir)
                lead_ws_rel = self._rel_posix(lead_dir / "workspace")
                (lead_dir / "workspace").mkdir(parents=True, exist_ok=True)
                (lead_dir / "workspace" / ".gitkeep").touch(exist_ok=True)

                lead_id = f"{clean_slug}/lead"
                lead_title = f"{clean_name} Team Leader"
                lead_resp = (
                    lead_responsibilities.strip()
                    or f"Coordinate internal execution for '{clean_name}' ({clean_slug}) and serve as sole external communication bridge along the ULTRON hierarchy."
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
                lead_agents_path = lead_dir / "AGENTS.md"
                if not lead_agents_path.exists():
                    lead_agents_path.write_text(with_role_context_import(lead_role_md), encoding="utf-8")

                role_manifest = {
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

            chosen_model = normalize_model(model or team_obj["default_model"])

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
                role_agents_path.write_text(with_role_context_import(member_md), encoding="utf-8")

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

    def set_team_harness(self, team_slug: str, harness: str = "") -> Dict[str, Any]:
        clean_team = validate_slug(team_slug, "team slug")
        clean_harness = harness_adapter(harness.strip()).name if harness.strip() else ""
        with self._lock(exclusive=True):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            team_obj = teams_by_slug.get(clean_team)
            if not team_obj:
                raise ValueError(f"Team '{clean_team}' does not exist.")
            if team_obj["status"] == "active":
                raise ValueError(f"Team '{clean_team}' is active. Run stop-team before changing its harness.")
            manifest_path = self._abs_from_rel(team_obj["hive_path"]) / "team.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if clean_harness:
                manifest["harness"] = clean_harness
            else:
                manifest.pop("harness", None)
            manifest["updated_at"] = now_iso()
            atomic_write_json(manifest_path, manifest)
            teams_after, _, _ = self._scan_state_unlocked()
            return teams_after[clean_team]

    def set_model(
        self, team_slug: str, model: str, role: Optional[str] = None
    ) -> Dict[str, Any]:
        clean_team = validate_slug(team_slug, "team slug")
        clean_model = normalize_model(model)
        clean_role = validate_role_slug(role) if role else None
        iso = now_iso()
        with self._lock(exclusive=True):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            team_obj = teams_by_slug.get(clean_team)
            if not team_obj:
                raise ValueError(f"Team '{clean_team}' does not exist.")
            team_dir = self._abs_from_rel(team_obj["hive_path"])
            if clean_role:
                role_match = next(
                    (r for r in team_obj["roles"] if r["role"] == clean_role), None
                )
                if not role_match:
                    raise ValueError(
                        f"Role '{clean_role}' does not exist in team '{clean_team}'."
                    )
                role_manifest_path = self._abs_from_rel(role_match["role_path"]) / "role.json"
                role_manifest = json.loads(role_manifest_path.read_text(encoding="utf-8"))
                role_manifest["model"] = clean_model
                role_manifest["updated_at"] = iso
                atomic_write_json(role_manifest_path, role_manifest)
                _, agents_after, _ = self._scan_state_unlocked()
                return agents_after[f"{clean_team}/{clean_role}"]

            manifest_path = team_dir / "team.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["default_model"] = clean_model
            manifest["updated_at"] = iso
            atomic_write_json(manifest_path, manifest)
            for r_obj in team_obj["roles"]:
                r_manifest_path = self._abs_from_rel(r_obj["role_path"]) / "role.json"
                r_manifest = json.loads(r_manifest_path.read_text(encoding="utf-8"))
                r_manifest["model"] = clean_model
                r_manifest["updated_at"] = iso
                atomic_write_json(r_manifest_path, r_manifest)
            teams_after, _, _ = self._scan_state_unlocked()
            return teams_after[clean_team]

    def get_team(self, slug: str) -> Optional[Dict[str, Any]]:
        clean = validate_slug(slug, "team slug")
        with self._lock(exclusive=False):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            return teams_by_slug.get(clean)

    def set_team_lifespan(
        self,
        team_slug: str,
        lifespan: Optional[str] = None,
        archived: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Configure a team's lifespan ('permanent' | 'ephemeral') and optional archived state."""
        clean_team = validate_slug(team_slug, "team slug")
        clean_lifespan: Optional[str] = None
        if lifespan is not None:
            clean_lifespan = lifespan.strip().lower()
            if clean_lifespan not in VALID_TEAM_LIFESPANS:
                raise ValueError(
                    f"Invalid team lifespan '{lifespan}'. Must be one of {sorted(VALID_TEAM_LIFESPANS)}."
                )
        iso = now_iso()

        with self._lock(exclusive=True):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            team_obj = teams_by_slug.get(clean_team)
            if not team_obj:
                raise ValueError(f"Team '{clean_team}' does not exist.")
            if archived is True and team_obj["status"] == "active":
                raise ValueError(
                    f"Cannot archive active team '{clean_team}'. Run stop-team first."
                )
            manifest_path = self._abs_from_rel(team_obj["hive_path"]) / "team.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if clean_lifespan is not None:
                if clean_lifespan == DEFAULT_TEAM_LIFESPAN:
                    manifest.pop("lifespan", None)
                else:
                    manifest["lifespan"] = clean_lifespan
            if archived is True:
                manifest["archived"] = True
            elif archived is False:
                manifest.pop("archived", None)
            manifest["updated_at"] = iso
            atomic_write_json(manifest_path, manifest)
            teams_after, _, _ = self._scan_state_unlocked()
            return teams_after[clean_team]

    def set_team_project(
        self,
        team_slug: str,
        project_slug: str = "",
        cascade: bool = False,
    ) -> Dict[str, Any]:
        """Bind or clear a team's project (optionally cascading to descendant child teams)."""
        clean_team = validate_slug(team_slug, "team slug")
        clean_project = (
            validate_slug(project_slug, "project slug")
            if (project_slug or "").strip()
            else ""
        )
        iso = now_iso()

        with self._lock(exclusive=True):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            projects_by_slug = self._scan_projects_unlocked(teams_by_slug)
            team_obj = teams_by_slug.get(clean_team)
            if not team_obj:
                raise ValueError(f"Team '{clean_team}' does not exist.")
            if clean_project and clean_project not in projects_by_slug:
                raise ValueError(f"Project '{clean_project}' does not exist.")

            target_slugs = (
                [clean_team, *self._get_descendant_slugs(teams_by_slug, clean_team)]
                if cascade
                else [clean_team]
            )
            for t_slug in target_slugs:
                t_dir = self._abs_from_rel(teams_by_slug[t_slug]["hive_path"])
                t_manifest_path = t_dir / "team.json"
                t_manifest = json.loads(t_manifest_path.read_text(encoding="utf-8"))
                if clean_project:
                    t_manifest["project"] = clean_project
                else:
                    t_manifest.pop("project", None)
                t_manifest["updated_at"] = iso
                atomic_write_json(t_manifest_path, t_manifest)

            teams_after, _, _ = self._scan_state_unlocked()
            return teams_after[clean_team]

    def list_teams(
        self,
        status: Optional[str] = None,
        project: Optional[str] = None,
        lifespan: Optional[str] = None,
        include_archived: bool = False,
        archived_only: bool = False,
    ) -> List[Dict[str, Any]]:
        if status:
            st = status.strip().lower()
            if st not in VALID_TEAM_STATUSES:
                raise ValueError(f"Invalid status '{status}'.")
        else:
            st = None

        clean_project = (
            validate_slug(project, "project slug") if (project or "").strip() else None
        )
        clean_lifespan: Optional[str] = None
        if lifespan:
            clean_lifespan = lifespan.strip().lower()
            if clean_lifespan not in VALID_TEAM_LIFESPANS:
                raise ValueError(f"Invalid team lifespan '{lifespan}'.")

        with self._lock(exclusive=False):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            teams: List[Dict[str, Any]] = []
            for t in teams_by_slug.values():
                if archived_only:
                    if not t.get("archived", False):
                        continue
                elif not include_archived and t.get("archived", False):
                    continue
                if st is not None and t["status"] != st:
                    continue
                if clean_project is not None and t.get("project") != clean_project:
                    continue
                if clean_lifespan is not None and t.get("lifespan") != clean_lifespan:
                    continue
                teams.append(t)
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
    # Lifecycle Operations: Directory, Render-Spawn, Activate, Disable, Remove
    # ------------------------------------------------------------------

    def set_campaign(self, team_slug: str, state: str) -> Dict[str, Any]:
        """Set team campaign mode ('active' or 'off') for safety cron activation."""
        clean_team = validate_slug(team_slug, "team slug")
        st = state.strip().lower()
        if st in ("on", "active", "true", "1"):
            target_state = "active"
        elif st in ("off", "inactive", "false", "0"):
            target_state = "off"
        else:
            raise ValueError(f"Invalid campaign state '{state}'. Expected 'on' or 'off'.")

        with self._lock(exclusive=True):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            team_obj = teams_by_slug.get(clean_team)
            if not team_obj:
                raise ValueError(f"Team '{clean_team}' does not exist.")

            manifest_path = self._abs_from_rel(team_obj["hive_path"]) / "team.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["campaign"] = target_state
            manifest["updated_at"] = now_iso()
            atomic_write_json(manifest_path, manifest)
            teams_after, _, _ = self._scan_state_unlocked()
            return teams_after[clean_team]

    def directory(
        self,
        agent_id: Optional[str] = None,
        team_slug: Optional[str] = None,
        owns: Optional[str] = None,
        include_all: bool = False,
        no_probe: bool = False,
    ) -> Any:
        with self._lock(exclusive=False):
            teams_by_slug, agents_by_id, sessions = self._scan_state_unlocked()

        clean_aid = normalize_agent_id(agent_id) if agent_id else None
        if clean_aid and clean_aid not in agents_by_id:
            raise ValueError(f"Agent '{clean_aid}' is not registered.")

        clean_team = validate_slug(team_slug, "team slug") if team_slug else None
        clean_owns = owns.strip().lower() if owns else None

        liveness_map: Dict[str, str] = {}
        probe_error: Optional[str] = None
        if not no_probe:
            try:
                probe_res = self.probe_liveness(team_slug=clean_team)
                for a_id, p_info in probe_res.get("agents", {}).items():
                    liveness_map[a_id] = p_info.get("state", "unknown")
            except Exception as exc:
                probe_error = str(exc)

        prime_info = agents_by_id.get(PRIME_ID)

        results: List[Dict[str, Any]] = []

        for aid, agent in agents_by_id.items():
            t_slug = agent.get("team_slug")
            team = teams_by_slug.get(t_slug) if t_slug else None

            if clean_aid and aid != clean_aid:
                continue
            if clean_team and t_slug != clean_team:
                continue
            if team and team.get("archived", False) and not clean_aid and not clean_team:
                continue
            if not include_all and not clean_aid and agent.get("status") != "active":
                continue

            if clean_owns:
                charter_texts = [
                    agent.get("responsibilities", ""),
                    agent.get("title", ""),
                ]
                if team:
                    charter_texts.append(team.get("mission", ""))
                matched = any(clean_owns in txt.lower() for txt in charter_texts)
                if not matched:
                    continue

            superior: Optional[str] = None
            superior_status: Optional[str] = None
            superior_disabled: bool = False
            fallback_to_prime: bool = False
            prime_fallback: Optional[Dict[str, Any]] = None

            if aid == PRIME_ID:
                superior = "user"
                superior_status = "active"
                campaign = "off"
            elif agent["role"] == "lead":
                campaign = team.get("campaign", "off") if team else "off"
                if team and team.get("parent_team"):
                    parent_lead = f"{team['parent_team']}/lead"
                    parent_agent = agents_by_id.get(parent_lead)
                    superior = parent_lead
                    superior_status = parent_agent.get("status") if parent_agent else "disabled"
                    superior_disabled = bool(superior_status != "active")
                    fallback_to_prime = superior_disabled
                    prime_fallback = prime_info if fallback_to_prime else None
                else:
                    superior = PRIME_ID
                    prime_status = prime_info.get("status") if prime_info else "disabled"
                    superior_status = prime_status
                    superior_disabled = bool(prime_status != "active")
                    fallback_to_prime = False
                    prime_fallback = prime_info if superior_disabled else None
            else:
                campaign = team.get("campaign", "off") if team else "off"
                lead_id = f"{t_slug}/lead"
                lead_agent = agents_by_id.get(lead_id)
                superior = lead_id
                superior_status = lead_agent.get("status") if lead_agent else "disabled"
                superior_disabled = bool(superior_status != "active")
                fallback_to_prime = superior_disabled
                prime_fallback = prime_info if fallback_to_prime else None

            if agent.get("status") == "active":
                if aid == PRIME_ID:
                    running = "alive"
                else:
                    running = liveness_map.get(aid, "unknown")
            else:
                running = "gone"

            entry = {
                "agent_id": aid,
                "team": t_slug or ("HQ" if aid == PRIME_ID else None),
                "role": agent.get("role", "prime" if aid == PRIME_ID else "unknown"),
                "title": agent.get("title", ""),
                "harness": agent.get("harness", "") or (self.get_prime_harness() if aid == PRIME_ID else ""),
                "swarm_name": swarm_name_for(aid),
                "status": agent.get("status", "disabled"),
                "campaign": campaign,
                "running": running,
                "superior": superior,
                "superior_status": superior_status,
                "superior_disabled": superior_disabled,
                "fallback_to_prime": fallback_to_prime,
                "prime_fallback": prime_fallback,
                "parent_disabled_warning": superior_disabled,
                "mission": team.get("mission", "") if team else "",
                "responsibilities": agent.get("responsibilities", ""),
                "probe_error": probe_error,
            }
            results.append(entry)

        results.sort(
            key=lambda r: (
                0 if r["agent_id"] == PRIME_ID else 1,
                r["team"] or "",
                0 if r["role"] == "lead" else 1,
                r["role"],
            )
        )

        if clean_aid:
            return results[0]
        return results

    def render_spawn(
        self,
        team_slug: str,
        role: Optional[str] = None,
        mission_brief: str = "",
        harness: str = "antigravity",
    ) -> List[Dict[str, Any]]:
        adapter = harness_adapter(harness)
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
            projects_by_slug = self._scan_projects_unlocked(teams_by_slug)
            bound_proj = projects_by_slug.get(team.get("project") or "")
            proj_lineage = set(bound_proj["lineage"]) if bound_proj else set()
            team_lineage_set = set(lineage_slugs)
            all_decisions = self._load_all_decisions_unlocked()
            relevant_decisions = [
                d
                for d in all_decisions
                if d["review_status"] != "overruled"
                and (
                    d["scope"] == "global"
                    or (d["scope"] == "project" and d["project_slug"] in proj_lineage)
                    or (d["scope"] == "team" and d["team_slug"] in team_lineage_set)
                )
            ]
            project_decisions_block = self._format_spawn_context_block(
                bound_proj, relevant_decisions
            )

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
                routing_summary = (
                    f"- **Role Type:** Team Leader (`{aid}`)\n"
                    f"- **Report & Escalate UP to your superior:** query `directory {aid}`, or escalate to `{PRIME_ID}` if disabled.\n"
                    f"- **Orchestrate Within Your Team:** discover active teammates with `directory --team {clean_team}`.\n"
                    f"- **Cross-Team & Hierarchy Routing:** Doorbell any other team's lead directly. Reach another team's specialists through their lead. Find owners with `directory --owns <text>`. Query `directory` each time you route; never rely on an earlier answer.\n"
                    f"- **Cross-Team Board Rule:** Use `--visibility team --team {clean_team} --with-team <other-team>` for parent/child handoffs."
                )
            else:
                routing_summary = (
                    f"- **Role Type:** Specialist (`{aid}`)\n"
                    f"- **Collaborate Directly Within Your Team:** discover active teammates with `directory --team {clean_team}` (post on `--visibility team --team {clean_team}` and doorbell the next peer in your workflow directly).\n"
                    f"- **Escalate Blockers & Route External Comms Through Team Lead:** `{clean_team}/lead` (posting a global lesson on the ULTRON board is allowed and does not count as cross-team messaging).\n"
                    f"- **Strict External Boundary:** Never doorbell external teams or `{PRIME_ID}` directly."
                )

            specs.append(
                adapter.build_spec(
                    self,
                    {
                        "agent_id": aid,
                        "role": r,
                        "team": team,
                        "team_slug": clean_team,
                        "layer": layer,
                        "lineage_display": lineage_display,
                        "role_dir": role_dir,
                        "role_workspace_rel": role_ws_rel,
                        "role_charter": role_charter,
                        "inherited_charters": inherited_charters,
                        "project_decisions_block": project_decisions_block,
                        "routing_summary": routing_summary,
                        "read_only": not bool(r["write_tools"]),
                        "target_repo": r.get("target_repo") or "",
                        "target_repo_abs": r.get("target_repo_abs") or "",
                        "mission_brief": mission_brief.strip(),
                    },
                )
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

            if t_obj.get("archived", False):
                t_manifest_path = self._abs_from_rel(t_obj["hive_path"]) / "team.json"
                t_manifest = json.loads(t_manifest_path.read_text(encoding="utf-8"))
                if t_manifest.pop("archived", None) is not None:
                    t_manifest["updated_at"] = iso
                    atomic_write_json(t_manifest_path, t_manifest)

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
        session_ids: Optional[Mapping[str, str]] = None,
        harness: str = "",
    ) -> Dict[str, Any]:
        clean_team = validate_slug(team_slug, "team slug")
        if not role_uuids:
            raise ValueError("role_uuids mapping cannot be empty.")

        normalized_map: Dict[str, str] = {}
        for key, uuid_val in role_uuids.items():
            cid = str(uuid_val).strip()
            if not cid:
                raise ValueError(f"Empty doorbell address provided for '{key}'.")
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
                    f"Team activation for '{clean_team}' must include a 'lead' doorbell address (or 'lead' must already be active), "
                    f"or pass --allow-detached."
                )

            missing_roles = sorted(
                r_slug
                for r_slug, r_obj in existing_roles.items()
                if r_slug not in normalized_map and r_obj["status"] != "active"
            )
            if missing_roles and not partial:
                raise ValueError(
                    f"Missing doorbell address(es) for role(s) {missing_roles} in team '{clean_team}'. "
                    f"Provide every role's address or pass --partial."
                )

            if t_obj.get("archived", False):
                t_manifest_path = self._abs_from_rel(t_obj["hive_path"]) / "team.json"
                t_manifest = json.loads(t_manifest_path.read_text(encoding="utf-8"))
                if t_manifest.pop("archived", None) is not None:
                    t_manifest["updated_at"] = iso
                    atomic_write_json(t_manifest_path, t_manifest)

            for r_slug, cid in normalized_map.items():
                entry = {
                    "conversation_id": cid,
                    "last_seen": iso,
                    "status": "active",
                }
                if session_ids and session_ids.get(r_slug):
                    entry["session_id"] = session_ids[r_slug]
                if harness:
                    entry["harness"] = harness
                if harness == "antigravity":
                    entry["swarm_name"] = swarm_name_for(f"{clean_team}/{r_slug}")
                sessions["agents"][f"{clean_team}/{r_slug}"] = entry
            self._write_sessions_unlocked(sessions)
            teams_after, _, _ = self._scan_state_unlocked()
            return teams_after[clean_team]

    def spawn_team(
        self, team_slug: str, mission_brief: str = "", harness: Optional[str] = None
    ) -> Dict[str, Any]:
        clean_team = validate_slug(team_slug, "team slug")
        team = self.get_team(clean_team)
        if not team:
            raise ValueError(f"Team '{clean_team}' does not exist.")
        adapter = harness_adapter(resolve_harness(harness or team["harness"] or None, self))
        if team["status"] == "active":
            raise ValueError(f"Team '{clean_team}' is already active. Run stop-team first.")
        if team["parent_team"]:
            parent = self.get_team(team["parent_team"])
            if not parent or parent["status"] != "active":
                raise ValueError(
                    f"Cannot spawn team '{clean_team}': parent team '{team['parent_team']}' is not active."
                )
        prime_harness = self.get_prime_harness()
        if prime_harness and prime_harness != adapter.name and not adapter.launches_from_cli:
            raise ValueError(
                f"ULTRON PRIME runs on '{prime_harness}', which cannot launch '{adapter.name}' sessions. "
                f"Only a Prime on '{adapter.name}' can spawn team '{clean_team}'."
            )
        specs = self.render_spawn(clean_team, mission_brief=mission_brief, harness=adapter.name)
        return adapter.spawn(self, team, specs)

    def stop_team(
        self, team_slug: str, cascade: bool = False, harness: Optional[str] = None
    ) -> Dict[str, Any]:
        clean_team = validate_slug(team_slug, "team slug")
        plan = self.prepare_disable(clean_team, cascade=cascade)
        with self._lock(exclusive=False):
            sessions = self._read_sessions_unlocked()
        recorded = {
            str(sessions["agents"].get(a["agent_id"], {}).get("harness", "")) for a in plan["agents_to_kill"]
        } - {""}
        if harness:
            recorded.add(harness)
        if len(recorded) > 1:
            raise ValueError(
                f"Teams {plan['teams_affected']} run on more than one harness {sorted(recorded)}. "
                f"Stop the child teams first, one harness at a time."
            )
        adapter = harness_adapter(resolve_harness(next(iter(recorded), None), self))
        return adapter.stop(self, plan, sessions, cascade)

    def probe_liveness(self, team_slug: Optional[str] = None, harness: Optional[str] = None) -> Dict[str, Any]:
        fallback = resolve_harness_or_blank(harness, self)
        clean_team = validate_slug(team_slug, "team slug") if team_slug else None
        if clean_team and not self.get_team(clean_team):
            raise ValueError(f"Team '{clean_team}' does not exist.")
        with self._lock(exclusive=False):
            sessions = self._read_sessions_unlocked()
            teams_by_slug, _, _ = self._scan_state_unlocked()
        agents = {
            aid: entry
            for aid, entry in sessions["agents"].items()
            if aid != PRIME_ID
            and entry.get("status") == "active"
            and (clean_team is None or aid.split("/")[0] == clean_team)
        }
        groups: Dict[str, Dict[str, Mapping[str, Any]]] = {}
        for aid, entry in agents.items():
            groups.setdefault(str(entry.get("harness", "")) or fallback, {})[aid] = entry
        merged: Dict[str, Any] = {"harnesses": sorted(groups), "agents": {}, "next_steps": []}
        for name, group in sorted(groups.items()):
            res = harness_adapter(name).probe(group)
            merged["agents"].update(res["agents"])
            merged["next_steps"] += res["next_steps"]
        for aid, a_res in merged["agents"].items():
            t_slug = aid.split("/")[0] if "/" in aid else None
            t_obj = teams_by_slug.get(t_slug) if t_slug else None
            a_res["campaign"] = t_obj.get("campaign", "off") if t_obj else "off"
        return merged

    def doorbell(self, target_id: str, message: str, sender: str = "") -> Dict[str, Any]:
        target = self.get_agent(target_id)
        if not target:
            raise ValueError(f"Agent '{target_id}' is not registered.")
        if target["status"] != "active" or not target["conversation_id"]:
            raise ValueError(f"Agent '{target['agent_id']}' is DISABLED (no live doorbell address).")
        if not message.strip():
            raise ValueError("Doorbell message cannot be empty.")
        name = target["harness"] or self.get_prime_harness()
        if not name:
            raise ValueError(f"No harness recorded for '{target['agent_id']}'.")
        text = f"Doorbell from {normalize_agent_id(sender)}: {message}" if sender else message
        harness_adapter(name).shell_doorbell(target["conversation_id"], text)
        return {"agent_id": target["agent_id"], "harness": name, "address": target["conversation_id"]}

    def get_prime_harness(self) -> str:
        with self._lock(exclusive=False):
            sessions = self._read_sessions_unlocked()
        prime = sessions["agents"].get(PRIME_ID, {})
        return str(prime.get("harness", "")) if prime.get("status") == "active" else ""

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

    def disable_team(
        self, team_slug: str, cascade: bool = False, archive_ephemeral: bool = True
    ) -> Dict[str, Any]:
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
            archived_teams: List[str] = []
            if archive_ephemeral:
                for t_slug in plan["teams_affected"]:
                    t_obj = teams_by_slug[t_slug]
                    if t_obj.get("lifespan") == "ephemeral" and not t_obj.get("archived", False):
                        t_manifest_path = self._abs_from_rel(t_obj["hive_path"]) / "team.json"
                        t_manifest = json.loads(t_manifest_path.read_text(encoding="utf-8"))
                        t_manifest["archived"] = True
                        t_manifest["updated_at"] = iso
                        atomic_write_json(t_manifest_path, t_manifest)
                        archived_teams.append(t_slug)
            plan["archived_teams"] = archived_teams
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

        if limit is not None and limit <= 0:
            return []

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

    def export_thread(
        self,
        thread_id: str | int,
        format: str = "md",
        output_path: Optional[str | Path] = None,
        as_agent: Optional[str] = None,
        show_all: bool = False,
    ) -> str:
        """
        Export an accessible thread to Markdown or JSON format.

        Args:
            thread_id: Full thread ID, short prefix/suffix, or '#'-prefixed ID.
            format: Export format ('md' or 'json', case-insensitive, default: 'md').
            output_path: Optional destination file path. If specified, writes content to
                         path, creating parent directories if necessary.
            as_agent: Requesting agent ID for visibility validation.
            show_all: If True, bypass visibility restrictions.

        Returns:
            The exported string (Markdown or indented JSON).

        Raises:
            ValueError: If thread_id is not found, ambiguous, or format is unsupported.
            PermissionError: If as_agent is not authorized to access the thread.
        """
        fmt = str(format).strip().lower()
        if fmt not in ("md", "json"):
            raise ValueError(
                f"Invalid export format '{format}'. Supported formats: 'md', 'json'."
            )

        thread = self.get_thread(
            thread_id=thread_id,
            as_agent=as_agent,
            show_all=show_all,
        )
        if not thread:
            raise ValueError(f"Thread '{thread_id}' not found.")

        if fmt == "json":
            serialized = json.dumps(thread, indent=2, sort_keys=True)
        else:
            serialized = format_thread_markdown(thread)

        if output_path is not None and str(output_path).strip():
            out_path = Path(output_path).expanduser().resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(serialized, encoding="utf-8")

        return serialized

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

    # ------------------------------------------------------------------
    # Append-Only Prime Decisions Ledger (ultron/core/decisions/)
    # ------------------------------------------------------------------

    @staticmethod
    def _format_spawn_context_block(
        bound_project: Optional[Mapping[str, Any]],
        decisions: List[Dict[str, Any]],
    ) -> str:
        if not bound_project and not decisions:
            return ""
        lines: List[str] = ["\n---\n\n## Project & Prime Decisions Context"]
        if bound_project:
            lines.append(
                f"- **Assigned Project:** `{bound_project['slug']}` ({bound_project['name']})"
                + (
                    f" — `{bound_project['effective_target_path']}`"
                    if bound_project.get("effective_target_path")
                    else ""
                )
            )
            if bound_project.get("parent_project"):
                lines.append(
                    f"- **Project Lineage:** `{' -> '.join(bound_project.get('lineage', []))}`"
                )
            if bound_project.get("relationships"):
                rels = ", ".join(
                    f"{r['relation']}:{r['target']}" for r in bound_project["relationships"]
                )
                lines.append(f"- **Project Relationships:** {rels}")
        if decisions:
            lines.append("- **Active Prime Decisions (User-Guided & Autonomous Rulings):**")
            for d in decisions:
                scope_label = d["scope"]
                if d["scope"] == "project" and d.get("project_slug"):
                    scope_label = f"project:{d['project_slug']}"
                elif d["scope"] == "team" and d.get("team_slug"):
                    scope_label = f"team:{d['team_slug']}"
                lines.append(
                    f"  - `[{d['id']}]` **{d['title']}** ({scope_label} | {d['origin']} | `{d['review_status']}`): {d['decision']}"
                )
                if d.get("latest_review_notes") and d["review_status"] == "needs_improvement":
                    lines.append(f"    - *Review Note:* {d['latest_review_notes']}")
        return "\n".join(lines)

    def _ensure_decisions_dir_unlocked(self) -> None:
        self.decisions_dir.mkdir(parents=True, exist_ok=True)
        gitattr = self.decisions_dir / ".gitattributes"
        if not gitattr.exists():
            gitattr.write_text(
                "# Union-merge append-only JSONL Prime decision logs across Git branches without conflict\n"
                "*.jsonl merge=union\n",
                encoding="utf-8",
            )

    def _resolve_decision_path_unlocked(self, decision_ref: str) -> Optional[Path]:
        raw = str(decision_ref).strip()
        if raw.startswith("#"):
            raw = raw[1:].strip()
        if not raw or not self.decisions_dir.is_dir():
            return None
        clean = raw.lower()

        exact = self.decisions_dir / f"{clean}.jsonl"
        if exact.is_file():
            return exact

        matches: List[Path] = []
        for fpath in sorted(self.decisions_dir.glob("*.jsonl")):
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
                f"Ambiguous decision reference '{decision_ref}': matches {[m.stem for m in matches]}."
            )
        return None

    @staticmethod
    def _fold_decision_jsonl(fpath: Path) -> Dict[str, Any]:
        """Fold append-only JSONL decision & review events deterministically."""
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

        root_events = [e for e in events if e.get("type") == "decision"]
        if len(root_events) != 1:
            raise ValueError(
                f"Invalid decision file '{fpath.name}': expected exactly 1 root 'decision' event, found {len(root_events)}."
            )
        root = root_events[0]
        did = str(root.get("decision_id") or fpath.stem)
        created_at = str(root["created_at"])

        origin = str(root.get("origin") or "prime_autonomous").strip().lower()
        if origin not in VALID_DECISION_ORIGINS:
            raise ValueError(f"Invalid decision origin '{origin}' in '{fpath.name}'.")
        init_status = str(root.get("review_status") or "pending_review").strip().lower()
        if init_status not in VALID_DECISION_REVIEW_STATUSES:
            raise ValueError(f"Invalid review_status '{init_status}' in '{fpath.name}'.")
        scope = str(root.get("scope") or "global").strip().lower()
        if scope not in VALID_DECISION_SCOPES:
            raise ValueError(f"Invalid scope '{scope}' in '{fpath.name}'.")

        follow_ups = [e for e in events if e.get("type") != "decision"]
        follow_ups.sort(
            key=lambda e: (str(e.get("created_at") or ""), str(e.get("event_id") or ""))
        )

        original_decision = str(root.get("decision") or "")
        current_decision = original_decision
        current_status = init_status
        updated_at = created_at
        reviews: List[Dict[str, Any]] = []

        for ev in follow_ups:
            ev_type = ev.get("type")
            if ev_type != "review":
                raise ValueError(f"Unknown event type '{ev_type}' in '{fpath.name}'.")
            rev_status = str(ev.get("review_status") or "").strip().lower()
            if rev_status not in VALID_DECISION_REVIEW_STATUSES:
                raise ValueError(
                    f"Invalid review_status '{rev_status}' in '{fpath.name}'."
                )
            current_status = rev_status
            rep = str(ev.get("replacement_decision") or "").strip()
            if rep:
                current_decision = rep
            ev_ts = str(ev.get("created_at") or "")
            if ev_ts and ev_ts > updated_at:
                updated_at = ev_ts
            reviews.append(
                {
                    "created_at": ev_ts,
                    "event_id": str(ev.get("event_id") or ""),
                    "notes": str(ev.get("notes") or ""),
                    "replacement_decision": rep,
                    "review_status": rev_status,
                    "reviewer": str(ev.get("reviewer") or "user"),
                }
            )

        return {
            "created_at": created_at,
            "decided_by": str(root.get("decided_by") or PRIME_ID).lower(),
            "decision": current_decision,
            "decision_id": did,
            "id": did,
            "latest_review_notes": reviews[-1]["notes"] if reviews else "",
            "origin": origin,
            "original_decision": original_decision,
            "project_slug": str(root.get("project_slug") or ""),
            "rationale": str(root.get("rationale") or ""),
            "review_count": len(reviews),
            "review_status": current_status,
            "reviews": reviews,
            "scope": scope,
            "tags": str(root.get("tags") or ""),
            "team_slug": str(root.get("team_slug") or ""),
            "title": str(root.get("title") or ""),
            "updated_at": updated_at,
        }

    def _load_all_decisions_unlocked(self) -> List[Dict[str, Any]]:
        if not self.decisions_dir.is_dir():
            return []
        decisions = [
            self._fold_decision_jsonl(fpath)
            for fpath in sorted(self.decisions_dir.glob("*.jsonl"))
        ]
        decisions.sort(
            key=lambda d: (d["updated_at"], d["created_at"], d["id"]), reverse=True
        )
        return decisions

    def log_decision(
        self,
        title: str,
        decision: str,
        rationale: str = "",
        origin: str = "prime_autonomous",
        scope: Optional[str] = None,
        project_slug: Optional[str] = None,
        team_slug: Optional[str] = None,
        review_status: Optional[str] = None,
        decided_by: str = PRIME_ID,
        tags: str = "",
    ) -> Dict[str, Any]:
        clean_title = title.strip()
        clean_decision = decision.strip()
        if not clean_title:
            raise ValueError("Decision title cannot be empty.")
        if not clean_decision:
            raise ValueError("Decision text cannot be empty.")

        clean_origin = (origin or "prime_autonomous").strip().lower()
        if clean_origin not in VALID_DECISION_ORIGINS:
            raise ValueError(
                f"Invalid origin '{origin}'. Must be one of {sorted(VALID_DECISION_ORIGINS)}."
            )
        clean_actor = normalize_agent_id(decided_by or PRIME_ID)
        clean_proj = (
            validate_slug(project_slug, "project slug")
            if (project_slug or "").strip()
            else ""
        )
        clean_team = (
            validate_slug(team_slug, "team slug")
            if (team_slug or "").strip()
            else ""
        )

        clean_scope = (scope or "").strip().lower()
        if not clean_scope:
            clean_scope = "team" if clean_team else ("project" if clean_proj else "global")
        if clean_scope not in VALID_DECISION_SCOPES:
            raise ValueError(
                f"Invalid scope '{scope}'. Must be one of {sorted(VALID_DECISION_SCOPES)}."
            )

        if review_status:
            clean_status = review_status.strip().lower()
        else:
            clean_status = "approved" if clean_origin == "user_guided" else "pending_review"
        if clean_status not in VALID_DECISION_REVIEW_STATUSES:
            raise ValueError(
                f"Invalid review_status '{review_status}'. Must be one of {sorted(VALID_DECISION_REVIEW_STATUSES)}."
            )

        iso = now_iso()
        with self._lock(exclusive=True):
            teams_by_slug, _, _ = self._scan_state_unlocked()
            projects_by_slug = self._scan_projects_unlocked(teams_by_slug)

            if clean_scope == "global":
                if clean_proj or clean_team:
                    raise ValueError(
                        "Global decisions cannot specify --project or --team."
                    )
            elif clean_scope == "project":
                if not clean_proj:
                    raise ValueError("Project-scoped decisions require --project <slug>.")
                if clean_team:
                    raise ValueError("Project-scoped decisions cannot specify --team.")
                if clean_proj not in projects_by_slug:
                    raise ValueError(f"Project '{clean_proj}' does not exist.")
            elif clean_scope == "team":
                if not clean_team:
                    raise ValueError("Team-scoped decisions require --team <slug>.")
                if clean_team not in teams_by_slug:
                    raise ValueError(f"Team '{clean_team}' does not exist.")
                if (
                    not clean_proj
                    and teams_by_slug[clean_team].get("project")
                    and not teams_by_slug[clean_team].get("project_missing")
                ):
                    clean_proj = teams_by_slug[clean_team]["project"]
                elif clean_proj and clean_proj not in projects_by_slug:
                    raise ValueError(f"Project '{clean_proj}' does not exist.")

            self._ensure_decisions_dir_unlocked()
            did = generate_decision_id()
            while (self.decisions_dir / f"{did}.jsonl").exists():
                did = generate_decision_id()
            fpath = self.decisions_dir / f"{did}.jsonl"
            root_event = {
                "created_at": iso,
                "decided_by": clean_actor,
                "decision": clean_decision,
                "decision_id": did,
                "event_id": generate_event_id(),
                "origin": clean_origin,
                "project_slug": clean_proj,
                "rationale": (rationale or "").strip(),
                "review_status": clean_status,
                "scope": clean_scope,
                "tags": (tags or "").strip(),
                "team_slug": clean_team,
                "title": clean_title,
                "type": "decision",
            }
            append_jsonl_event(fpath, root_event)
            return self._fold_decision_jsonl(fpath)

    def review_decision(
        self,
        decision_ref: str,
        review_status: str,
        notes: str = "",
        replacement_decision: str = "",
        reviewer: str = "user",
    ) -> Dict[str, Any]:
        clean_status = (review_status or "").strip().lower()
        if clean_status not in VALID_DECISION_REVIEW_STATUSES:
            raise ValueError(
                f"Invalid review_status '{review_status}'. Must be one of {sorted(VALID_DECISION_REVIEW_STATUSES)}."
            )
        clean_reviewer = (reviewer or "user").strip() or "user"
        iso = now_iso()
        with self._lock(exclusive=True):
            fpath = self._resolve_decision_path_unlocked(decision_ref)
            if not fpath:
                raise ValueError(f"Decision '{decision_ref}' does not exist.")
            review_event = {
                "created_at": iso,
                "event_id": generate_event_id(),
                "notes": (notes or "").strip(),
                "replacement_decision": (replacement_decision or "").strip(),
                "review_status": clean_status,
                "reviewer": clean_reviewer,
                "type": "review",
            }
            append_jsonl_event(fpath, review_event)
            return self._fold_decision_jsonl(fpath)

    def get_decision(self, decision_ref: str) -> Optional[Dict[str, Any]]:
        with self._lock(exclusive=False):
            fpath = self._resolve_decision_path_unlocked(decision_ref)
            if not fpath:
                return None
            return self._fold_decision_jsonl(fpath)

    def list_decisions(
        self,
        review_status: Optional[str] = None,
        origin: Optional[str] = None,
        scope: Optional[str] = None,
        project_slug: Optional[str] = None,
        team_slug: Optional[str] = None,
        pending_only: bool = False,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        target_status = "pending_review" if pending_only else (
            review_status.strip().lower() if review_status else None
        )
        if pending_only and review_status and review_status.strip().lower() != "pending_review":
            raise ValueError("Cannot pass --pending together with a non-pending_review --status.")
        if target_status and target_status not in VALID_DECISION_REVIEW_STATUSES:
            raise ValueError(f"Invalid review_status '{review_status}'.")
        clean_origin = origin.strip().lower() if origin else None
        if clean_origin and clean_origin not in VALID_DECISION_ORIGINS:
            raise ValueError(f"Invalid origin '{origin}'.")
        clean_scope = scope.strip().lower() if scope else None
        if clean_scope and clean_scope not in VALID_DECISION_SCOPES:
            raise ValueError(f"Invalid scope '{scope}'.")
        clean_proj = validate_slug(project_slug, "project slug") if project_slug else None
        clean_team = validate_slug(team_slug, "team slug") if team_slug else None

        with self._lock(exclusive=False):
            decisions = self._load_all_decisions_unlocked()

        if limit is not None and limit <= 0:
            return []

        out: List[Dict[str, Any]] = []
        for d in decisions:
            if target_status and d["review_status"] != target_status:
                continue
            if clean_origin and d["origin"] != clean_origin:
                continue
            if clean_scope and d["scope"] != clean_scope:
                continue
            if clean_proj and d["project_slug"] != clean_proj:
                continue
            if clean_team and d["team_slug"] != clean_team:
                continue
            out.append(d)
            if len(out) >= limit:
                break
        return out

    def verify(self, prune_orphans: bool = False) -> Dict[str, Any]:
        """Validate integrity of Hive manifests, runtime sessions, JSONL threads, and .gitattributes."""
        with self._lock(exclusive=prune_orphans):
            teams_by_slug, agents_by_id, sessions = self._scan_state_unlocked()
            projects_by_slug = self._scan_projects_unlocked(teams_by_slug)
            for p_slug, p_obj in projects_by_slug.items():
                for rel in p_obj.get("relationships", []):
                    if rel["target"] not in projects_by_slug:
                        raise ValueError(
                            f"Project '{p_slug}' references unknown relationship target '{rel['target']}'."
                        )
            for slug, t_obj in teams_by_slug.items():
                if t_obj.get("project_missing"):
                    raise ValueError(
                        f"Team '{slug}' references missing project '{t_obj['project']}'."
                    )
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

            decisions = self._load_all_decisions_unlocked()
            if self.decisions_dir.is_dir():
                d_gitattr = self.decisions_dir / ".gitattributes"
                if not d_gitattr.is_file() or "merge=union" not in d_gitattr.read_text(encoding="utf-8"):
                    raise ValueError(
                        f"Missing '*.jsonl merge=union' in '{d_gitattr}'."
                    )

            return {
                "agents": len(agents_by_id),
                "decisions": len(decisions),
                "gitattributes_union_merge": has_union,
                "ok": True,
                "orphan_sessions": 0,
                "posts": sum(t["post_count"] for t in threads),
                "projects": len(projects_by_slug),
                "pruned_orphan_sessions": pruned_orphans,
                "teams": len(teams_by_slug),
                "threads": len(threads),
            }

    def get_stats(self) -> Dict[str, Any]:
        with self._lock(exclusive=False):
            teams_by_slug, agents_by_id, _ = self._scan_state_unlocked()
            projects_by_slug = self._scan_projects_unlocked(teams_by_slug)
            threads = self._load_all_threads_unlocked()
            decisions = self._load_all_decisions_unlocked()

        vis_counts: Dict[str, int] = {}
        cat_counts: Dict[str, int] = {}
        status_counts: Dict[str, int] = {}
        total_posts = 0
        for t in threads:
            total_posts += t["post_count"]
            vis_counts[t["visibility"]] = vis_counts.get(t["visibility"], 0) + 1
            cat_counts[t["category"]] = cat_counts.get(t["category"], 0) + 1
            status_counts[t["status"]] = status_counts.get(t["status"], 0) + 1

        non_archived_teams = [
            t for t in teams_by_slug.values() if not t.get("archived", False)
        ]
        return {
            "active_agents": sum(1 for a in agents_by_id.values() if a["status"] == "active"),
            "active_teams": sum(1 for t in non_archived_teams if t["status"] == "active"),
            "archived_teams": sum(1 for t in teams_by_slug.values() if t.get("archived", False)),
            "categories": cat_counts,
            "decisions_dir": str(self.decisions_dir),
            "ephemeral_teams": sum(1 for t in non_archived_teams if t.get("lifespan") == "ephemeral"),
            "hive_dir": str(self.hive_dir),
            "pending_decisions": sum(1 for d in decisions if d["review_status"] == "pending_review"),
            "permanent_teams": sum(1 for t in non_archived_teams if t.get("lifespan", DEFAULT_TEAM_LIFESPAN) == "permanent"),
            "projects_dir": str(self.projects_dir),
            "repo_root": str(self.repo_root),
            "sessions_file": str(self.sessions_file),
            "statuses": status_counts,
            "threads_dir": str(self.threads_dir),
            "total_agents": len(agents_by_id),
            "total_decisions": len(decisions),
            "total_posts": total_posts,
            "total_projects": len(projects_by_slug),
            "total_teams": len(non_archived_teams),
            "total_threads": len(threads),
            "visibilities": vis_counts,
        }


# ----------------------------------------------------------------------
# Human-Readable Formatters
# ----------------------------------------------------------------------


def format_org_tree(core: UltronCore, include_archived: bool = False) -> str:
    prime = core.get_agent(PRIME_ID)
    teams = core.list_teams(include_archived=include_archived)
    prime_state = (
        f"ACTIVE ({prime['conversation_id']})"
        if prime and prime["status"] == "active" and prime["conversation_id"]
        else "UNREGISTERED"
    )
    lines = [f"[ULTRON HIVE] {PRIME_ID.upper()} [{prime_state}]"]
    if not teams:
        lines.append("  └── (No teams created in ultron/hive/ yet)")
        return "\n".join(lines)

    visible_slugs = {t["slug"] for t in teams}
    by_parent: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for t in teams:
        p_key = t["parent_team"] if t["parent_team"] in visible_slugs else None
        by_parent.setdefault(p_key, []).append(t)

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
            bp_suffix = f" blueprint={t['blueprint']}" if t.get("blueprint") else ""
            proj_suffix = f" project={t['project']}" if t.get("project") else ""
            life_suffix = f" lifespan={t['lifespan']}" if t.get("lifespan") == "ephemeral" else ""
            arch_suffix = " [ARCHIVED]" if t.get("archived") else ""
            repo_suffix = f" repo={t['target_repo']}" if t.get("target_repo") else ""
            lines.append(
                f"{prefix}{connector}[L{t['layer']}] {t['slug']} ({t['name']}) "
                f"[{t['status'].upper()} | {active_roles}/{len(t['roles'])} active] "
                f"roles: [{role_names}]{bp_suffix}{proj_suffix}{life_suffix}{arch_suffix}{repo_suffix}"
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
        f"{'DOORBELL ADDRESS':<38} {'TITLE'}"
    )
    lines.append(header)
    lines.append("-" * 110)
    for a in agents:
        cid = a["conversation_id"] or "-"
        lines.append(
            f"{a['agent_id']:<28} {a['status']:<10} {a['model']:<10} {cid:<38} {a['title']}"
        )
    return "\n".join(lines)


def format_project_list(projects: List[Dict[str, Any]]) -> str:
    if not projects:
        return "[ULTRON] No projects registered in ultron/core/projects/."
    lines = [f"[ULTRON] Projects Catalog ({len(projects)}):"]
    for p in projects:
        indent = "  " * p["layer"]
        target_note = f" path={p['effective_target_path']}" if p["effective_target_path"] else ""
        parent_note = f" parent={p['parent_project']}" if p["parent_project"] else ""
        rels_note = (
            " links=[" + ", ".join(f"{r['relation']}:{r['target']}" for r in p["relationships"]) + "]"
            if p["relationships"]
            else ""
        )
        lines.append(
            f"{indent}[L{p['layer']}] {p['slug']} ({p['name']}) [{p['status'].upper()}]"
            f"{parent_note}{target_note}{rels_note}"
        )
    return "\n".join(lines)


def format_project_info(p: Mapping[str, Any]) -> str:
    lines = [f"[ULTRON] Project: {p['slug']} ({p['name']}) [{p['status'].upper()}]"]
    if p.get("description"):
        lines.append(f"  Description:     {p['description']}")
    lines.append(f"  Parent Project:  {p.get('parent_project') or '(root)'}")
    lines.append(f"  Lineage:         {' -> '.join(p.get('lineage', []))}")
    lines.append(f"  Repo Path:       {p.get('repo_path') or '(inherited / none)'}")
    lines.append(f"  Subpath:         {p.get('subpath') or '(root)'}")
    lines.append(f"  Effective Path:  {p.get('effective_target_path') or '(none)'}")
    if p.get("relationships"):
        rels = ", ".join(
            f"{r['relation']} -> {r['target']}" + (f" ({r['note']})" if r.get("note") else "")
            for r in p["relationships"]
        )
        lines.append(f"  Relationships:   {rels}")
    if p.get("subprojects"):
        subs = ", ".join(f"{s['slug']} [{s['status']}]" for s in p["subprojects"])
        lines.append(f"  Subprojects:     {subs}")
    if p.get("teams"):
        tms = ", ".join(f"{t['slug']} [{t['status']}/{t['lifespan']}]" for t in p["teams"])
        lines.append(f"  Bound Teams:     {tms}")
    return "\n".join(lines)


def format_decision_list(decisions: List[Dict[str, Any]]) -> str:
    if not decisions:
        return "[ULTRON] No Prime Decisions recorded in ultron/core/decisions/."
    lines = [f"[ULTRON] Prime Decisions ({len(decisions)}):"]
    for d in decisions:
        scope_badge = d["scope"]
        if d["scope"] == "project" and d.get("project_slug"):
            scope_badge = f"project:{d['project_slug']}"
        elif d["scope"] == "team" and d.get("team_slug"):
            scope_badge = f"team:{d['team_slug']}"
        lines.append(
            f"  * {d['id']} [{d['review_status'].upper()} | {d['origin']} | {scope_badge}] "
            f"{d['title']} -> {d['decision']}"
        )
    return "\n".join(lines)


def format_decision_view(d: Mapping[str, Any]) -> str:
    lines = ["=" * 84]
    lines.append(f"DECISION {d['id']}: {d['title']}")
    scope_badge = d["scope"]
    if d["scope"] == "project" and d.get("project_slug"):
        scope_badge = f"project:{d['project_slug']}"
    elif d["scope"] == "team" and d.get("team_slug"):
        scope_badge = f"team:{d['team_slug']}"
    lines.append(
        f"Status: [{d['review_status'].upper()}] | Origin: [{d['origin']}] | Scope: [{scope_badge}] | By: {d['decided_by']} ({d['created_at'][:19]})"
    )
    lines.append("=" * 84)
    lines.append(f"Decision:          {d['decision']}")
    if d.get("original_decision") and d["original_decision"] != d["decision"]:
        lines.append(f"Original Decision: {d['original_decision']}")
    if d.get("rationale"):
        lines.append(f"Rationale:         {d['rationale']}")
    if d.get("tags"):
        lines.append(f"Tags:              [{d['tags']}]")
    for rev in d.get("reviews", []):
        lines.append(
            f"\n--- Review ({rev['review_status'].upper()}) by @{rev['reviewer']} at {rev['created_at'][:19]} ---"
        )
        if rev.get("replacement_decision"):
            lines.append(f"  Replacement: {rev['replacement_decision']}")
        if rev.get("notes"):
            lines.append(f"  Notes:       {rev['notes']}")
    lines.append("=" * 84)
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


def format_thread_markdown(thread: Mapping[str, Any]) -> str:
    scope = format_scope_badge(thread)
    post_count = thread.get("post_count", len(thread.get("posts", [])))
    t_id = thread.get("id", "")
    t_title = thread.get("title", "")
    t_cat = thread.get("category", "")
    t_status = thread.get("status", "")
    t_vis = thread.get("visibility", "")
    t_author = thread.get("author", "")
    t_created = thread.get("created_at", "")
    t_updated = thread.get("updated_at", "")

    parts: List[str] = []
    header_lines = [
        f"# Thread: {t_title} ({t_id})",
        "",
        f"- **Thread ID:** `{t_id}`",
        f"- **Category:** `{t_cat}`",
        f"- **Status:** `{t_status}`",
        f"- **Visibility:** `{t_vis}`",
        f"- **Scope:** `{scope}`",
        f"- **Author:** `@{t_author}`",
        f"- **Created At:** `{t_created}`",
        f"- **Updated At:** `{t_updated}`",
        f"- **Total Posts:** {post_count}",
    ]
    parts.append("\n".join(header_lines))

    posts = thread.get("posts", [])
    for idx, post in enumerate(posts):
        p_id = post.get("id", "")
        p_author = post.get("author", "")
        p_created = post.get("created_at", "")
        p_parent = post.get("parent_post_id")
        p_tags = post.get("tags")
        p_content = str(post.get("content", ""))

        post_lines: List[str] = []
        if idx == 0:
            post_lines.append(f"## Root Post ({p_id})")
        else:
            post_lines.append(f"## Reply ({p_id})")
        post_lines.append(f"- **Author:** `@{p_author}`")
        post_lines.append(f"- **Created At:** `{p_created}`")
        if idx > 0 and p_parent:
            post_lines.append(f"- **In Reply To:** {p_parent}")
        if p_tags:
            post_lines.append(f"- **Tags:** [{p_tags}]")
        post_lines.append("")
        post_lines.append(p_content)
        parts.append("\n".join(post_lines))

    return "\n\n---\n\n".join(parts) + "\n"


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
    )
    parser.add_argument(
        "--root", dest="_global_root", default=None, help="Override ULTRON repository root"
    )
    parser.add_argument(
        "--json",
        dest="_global_json",
        action="store_true",
        default=False,
        help="Emit machine-readable JSON output",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_cmd(
        name: str, help_text: str, aliases: Optional[List[str]] = None
    ) -> argparse.ArgumentParser:
        return sub.add_parser(name, aliases=aliases or [], help=help_text, parents=[common])

    # register-prime
    p_prime = add_cmd("register-prime", "Register/update ULTRON PRIME's doorbell address")
    p_prime.add_argument("--id", required=True, help="ULTRON PRIME doorbell address (conversation UUID or session name)")
    p_prime.add_argument("--harness", default=None, help=f"Harness running PRIME (default: ${HARNESS_ENV}, then auto-detect)")

    # org-tree
    p_ot = add_cmd("org-tree", "Display full N-layer Hive organization tree")
    p_ot.add_argument("--all", dest="show_all", action="store_true", help="Include archived ephemeral teams")

    # blueprints
    add_cmd("blueprints", "List available Team Blueprints in ultron/core/blueprints/")

    # blueprint-info
    p_bpi = add_cmd("blueprint-info", "Show full details, roster, and workflow of a Team Blueprint")
    p_bpi.add_argument("slug", help="Blueprint slug (e.g. coding-light)")

    # save-blueprint
    p_sbp = add_cmd(
        "save-blueprint",
        "Export an existing Hive team's roster and charters into a reusable Team Blueprint",
    )
    p_sbp.add_argument("team", help="Source Hive team slug")
    p_sbp.add_argument("--slug", required=True, help="New blueprint slug (kebab-case)")
    p_sbp.add_argument("--name", required=True, help="Human-readable blueprint title")
    p_sbp.add_argument("--description", required=True, help="Blueprint summary description")
    p_sbp.add_argument("--when-to-use", default="", help="Guidance on when to select this blueprint")
    p_sbp.add_argument("--workflow-summary", default="", help="One-line pipeline summary")
    p_sbp.add_argument("--overwrite", action="store_true", help="Overwrite existing blueprint")

    # create-team
    p_ct = add_cmd("create-team", "Create a team folder in ultron/hive/ and register it")
    p_ct.add_argument("--slug", required=True, help="Unique team slug (kebab-case)")
    p_ct.add_argument(
        "--name",
        default="",
        help="Human-readable team name (optional when --blueprint is provided)",
    )
    p_ct.add_argument("--mission", required=True, help="Team mission and scope boundaries")
    p_ct.add_argument("--harness", default="", help="Harness this team runs on (default: Prime's)")
    p_ct.add_argument(
        "--blueprint",
        default=None,
        help="Optional Team Blueprint slug (e.g. coding-light) to scaffold full roster and workflow",
    )
    p_ct.add_argument(
        "--parent",
        default=None,
        help="Parent team slug (omit for Layer 1 under ULTRON PRIME)",
    )
    p_ct.add_argument(
        "--model",
        default=DEFAULT_MODEL_TIER,
        type=normalize_model,
        help=f"Default model tier ({', '.join(sorted(VALID_MODELS))}) or explicit model ID (default: {DEFAULT_MODEL_TIER})",
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
    p_ct.add_argument(
        "--project",
        default="",
        help="Optional project slug from ultron/core/projects/ to bind this team to",
    )
    p_ct.add_argument(
        "--lifespan",
        default=None,
        choices=sorted(VALID_TEAM_LIFESPANS),
        help=f"Team lifespan: {', '.join(sorted(VALID_TEAM_LIFESPANS))} (default: {DEFAULT_TEAM_LIFESPAN})",
    )
    p_ct.add_argument(
        "--ephemeral",
        action="store_true",
        help="Shorthand for --lifespan ephemeral (auto-archives when disabled)",
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
        type=normalize_model,
        help=f"Override model tier ({', '.join(sorted(VALID_MODELS))}) or explicit model ID for this role",
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
    p_sh = add_cmd("set-harness", "Set or clear the harness a team runs on (team must be stopped)")
    p_sh.add_argument("team", help="Team slug")
    p_sh.add_argument("harness", nargs="?", default="", help=f"One of {sorted(HARNESS_ADAPTERS)}; omit to follow Prime")

    p_sm = add_cmd("set-model", "Update the persisted model tier or explicit model ID for a team or single role (Prime-only)")
    p_sm.add_argument("team", help="Team slug")
    p_sm.add_argument("model", help=f"Model tier ({', '.join(sorted(VALID_MODELS))}) or explicit model ID (e.g. gemini-4-argon-high)")
    p_sm.add_argument("--role", default=None, help="Optional single role slug to update instead of the whole team")

    p_db = add_cmd("doorbell", "Wake an agent on any harness from a shell")
    p_db.add_argument("agent_id", help="Target agent id (e.g. docs/lead or ultron-prime)")
    p_db.add_argument("message", help="Message text")
    p_db.add_argument("--from", dest="sender", default="", help="Your agent id, prefixed to the message")

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

    p_slf = add_cmd("set-lifespan", "Update a team's lifespan or archival state (Prime-only)")
    p_slf.add_argument("team", help="Team slug")
    p_slf.add_argument(
        "lifespan",
        nargs="?",
        default=None,
        choices=sorted(VALID_TEAM_LIFESPANS),
        help="Target lifespan (permanent | ephemeral)",
    )
    slf_arch = p_slf.add_mutually_exclusive_group()
    slf_arch.add_argument("--archive", action="store_true", help="Mark stopped team archived")
    slf_arch.add_argument("--unarchive", action="store_true", help="Unarchive team back into standing views")

    p_sprj = add_cmd("set-project", "Bind or clear a team's Project catalog reference (Prime-only)")
    p_sprj.add_argument("team", help="Team slug")
    p_sprj.add_argument("project_slug", nargs="?", default="", help="Project slug (omit with --clear)")
    p_sprj.add_argument("--clear", action="store_true", help="Unbind team from its project")
    p_sprj.add_argument("--cascade", action="store_true", help="Apply project binding to descendant child teams")

    # teams
    p_tms = add_cmd("teams", "List registered teams")
    p_tms.add_argument(
        "--status", default=None, choices=sorted(VALID_TEAM_STATUSES), help="Filter by status"
    )
    p_tms.add_argument("--project", default=None, help="Filter by bound project slug")
    p_tms.add_argument(
        "--lifespan", default=None, choices=sorted(VALID_TEAM_LIFESPANS), help="Filter by lifespan"
    )
    tms_arch = p_tms.add_mutually_exclusive_group()
    tms_arch.add_argument("--archived", action="store_true", help="List only archived ephemeral teams")
    tms_arch.add_argument("--all", dest="show_all", action="store_true", help="Include archived teams")

    # team-info
    p_ti = add_cmd("team-info", "Show detailed info and role roster for a team")
    p_ti.add_argument("slug", help="Team slug")

    # render-spawn (alias: prepare-spawn)
    p_rs = add_cmd(
        "render-spawn",
        "Render per-harness spawn specs for a team's roles",
        aliases=["prepare-spawn"],
    )
    p_rs.add_argument("team", help="Team slug")
    p_rs.add_argument("--role", default=None, help="Optional single role slug to render")
    p_rs.add_argument(
        "--brief", default="", help="Optional initial directive appended to startup prompt"
    )
    p_rs.add_argument("--harness", default=None, help=f"Harness to render for (default: ${HARNESS_ENV}, then auto-detect)")

    # spawn-team
    p_sp = add_cmd("spawn-team", "Spawn one live session per role (or emit the harness's launch plan)")
    p_sp.add_argument("team", help="Team slug")
    p_sp.add_argument("--brief", default="", help="Optional initial directive for every role")
    p_sp.add_argument("--harness", default=None, help=f"Harness running ULTRON (default: ${HARNESS_ENV}, then auto-detect)")

    # stop-team
    p_st = add_cmd("stop-team", "Stop a team's live sessions and disable it (or emit the harness's stop plan)")
    p_st.add_argument("team", help="Team slug")
    p_st.add_argument("--cascade", action="store_true", help="Include all descendant child teams")
    p_st.add_argument("--harness", default=None, help=f"Harness running ULTRON (default: ${HARNESS_ENV}, then auto-detect)")

    p_lv = add_cmd("liveness", "Check that every active role's session is still running")
    p_lv.add_argument("team", nargs="?", default=None, help="Only this team (default: all active roles)")
    p_lv.add_argument("--harness", default=None, help=f"Harness running ULTRON (default: ${HARNESS_ENV}, auto-detect, then Prime's)")

    # activate-team
    p_at = add_cmd("activate-team", "Bind live doorbell addresses and mark a team active (spawn-team does this on Claude Code)")
    p_at.add_argument("team", help="Team slug")
    p_at.add_argument(
        "--uuids",
        required=True,
        help='JSON object mapping role -> doorbell address (e.g. \'{"lead":"...","coder":"..."}\')',
    )
    p_at.add_argument(
        "--allow-detached",
        action="store_true",
        help="Allow activation even if parent team is disabled",
    )
    p_at.add_argument("--partial", action="store_true", help="Allow partial role activation")
    p_at.add_argument("--harness", default=None, help=f"Harness running the roles (default: ${HARNESS_ENV}, auto-detect, then Prime's)")

    # activate-agent
    p_aa = add_cmd("activate-agent", "Bind a live doorbell address to a single role")
    p_aa.add_argument("agent_id", help="Agent ID (<team>/<role> or ultron-prime)")
    p_aa.add_argument("--id", required=True, help="Doorbell address (conversation UUID or session name)")
    p_aa.add_argument(
        "--allow-detached",
        action="store_true",
        help="Allow activation if parent/lead is disabled",
    )

    # prepare-disable
    p_pd = add_cmd("prepare-disable", "List live sessions to stop before disabling a team")
    p_pd.add_argument("team", help="Team slug")
    p_pd.add_argument(
        "--cascade", action="store_true", help="Include all descendant child teams"
    )

    # disable-team
    p_dt = add_cmd(
        "disable-team", "Clear bindings and mark a team disabled after its sessions are stopped"
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
    p_ag = add_cmd("agents", "List registered roles and their doorbell addresses")
    p_ag.add_argument("--team", default=None, help="Filter by team slug")
    p_ag.add_argument(
        "--status", default=None, choices=sorted(VALID_AGENT_STATUSES), help="Filter by status"
    )

    # whois
    p_who = add_cmd("whois", "Resolve <team>/<role> or ultron-prime to its doorbell address")
    p_who.add_argument("agent_id", help="Agent ID (e.g. platform/lead or ultron-prime)")
    p_who.add_argument(
        "--id-only",
        action="store_true",
        help="Print ONLY the raw address to stdout (errors go strictly to stderr)",
    )
    p_who.add_argument(
        "--swarm-name",
        action="store_true",
        help="Print ONLY the Antigravity swarm @handle (e.g. @platform-lead or @coordinator) to stdout",
    )

    # set-campaign
    p_sc = add_cmd("set-campaign", "Set team campaign mode (on|off) for safety cron activation (Prime-only)")
    p_sc.add_argument("team", help="Team slug")
    p_sc.add_argument("state", choices=["on", "off", "active", "inactive"], help="Campaign state: on|off")

    # directory
    p_dir = add_cmd(
        "directory", "Query live Hive directory and agent routing information"
    )
    p_dir.add_argument("agent_id", nargs="?", default=None, help="Optional agent ID to inspect")
    p_dir.add_argument("--team", default=None, help="Filter by team slug")
    p_dir.add_argument("--owns", default=None, help="Filter by keyword ownership in mission, responsibilities, or charters")
    p_dir.add_argument("--all", action="store_true", help="Include disabled agents (default: active only)")
    p_dir.add_argument("--no-probe", action="store_true", help="Skip live process probe for instant execution")

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
    p_new.add_argument("--author-id", default="", help="Optional doorbell address override")

    # reply
    p_rep = add_cmd("reply", "Append a reply to an existing JSONL thread")
    p_rep.add_argument("thread_id", help="Thread ID (full ID or unique short suffix/prefix)")
    p_rep.add_argument(
        "--author", required=True, help="Canonical author ID (<team>/<role> or ultron-prime)"
    )
    p_rep.add_argument("--content", "-m", required=True, help="Reply body")
    p_rep.add_argument("--reply-to", default=None, help="Optional parent post ID")
    p_rep.add_argument("--tags", default="", help="Comma-separated tags")
    p_rep.add_argument("--author-id", default="", help="Optional doorbell address override")

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

    # export-thread
    p_exp = add_cmd("export-thread", "Export thread to Markdown or JSON")
    p_exp.add_argument("thread_id", help="Thread ID (full ID or unique short suffix/prefix)")
    p_exp.add_argument(
        "--format",
        default="md",
        choices=["md", "json"],
        help="Export format (md or json, default: md)",
    )
    p_exp.add_argument(
        "--output",
        default=None,
        help="Destination file path (stdout if omitted)",
    )
    p_exp.add_argument("--as", dest="as_agent", default=None, help="Caller agent ID")
    p_exp.add_argument(
        "--all",
        dest="show_all",
        action="store_true",
        help="Unfiltered access (ULTRON PRIME / Curator)",
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

    # Projects Catalog commands
    p_cp = add_cmd("create-project", "Register a project or sub-project in ultron/core/projects/")
    p_cp.add_argument("--slug", required=True, help="Unique project slug (kebab-case)")
    p_cp.add_argument("--name", required=True, help="Human-readable project name")
    p_cp.add_argument("--description", default="", help="Project scope/description")
    p_cp.add_argument("--repo-path", default="", help="Repository root path (e.g. ~/Dev/game_dev_trial)")
    p_cp.add_argument("--subpath", default="", help="Relative directory inside repo (e.g. the_bearntalist)")
    p_cp.add_argument("--parent", default=None, help="Parent project slug (for nested sub-projects)")
    p_cp.add_argument("--status", default="active", choices=sorted(VALID_PROJECT_STATUSES), help="Initial status")

    p_up = add_cmd("update-project", "Update fields of an existing project")
    p_up.add_argument("slug", help="Project slug")
    p_up.add_argument("--name", default=None, help="New project name")
    p_up.add_argument("--description", default=None, help="New project description")
    p_up.add_argument("--repo-path", default=None, help="New repository path")
    p_up.add_argument("--clear-repo-path", action="store_true", help="Clear repo_path (inherit from parent)")
    p_up.add_argument("--subpath", default=None, help="New relative subpath")
    p_up.add_argument("--clear-subpath", action="store_true", help="Clear subpath")
    p_up.add_argument("--parent", default=None, help="New parent project slug")
    p_up.add_argument("--clear-parent", action="store_true", help="Clear parent_project (promote to root)")
    p_up.add_argument("--status", default=None, choices=sorted(VALID_PROJECT_STATUSES), help="New status")

    p_lp = add_cmd("link-project", "Add or remove a typed relationship edge between projects")
    p_lp.add_argument("source", help="Source project slug")
    p_lp.add_argument("target", help="Target project slug")
    p_lp.add_argument("--relation", default="depends_on", choices=sorted(VALID_PROJECT_RELATIONS), help="Relationship type")
    p_lp.add_argument("--note", default="", help="Relationship context/note")
    p_lp.add_argument("--unlink", action="store_true", help="Remove matching relationship edge")

    p_pjs = add_cmd("projects", "List registered projects in ultron/core/projects/")
    p_pjs.add_argument("--status", default=None, choices=sorted(VALID_PROJECT_STATUSES), help="Filter by status")
    p_pjs.add_argument("--parent", default=None, help="Filter by parent project slug")
    p_pjs.add_argument("--all", dest="show_all", action="store_true", help="Include archived projects")

    p_pi = add_cmd("project-info", "Show full details of a project")
    p_pi.add_argument("slug", help="Project slug")

    p_rp = add_cmd("remove-project", "Remove a project from ultron/core/projects/")
    p_rp.add_argument("slug", help="Project slug")
    p_rp.add_argument("--cascade", action="store_true", help="Remove descendant sub-projects recursively")

    # Prime Decisions Ledger commands
    p_ld = add_cmd("log-decision", "Log a Prime decision in ultron/core/decisions/ (Prime-only)")
    p_ld.add_argument("--title", required=True, help="Decision title")
    p_ld.add_argument("--decision", "-d", required=True, help="Authoritative ruling or choice made")
    p_ld.add_argument("--rationale", default="", help="Context, alternatives weighed, or reasoning")
    p_ld.add_argument(
        "--origin",
        default="prime_autonomous",
        choices=sorted(VALID_DECISION_ORIGINS),
        help="Whether User guided this or Prime decided autonomously while User was away",
    )
    p_ld.add_argument(
        "--scope",
        default=None,
        choices=sorted(VALID_DECISION_SCOPES),
        help="Scope (inferred from --team / --project / global if omitted)",
    )
    p_ld.add_argument("--project", default=None, help="Bound project slug")
    p_ld.add_argument("--team", default=None, help="Bound team slug")
    p_ld.add_argument(
        "--status",
        default=None,
        choices=sorted(VALID_DECISION_REVIEW_STATUSES),
        help="Initial review status (defaults: user_guided->approved, prime_autonomous->pending_review)",
    )
    p_ld.add_argument("--tags", default="", help="Comma-separated tags")

    p_ds = add_cmd("decisions", "List Prime Decisions from ultron/core/decisions/")
    p_ds.add_argument("--status", default=None, choices=sorted(VALID_DECISION_REVIEW_STATUSES), help="Filter by review status")
    p_ds.add_argument("--origin", default=None, choices=sorted(VALID_DECISION_ORIGINS), help="Filter by origin")
    p_ds.add_argument("--scope", default=None, choices=sorted(VALID_DECISION_SCOPES), help="Filter by scope")
    p_ds.add_argument("--project", default=None, help="Filter by project slug")
    p_ds.add_argument("--team", default=None, help="Filter by team slug")
    p_ds.add_argument("--pending", action="store_true", help="Show only decisions awaiting User validation (pending_review)")
    p_ds.add_argument("--limit", type=int, default=50, help="Max decisions to return")

    p_vd = add_cmd("view-decision", "Inspect a decision and its full review history")
    p_vd.add_argument("decision_id", help="Decision ID (full ID or unique short prefix/suffix)")

    p_rd = add_cmd("review-decision", "Validate, refine, or overrule a recorded Prime Decision (Prime-only)")
    p_rd.add_argument("decision_id", help="Decision ID (full ID or unique short prefix/suffix)")
    p_rd.add_argument("--status", required=True, choices=sorted(VALID_DECISION_REVIEW_STATUSES), help="New review status")
    p_rd.add_argument("--notes", default="", help="User feedback, improvement guidance, or rationale")
    p_rd.add_argument("--replacement", default="", help="Replacement ruling text (preserves original_decision)")
    p_rd.add_argument("--reviewer", default="user", help="Reviewer identity (default: user)")

    # Read-only Mission Control Web UI
    p_ui = add_cmd("ui", "Launch local read-only ULTRON Mission Control web dashboard (Prime-only)")
    p_ui.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p_ui.add_argument("--port", type=int, default=8420, help="HTTP port (default: 8420)")
    p_ui.add_argument("--no-open", action="store_true", help="Do not open default browser automatically")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.root = getattr(args, "root", args._global_root)
    args.json = bool(getattr(args, "json", args._global_json))

    try:
        core = UltronCore(repo_root=args.root)
        cmd = args.command
        role_id = os.environ.get(ROLE_ID_ENV, "").strip()
        if role_id and role_id != PRIME_ID and cmd in PRIME_ONLY_COMMANDS:
            raise PermissionError(f"'{cmd}' is for {PRIME_ID} only; this shell belongs to role '{role_id}'.")

        if cmd == "register-prime":
            prime_harness = resolve_harness_or_blank(args.harness)
            res = core.register_prime(args.id, harness=prime_harness)
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
                        {
                            "prime": core.get_agent(PRIME_ID),
                            "teams": core.list_teams(include_archived=args.show_all),
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(format_org_tree(core, include_archived=args.show_all))

        elif cmd == "blueprints":
            bps = core.list_blueprints()
            if args.json:
                print(json.dumps(bps, indent=2, sort_keys=True))
            elif not bps:
                print("[ULTRON] No blueprints found in ultron/core/blueprints/.")
            else:
                print(f"[ULTRON] Available Team Blueprints ({len(bps)}):\n")
                for bp in bps:
                    roles_str = ", ".join(bp["role_names"])
                    print(f"  * {bp['slug']} — {bp['name']} ({len(bp['roles'])} roles: [{roles_str}])")
                    print(f"    Description: {bp['description']}")
                    if bp.get("workflow_summary"):
                        print(f"    Workflow:    {bp['workflow_summary']}")
                    if bp.get("when_to_use"):
                        print(f"    When to Use: {bp['when_to_use']}")
                    print()

        elif cmd == "blueprint-info":
            bp = core.get_blueprint(args.slug)
            if args.json:
                print(json.dumps(bp, indent=2, sort_keys=True))
            else:
                print(f"[ULTRON] Blueprint: {bp['slug']} ({bp['name']})")
                print(f"  Description: {bp['description']}")
                print(f"  When to Use: {bp['when_to_use']}")
                print(f"  Workflow:    {bp['workflow_summary']}")
                print(f"  Roles ({len(bp['roles'])}):")
                for r in bp["roles"]:
                    ro_tag = " [read-only]" if not r["write_tools"] else ""
                    print(
                        f"    - {r['role']:<14} ({r['title']}, model={r['default_model']}{ro_tag}): {r['responsibilities']}"
                    )

        elif cmd == "save-blueprint":
            bp = core.save_blueprint(
                team_slug=args.team,
                blueprint_slug=args.slug,
                name=args.name,
                description=args.description,
                when_to_use=args.when_to_use,
                workflow_summary=args.workflow_summary,
                overwrite=args.overwrite,
            )
            if args.json:
                print(json.dumps(bp, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Saved Blueprint '{bp['slug']}' ({bp['name']}) at {bp['blueprint_path']} "
                    f"with roles {bp['role_names']}"
                )

        elif cmd == "create-team":
            if args.ephemeral and args.lifespan == "permanent":
                raise ValueError("Cannot pass both --ephemeral and --lifespan permanent.")
            chosen_lifespan = "ephemeral" if args.ephemeral else (args.lifespan or DEFAULT_TEAM_LIFESPAN)
            res = core.create_team(
                slug=args.slug,
                name=args.name,
                mission=args.mission,
                parent_team=args.parent,
                default_model=args.model,
                workspace_mode=args.workspace,
                lead_responsibilities=args.lead_responsibilities,
                target_repo=args.target_repo,
                blueprint=args.blueprint,
                harness=args.harness,
                lifespan=chosen_lifespan,
                project=args.project,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                bp_note = f" [blueprint={res['blueprint']}]" if res.get("blueprint") else ""
                proj_note = f" [project={res['project']}]" if res.get("project") else ""
                life_note = f" [lifespan={res['lifespan']}]" if res.get("lifespan") != DEFAULT_TEAM_LIFESPAN else ""
                repo_note = f" [target_repo={res['target_repo']}]" if res.get("target_repo") else ""
                roles_list = [r["agent_id"] for r in res["roles"]]
                print(
                    f"[ULTRON] Created Team '{res['slug']}' (Layer {res['layer']}) at {res['hive_path']} "
                    f"with roles {roles_list} [status=disabled]{bp_note}{proj_note}{life_note}{repo_note}"
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

        elif cmd == "set-harness":
            res = core.set_team_harness(args.team, args.harness)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(f"[ULTRON] Team '{res['slug']}' harness -> {res['harness'] or 'follow Prime'}")

        elif cmd == "set-model":
            res = core.set_model(args.team, args.model, role=args.role)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            elif args.role:
                print(f"[ULTRON] Role '{res['agent_id']}' model -> {res['model']}")
            else:
                print(f"[ULTRON] Team '{res['slug']}' (and all {len(res['roles'])} role(s)) model -> {res['default_model']}")

        elif cmd == "doorbell":
            res = core.doorbell(args.agent_id, args.message, sender=args.sender)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(f"[ULTRON] Doorbell delivered to {res['agent_id']} on {res['harness']}.")

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

        elif cmd == "set-lifespan":
            if args.lifespan is None and not args.archive and not args.unarchive:
                raise ValueError("Specify <permanent|ephemeral> and/or --archive or --unarchive.")
            arch_arg: Optional[bool] = True if args.archive else (False if args.unarchive else None)
            res = core.set_team_lifespan(args.team, lifespan=args.lifespan, archived=arch_arg)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                arch_note = " [ARCHIVED]" if res.get("archived") else ""
                print(f"[ULTRON] Team '{res['slug']}' lifespan={res['lifespan']}{arch_note}")

        elif cmd == "set-project":
            clean_p = (args.project_slug or "").strip()
            if args.clear and clean_p:
                raise ValueError("Cannot pass both <project_slug> and --clear.")
            if not args.clear and not clean_p:
                raise ValueError("Provide a <project_slug> or pass --clear to unbind.")
            res = core.set_team_project(
                team_slug=args.team,
                project_slug="" if args.clear else clean_p,
                cascade=args.cascade,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(f"[ULTRON] Team '{res['slug']}' project -> {res.get('project') or '(unbound)'}")

        elif cmd == "teams":
            res = core.list_teams(
                status=args.status,
                project=args.project,
                lifespan=args.lifespan,
                include_archived=args.show_all or args.archived,
                archived_only=args.archived,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            elif not res:
                print("[ULTRON] No teams registered.")
            else:
                for t in res:
                    proj_suffix = f" project={t['project']}" if t.get("project") else ""
                    life_suffix = f" lifespan={t['lifespan']}" if t.get("lifespan") else ""
                    arch_suffix = " [ARCHIVED]" if t.get("archived") else ""
                    repo_suffix = f" repo={t['target_repo']}" if t.get("target_repo") else ""
                    print(
                        f"[L{t['layer']}] {t['slug']:<20} status={t['status']:<10} "
                        f"parent={t['parent_team'] or PRIME_ID:<16} path={t['hive_path']}"
                        f"{life_suffix}{arch_suffix}{proj_suffix}{repo_suffix}"
                    )

        elif cmd == "team-info":
            res = core.get_team(args.slug)
            if not res:
                print(f"[ULTRON Error] Team '{args.slug}' not found.", file=sys.stderr)
                return 1
            print(json.dumps(res, indent=2, sort_keys=True))

        elif cmd in ("render-spawn", "prepare-spawn"):
            harness = resolve_harness(args.harness, core)
            specs = core.render_spawn(
                team_slug=args.team, role=args.role, mission_brief=args.brief, harness=harness
            )
            if args.json:
                print(json.dumps(specs, indent=2, sort_keys=True))
            elif harness == "claude-code":
                for s in specs:
                    print("=" * 80)
                    print(f"SPAWN SPEC FOR: {s['agent_id']} (session {s['session_name']})")
                    print(f"  Model={s['claude_model'] or 'inherit'} | Dir={s['role_dir']}")
                    print("-" * 80)
                    print(s["role_context"])
            else:
                for s in specs:
                    print("=" * 80)
                    print(
                        f"SPAWN SPEC FOR: {s['agent_id']} (swarm=@{s['swarm_name']})"
                    )
                    print(
                        f"  Model={s['swarm_add'].get('model', 'inherit')} | "
                        f"Workspace={s['swarm_add']['workspace']} | "
                        f"ContextFile={s['role_context_path']}"
                    )
                    print("-" * 80)
                    print(s["role_context"])
                    print("-" * 80)
                    print("[SWARM BRIEF]")
                    print(s["swarm_add"]["brief"])

        elif cmd == "spawn-team":
            res = core.spawn_team(team_slug=args.team, mission_brief=args.brief, harness=args.harness)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            elif res["next_steps"]:
                print(f"[ULTRON] Launch plan for team '{res['team_slug']}' on {res['harness']} "
                      f"({len(res['specs'])} role(s)); run with --json for the full specs. Next:")
                for step in res["next_steps"]:
                    print(f"  - {step}")
            else:
                print(f"[ULTRON] Spawned team '{res['team_slug']}' on {res['harness']}:")
                for sess in res["sessions"]:
                    print(f"  {sess['agent_id']:<28} {sess['session_name']:<36} id={sess['session_id']} model={sess['model']}")
                print("[ULTRON] Reminder: Arm a recurring Safety Cron while teams work, and commit & push ultron/hive/ and ultron/core/threads/ to origin.")

        elif cmd == "stop-team":
            res = core.stop_team(team_slug=args.team, cascade=args.cascade, harness=args.harness)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            elif res["next_steps"]:
                print(f"[ULTRON] Stop plan for {res['teams_affected']} on {res['harness']}; "
                      f"the team stays active until disable-team runs. Next:")
                for step in res["next_steps"]:
                    print(f"  - {step}")
            else:
                print(f"[ULTRON] Disabled team(s) {res['teams_affected']}.")
                print("[ULTRON] Reminder: Commit & push ultron/hive/ and ultron/core/threads/ to origin (and cancel your Safety Cron if no active teams remain).")
                for aid, err in sorted(res["stop_failures"].items()):
                    print(f"[ULTRON] Stop failed for {aid}: {err}", file=sys.stderr)
                for aid in res["missing_session_ids"]:
                    print(f"[ULTRON] No session id recorded for {aid}; stop it by hand.", file=sys.stderr)
            if res["stop_failures"] or res["missing_session_ids"]:
                return 1

        elif cmd == "liveness":
            res = core.probe_liveness(team_slug=args.team, harness=args.harness)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                if not res["agents"]:
                    print("[ULTRON] No active roles.")
                for aid, r in sorted(res["agents"].items()):
                    camp = r.get("campaign", "off")
                    print(f"  {aid:<28} {r['state']:<8} campaign:{camp:<7} {r['detail']}")
                for step in res["next_steps"]:
                    print(f"  - {step}")
            if any(r["state"] == "gone" for r in res["agents"].values()):
                return 1

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
                harness=resolve_harness_or_blank(args.harness, core),
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
                print("[ULTRON] Reminder: Arm a recurring Safety Cron while teams work, and commit & push ultron/hive/ and ultron/core/threads/ to origin.")

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
                    f"(cleared {len(res['conversation_ids_to_kill'])} live binding(s); Hive files & JSONL threads preserved)."
                )
                print("[ULTRON] Reminder: Commit & push ultron/hive/ and ultron/core/threads/ to origin (and cancel your Safety Cron if no active teams remain).")

        elif cmd == "disable-agent":
            res = core.disable_agent(args.agent_id)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Disabled '{res['agent_id']}' (previous address: {res['previous_conversation_id'] or 'none'})."
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
                    f"[ULTRON Error] Agent '{agent['agent_id']}' is currently DISABLED (no live doorbell address).",
                    file=sys.stderr,
                )
                return 1
            if args.swarm_name:
                print(f"@{agent.get('swarm_name') or swarm_name_for(agent['agent_id'])}")
            elif args.id_only:
                print(agent["conversation_id"])
            elif args.json:
                print(json.dumps(agent, indent=2, sort_keys=True))
            else:
                print(f"[ULTRON] Agent: {agent['agent_id']}")
                print(f"  Title:           {agent['title']}")
                print(f"  Status:          {agent['status']}")
                print(f"  Model:           {agent['model']}")
                print(f"  Conversation ID: {agent['conversation_id']}")
                print(f"  Swarm Name:      @{agent.get('swarm_name') or swarm_name_for(agent['agent_id'])}")
                print(f"  Role Path:       {agent['role_path']}")

        elif cmd == "set-campaign":
            res = core.set_campaign(args.team, args.state)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(f"[ULTRON] Team '{res['slug']}' campaign -> {res['campaign']}")

        elif cmd == "directory":
            res = core.directory(
                agent_id=args.agent_id,
                team_slug=args.team,
                owns=args.owns,
                include_all=args.all,
                no_probe=args.no_probe,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            elif args.agent_id:
                if res.get("probe_error"):
                    print(f"[ULTRON Directory] Warning: Liveness probe failed: {res['probe_error']}", file=sys.stderr)
                print(f"[ULTRON Directory] Agent: {res['agent_id']}")
                print(f"  Title:            {res['title']}")
                print(f"  Team:             {res['team'] or '-'}")
                print(f"  Role:             {res['role']}")
                print(f"  Status:           {res['status']}")
                print(f"  Campaign:         {res['campaign']}")
                print(f"  Running:          {res['running']}")
                print(f"  Harness:          {res['harness'] or '-'}")
                if res['superior']:
                    if res['superior_disabled']:
                        if res['fallback_to_prime']:
                            print(f"  Superior:         {res['superior']} (DISABLED -> fallback to {PRIME_ID})")
                        else:
                            print(f"  Superior:         {res['superior']} (DISABLED)")
                    else:
                        print(f"  Superior:         {res['superior']} ({res['superior_status']})")
                print(f"  Mission:          {res['mission'] or '-'}")
                print(f"  Responsibilities: {res['responsibilities'] or '-'}")
            else:
                probe_err = next((e.get("probe_error") for e in res if e.get("probe_error")), None)
                if probe_err:
                    print(f"[ULTRON Directory] Warning: Liveness probe failed: {probe_err}", file=sys.stderr)
                if not res:
                    print("[ULTRON Directory] No agents found.")
                else:
                    print(f"{'AGENT ID':<24} {'STATUS':<10} {'CAMPAIGN':<10} {'RUNNING':<9} {'HARNESS':<14} {'SUPERIOR':<24} {'TITLE'}")
                    print("-" * 110)
                    for e in res:
                        sup_disp = e['superior'] or "-"
                        if e['superior_disabled']:
                            sup_disp += " (!)"
                        print(f"{e['agent_id']:<24} {e['status']:<10} {e['campaign']:<10} {e['running']:<9} {e['harness'] or '-':<14} {sup_disp:<24} {e['title']}")

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

        elif cmd == "export-thread":
            fmt = "json" if getattr(args, "json", False) and args.format == "md" else args.format
            res = core.export_thread(
                thread_id=args.thread_id,
                format=fmt,
                output_path=args.output,
                as_agent=args.as_agent,
                show_all=args.show_all,
            )
            if args.output:
                print(
                    f"[ULTRON] Exported thread '{args.thread_id}' to {args.output} ({fmt})."
                )
            else:
                if res.endswith("\n"):
                    sys.stdout.write(res)
                else:
                    print(res)

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
                    f"{res['projects']} project(s), {res['decisions']} decision(s), "
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
                    f"  Projects:         {stats['total_projects']}"
                )
                print(
                    f"  Decisions:        {stats['total_decisions']} total ({stats['pending_decisions']} pending review)"
                )
                print(
                    f"  Agents / Roles:   {stats['active_agents']} active / {stats['total_agents']} total"
                )
                print(
                    f"  Threads:          {stats['total_threads']} (Visibilities: {stats['visibilities']})"
                )
                print(f"  Posts:            {stats['total_posts']}")

        elif cmd == "create-project":
            res = core.create_project(
                slug=args.slug,
                name=args.name,
                description=args.description,
                repo_path=args.repo_path,
                subpath=args.subpath,
                parent_project=args.parent,
                status=args.status,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                path_note = f" path={res['effective_target_path']}" if res["effective_target_path"] else ""
                print(f"[ULTRON] Created Project '{res['slug']}' ({res['name']}) [{res['status']}]{path_note}")

        elif cmd == "update-project":
            if args.repo_path is not None and args.clear_repo_path:
                raise ValueError("Cannot pass both --repo-path and --clear-repo-path.")
            if args.subpath is not None and args.clear_subpath:
                raise ValueError("Cannot pass both --subpath and --clear-subpath.")
            if args.parent is not None and args.clear_parent:
                raise ValueError("Cannot pass both --parent and --clear-parent.")
            res = core.update_project(
                slug=args.slug,
                name=args.name,
                description=args.description,
                repo_path="" if args.clear_repo_path else args.repo_path,
                subpath="" if args.clear_subpath else args.subpath,
                parent_project="" if args.clear_parent else args.parent,
                status=args.status,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(f"[ULTRON] Updated Project '{res['slug']}' [{res['status']}] path={res['effective_target_path'] or '(none)'}")

        elif cmd == "link-project":
            res = core.link_projects(
                source_slug=args.source,
                target_slug=args.target,
                relation=args.relation,
                note=args.note,
                unlink=args.unlink,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                verb = "Unlinked" if args.unlink else "Linked"
                print(f"[ULTRON] {verb} '{args.source}' -[{args.relation}]-> '{args.target}'")

        elif cmd == "projects":
            res = core.list_projects(
                status=args.status,
                parent_project=args.parent,
                include_archived=args.show_all,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(format_project_list(res))

        elif cmd == "project-info":
            res = core.get_project(args.slug)
            if not res:
                print(f"[ULTRON Error] Project '{args.slug}' not found.", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(format_project_info(res))

        elif cmd == "remove-project":
            res = core.remove_project(slug=args.slug, cascade=args.cascade)
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(f"[ULTRON] Removed project(s): {res['removed_projects']}")

        elif cmd == "log-decision":
            res = core.log_decision(
                title=args.title,
                decision=args.decision,
                rationale=args.rationale,
                origin=args.origin,
                scope=args.scope,
                project_slug=args.project,
                team_slug=args.team,
                review_status=args.status,
                tags=args.tags,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Logged Decision {res['id']} [{res['origin']} | {res['review_status']}]: {res['title']}"
                )

        elif cmd == "decisions":
            res = core.list_decisions(
                review_status=args.status,
                origin=args.origin,
                scope=args.scope,
                project_slug=args.project,
                team_slug=args.team,
                pending_only=args.pending,
                limit=args.limit,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(format_decision_list(res))

        elif cmd == "view-decision":
            res = core.get_decision(args.decision_id)
            if not res:
                print(f"[ULTRON Error] Decision '{args.decision_id}' not found.", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(format_decision_view(res))

        elif cmd == "review-decision":
            res = core.review_decision(
                decision_ref=args.decision_id,
                review_status=args.status,
                notes=args.notes,
                replacement_decision=args.replacement,
                reviewer=args.reviewer,
            )
            if args.json:
                print(json.dumps(res, indent=2, sort_keys=True))
            else:
                print(
                    f"[ULTRON] Reviewed Decision {res['id']} -> {res['review_status']} ({res['title']})"
                )

        elif cmd == "ui":
            try:
                from ultron.core.web import serve as web_serve
            except ImportError:
                from web import serve as web_serve  # type: ignore[no-redef]
            return web_serve(
                core,
                host=args.host,
                port=args.port,
                open_browser=not args.no_open,
            )

        return 0

    except (ValueError, PermissionError, FileNotFoundError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"[ULTRON Error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
