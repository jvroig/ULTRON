from __future__ import annotations

import json
from pathlib import Path
import shutil

REPO_ROOT = Path(__file__).resolve().parents[1]


def build_fixture_hive(root: Path):
    from ultron.core.core import UltronCore

    (root / "ultron" / "core" / "threads").mkdir(parents=True)
    (root / "ultron" / "hive").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "ultron" / "core" / "templates", root / "ultron" / "core" / "templates")
    core = UltronCore(repo_root=root)
    target = root / "target"
    target.mkdir()
    core.create_team(slug="api", name="API {Team}", mission="Serve {{things}}", default_model="pro")
    core.add_role(team_slug="api", role="coder", title="Coder", responsibilities="Write code", model="flash_lite")
    core.add_role(team_slug="api", role="reviewer", title="Reviewer", responsibilities="Review", write_tools=False)
    core.create_team(slug="auth", parent_team="api", name="Auth", mission="Tokens", target_repo=str(target))
    core.add_role(team_slug="auth", role="dev", title="Dev", responsibilities="Implement")
    return core


def render_all(core, root: Path, harness: str = "antigravity") -> str:
    specs = []
    for team in ("api", "auth"):
        specs += core.render_spawn(team, mission_brief="Ship {it}", harness=harness)
    text = json.dumps(specs, indent=2, sort_keys=True)
    return text.replace(str(root.resolve()), "<ROOT>").replace(str(root), "<ROOT>")
