#!/usr/bin/env python3
"""
Comprehensive unit & integration test suite for ULTRON Core (ultron/core/core.py).
Verifies N-layer Hive scaffolding, lifecycle guards, visibility isolation,
authorization, WAL sync_state determinism, reconciliatory JSON restore, and CLI contracts.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ultron.core.core import PRIME_ID, UltronCore  # noqa: E402


class UltronCoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve()
        (self.root / "ultron" / "core" / "threads").mkdir(parents=True)
        (self.root / "ultron" / "hive").mkdir(parents=True)

        # Copy real templates into isolated test repo root
        shutil.copytree(
            REPO_ROOT / "ultron" / "core" / "templates",
            self.root / "ultron" / "core" / "templates",
        )
        (self.root / "ultron" / "core" / "teams.json").write_text("[]\n", encoding="utf-8")
        (self.root / "ultron" / "core" / "agents.json").write_text("[]\n", encoding="utf-8")

        self.core = UltronCore(repo_root=self.root)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def run_cli(
        self, *args: str, cwd: Path | None = None, env_extra: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("ULTRON_AGENT_ID", None)
        env["ULTRON_REPO_ROOT"] = str(self.root)
        if env_extra:
            env.update(env_extra)
        cmd = [sys.executable, str(REPO_ROOT / "ultron" / "core" / "core.py"), *args]
        return subprocess.run(
            cmd,
            cwd=str(cwd or self.root),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def test_zero_state_robustness(self) -> None:
        stats = self.core.get_stats()
        self.assertEqual(stats["total_teams"], 0)
        self.assertEqual(stats["total_agents"], 0)
        self.assertEqual(stats["total_threads"], 0)

        res_tree = self.run_cli("org-tree")
        self.assertEqual(res_tree.returncode, 0)
        self.assertIn("No teams created", res_tree.stdout)

        res_list = self.run_cli("list", "--all")
        self.assertEqual(res_list.returncode, 0)
        self.assertIn("No visible threads", res_list.stdout)

    def test_arbitrary_n_layer_hierarchy_and_portability(self) -> None:
        # Build a 6-layer deep chain plus a parallel branch
        parent = None
        for depth in range(1, 7):
            slug = f"layer-{depth}"
            t = self.core.create_team(
                slug=slug,
                name=f"Layer {depth} Team",
                mission=f"Operate at depth {depth}",
                parent_team=parent,
            )
            self.assertEqual(t["layer"], depth)
            self.assertFalse(t["hive_path"].startswith("/"))
            parent = slug

        # Sibling branch
        self.core.create_team(slug="ops-root", name="Ops Root", mission="Operations")
        ops_child = self.core.create_team(
            slug="ops-audit",
            name="Ops Audit",
            mission="Audit operations",
            parent_team="ops-root",
        )
        self.assertEqual(ops_child["layer"], 2)

        deep_team = self.core.get_team("layer-6")
        assert deep_team is not None
        self.assertEqual(
            deep_team["lineage"],
            ["layer-1", "layer-2", "layer-3", "layer-4", "layer-5", "layer-6"],
        )
        expected_rel = (
            "ultron/hive/layer-1/teams/layer-2/teams/layer-3/"
            "teams/layer-4/teams/layer-5/teams/layer-6"
        )
        self.assertEqual(deep_team["hive_path"], expected_rel)

        deep_dir = self.root / expected_rel
        self.assertTrue((deep_dir / "team.json").is_file())
        self.assertTrue((deep_dir / "AGENTS.md").is_file())
        self.assertTrue((deep_dir / "roles" / "lead" / "AGENTS.md").is_file())
        self.assertTrue((deep_dir / "roles" / "lead" / "workspace" / ".gitkeep").is_file())

        # Verify stored JSON files contain zero absolute machine paths
        teams_raw = (self.root / "ultron" / "core" / "teams.json").read_text(encoding="utf-8")
        agents_raw = (self.root / "ultron" / "core" / "agents.json").read_text(encoding="utf-8")
        self.assertNotIn(str(self.root), teams_raw)
        self.assertNotIn(str(self.root), agents_raw)

    def test_slug_validation_and_reserved_names(self) -> None:
        for bad in ["../escape", "Upper", "-leading", "trailing-", "a/b", "ultron-prime", "teams", "roles"]:
            with self.assertRaises(ValueError):
                self.core.create_team(slug=bad, name="Bad", mission="Bad")

        self.core.create_team(slug="alpha", name="Alpha", mission="Alpha mission")
        with self.assertRaises(ValueError):
            self.core.add_role("alpha", "lead", "Duplicate Lead", "Should fail")
        with self.assertRaises(ValueError):
            self.core.add_role("alpha", "prime", "Reserved Role", "Should fail")

    def test_render_spawn_invariants_and_brace_safety(self) -> None:
        self.core.create_team(slug="core-eng", name="Core Eng", mission="Build systems")
        self.core.add_role(
            team_slug="core-eng",
            role="auditor",
            title="Security Auditor",
            responsibilities="Audit code with zero write privileges",
            model="flash_lite",
            write_tools=False,
        )
        # Inject curly braces (JSON / Python dict) into team AGENTS.md to test template safety
        charter_file = self.root / "ultron" / "hive" / "core-eng" / "AGENTS.md"
        charter_file.write_text(
            charter_file.read_text(encoding="utf-8") + '\nExample config: `{"strict": true, "retries": 3}`\n',
            encoding="utf-8",
        )

        specs = self.core.render_spawn("core-eng", mission_brief="Audit repository layout.")
        self.assertEqual(len(specs), 2)
        lead_spec, auditor_spec = specs[0], specs[1]

        self.assertEqual(lead_spec["agent_id"], "core-eng/lead")
        self.assertFalse(lead_spec["define_subagent"]["EnableSubagentTools"])
        self.assertTrue(lead_spec["define_subagent"]["EnableWriteTools"])
        self.assertEqual(lead_spec["invoke_subagent"]["Model"], "flash")
        self.assertIn('{"strict": true, "retries": 3}', lead_spec["define_subagent"]["SystemPrompt"])
        self.assertIn("--visibility personal", lead_spec["define_subagent"]["SystemPrompt"])

        self.assertEqual(auditor_spec["agent_id"], "core-eng/auditor")
        self.assertFalse(auditor_spec["define_subagent"]["EnableSubagentTools"])
        self.assertFalse(auditor_spec["define_subagent"]["EnableWriteTools"])
        self.assertEqual(auditor_spec["invoke_subagent"]["Model"], "flash_lite")

    def test_lifecycle_guards_and_whois_contract(self) -> None:
        self.core.register_prime("00000000-0000-0000-0000-000000000001")
        self.core.create_team(slug="parent-t", name="Parent", mission="Parent team")
        self.core.add_role("parent-t", "coder", "Coder", "Write code")
        self.core.create_team(
            slug="child-t", name="Child", mission="Child team", parent_team="parent-t"
        )

        # Cannot activate child while parent is disabled
        with self.assertRaises(ValueError):
            self.core.activate_team("child-t", {"lead": "uuid-child-lead"})

        # Cannot activate specialist while team lead is disabled
        with self.assertRaises(ValueError):
            self.core.activate_agent("parent-t/coder", "uuid-parent-coder")

        # Activate parent, then child
        self.core.activate_team(
            "parent-t", {"lead": "uuid-parent-lead", "coder": "uuid-parent-coder"}
        )
        self.core.activate_team("child-t", {"lead": "uuid-child-lead"})

        # Verify whois --id-only contract on active agent
        ok_who = self.run_cli("whois", "parent-t/lead", "--id-only")
        self.assertEqual(ok_who.returncode, 0)
        self.assertEqual(ok_who.stdout.strip(), "uuid-parent-lead")
        self.assertEqual(ok_who.stderr, "")

        # Cannot disable lead alone while specialist is active
        with self.assertRaises(ValueError):
            self.core.disable_agent("parent-t/lead")

        # Cannot disable parent-t without --cascade while child-t is active
        with self.assertRaises(ValueError):
            self.core.prepare_disable("parent-t", cascade=False)
        with self.assertRaises(ValueError):
            self.core.disable_team("parent-t", cascade=False)

        # Cascade disable succeeds and returns all 3 UUIDs
        plan = self.core.disable_team("parent-t", cascade=True)
        self.assertEqual(
            set(plan["conversation_ids_to_kill"]),
            {"uuid-parent-lead", "uuid-parent-coder", "uuid-child-lead"},
        )

        # Verify whois --id-only on disabled agent writes NOTHING to stdout and exits 1
        disabled_who = self.run_cli("whois", "parent-t/lead", "--id-only")
        self.assertEqual(disabled_who.returncode, 1)
        self.assertEqual(disabled_who.stdout, "")
        self.assertIn("DISABLED", disabled_who.stderr)

        # Hive files still intact on disk after disable
        self.assertTrue((self.root / "ultron" / "hive" / "parent-t" / "AGENTS.md").is_file())
        self.assertTrue(
            (self.root / "ultron" / "hive" / "parent-t" / "teams" / "child-t" / "AGENTS.md").is_file()
        )

    def test_visibility_isolation_reply_auth_and_respawn_persistence(self) -> None:
        self.core.register_prime("uuid-prime")
        self.core.create_team(slug="team-a", name="Team A", mission="Alpha")
        self.core.add_role("team-a", "coder", "Coder", "Code")
        self.core.create_team(
            slug="team-a1", name="Team A1", mission="Alpha Sub", parent_team="team-a"
        )
        self.core.create_team(slug="team-b", name="Team B", mission="Beta")

        self.core.activate_team("team-a", {"lead": "uuid-a-lead-v1", "coder": "uuid-a-coder-v1"})
        self.core.activate_team("team-a1", {"lead": "uuid-a1-lead-v1"})
        self.core.activate_team("team-b", {"lead": "uuid-b-lead-v1"})

        # 1. Personal lesson by team-a/coder
        t_personal = self.core.create_thread(
            title="Coder SQLite Lesson",
            author="team-a/coder",
            visibility="personal",
            category="lesson",
            content="Always run PRAGMA wal_checkpoint on sync.",
        )
        # 2. Intra-team thread on team-a
        t_team_a = self.core.create_thread(
            title="Team A Sprint Plan",
            author="team-a/lead",
            visibility="team",
            category="task",
            content="Implement parser module.",
        )
        # 3. Cross-layer handoff between team-a and team-a1
        t_handoff = self.core.create_thread(
            title="Subtask Delegation to A1",
            author="team-a/lead",
            visibility="team",
            with_team="team-a1",
            category="task",
            content="Please validate token schema.",
        )
        # 4. Global announcement
        t_global = self.core.create_thread(
            title="Global Coding Standard",
            author="ultron-prime",
            visibility="global",
            category="architecture",
            content="Zero third-party dependencies in core.",
        )

        # Missing identity must fail loud
        with self.assertRaises(PermissionError):
            self.core.list_threads()
        with self.assertRaises(PermissionError):
            self.core.get_thread(t_global["thread_id"])
        with self.assertRaises(PermissionError):
            self.core.search("wal_checkpoint")
        # Non-prime trying --all must fail
        with self.assertRaises(PermissionError):
            self.core.list_threads(as_agent="team-b/lead", show_all=True)

        # Visibility checks per role
        coder_ids = {t["id"] for t in self.core.list_threads(as_agent="team-a/coder")}
        self.assertEqual(
            coder_ids,
            {
                t_personal["thread_id"],
                t_team_a["thread_id"],
                t_handoff["thread_id"],
                t_global["thread_id"],
            },
        )

        lead_a_ids = {t["id"] for t in self.core.list_threads(as_agent="team-a/lead")}
        self.assertEqual(
            lead_a_ids,
            {t_team_a["thread_id"], t_handoff["thread_id"], t_global["thread_id"]},
        )

        lead_a1_ids = {t["id"] for t in self.core.list_threads(as_agent="team-a1/lead")}
        self.assertEqual(lead_a1_ids, {t_handoff["thread_id"], t_global["thread_id"]})

        lead_b_ids = {t["id"] for t in self.core.list_threads(as_agent="team-b/lead")}
        self.assertEqual(lead_b_ids, {t_global["thread_id"]})

        # FTS search respects visibility!
        self.assertEqual(len(self.core.search("wal_checkpoint", as_agent="team-a/coder")), 1)
        self.assertEqual(len(self.core.search("wal_checkpoint", as_agent="team-a/lead")), 0)
        self.assertEqual(len(self.core.search("wal_checkpoint", as_agent="team-b/lead")), 0)
        self.assertEqual(len(self.core.search("wal_checkpoint", show_all=True)), 1)

        # Unauthorized view & reply blocked
        with self.assertRaises(PermissionError):
            self.core.get_thread(t_personal["thread_id"], as_agent="team-a/lead")
        with self.assertRaises(PermissionError):
            self.core.add_post(t_team_a["thread_id"], author="team-b/lead", content="Intrusion!")
        with self.assertRaises(PermissionError):
            self.core.add_post(t_handoff["thread_id"], author="team-b/lead", content="Intrusion!")

        # Authorized cross-layer reply works on --with-team thread
        self.core.add_post(
            t_handoff["thread_id"],
            author="team-a1/lead",
            content="Acknowledged, starting validation.",
        )

        # Disable & respawn team-a with brand-new UUIDs -> personal memory still belongs to team-a/coder!
        self.core.disable_team("team-a", cascade=True)
        self.core.activate_team("team-a", {"lead": "uuid-a-lead-v2", "coder": "uuid-a-coder-v2"})
        personal_after = self.core.list_threads(as_agent="team-a/coder", visibility="personal")
        self.assertEqual(len(personal_after), 1)
        self.assertEqual(personal_after[0]["id"], t_personal["thread_id"])

        # Reclassify personal lesson -> global standard by ULTRON PRIME
        self.core.reclassify_thread(t_personal["thread_id"], visibility="global")
        self.assertEqual(len(self.core.search("wal_checkpoint", as_agent="team-b/lead")), 1)

    def test_sync_state_no_spurious_restore_and_reconciliatory_restore(self) -> None:
        self.core.create_team(slug="root-t", name="Root", mission="Root")
        self.core.create_team(slug="sub-t", name="Sub", mission="Sub", parent_team="root-t")
        t1 = self.core.create_thread(
            title="Persistent Knowledge",
            author="root-t/lead",
            visibility="team",
            content="Keep this history across team removals.",
        )

        # Subsequent instantiation with unchanged JSON files must NOT call _reconcile_from_disk
        with mock.patch.object(
            UltronCore, "_reconcile_from_disk", wraps=self.core._reconcile_from_disk
        ) as spy:
            second = UltronCore(repo_root=self.root)
            self.assertEqual(spy.call_count, 0)
            self.assertEqual(second.get_stats()["total_teams"], 2)

        # Delete core.db + WAL files and shuffle teams.json so child appears BEFORE parent
        teams_path = self.root / "ultron" / "core" / "teams.json"
        teams_data = json.loads(teams_path.read_text(encoding="utf-8"))
        teams_data.reverse()  # sub-t before root-t!
        teams_path.write_text(json.dumps(teams_data, indent=2) + "\n", encoding="utf-8")

        for db_file in (self.root / "ultron" / "core").glob("core.db*"):
            db_file.unlink()

        restored = UltronCore(repo_root=self.root)
        self.assertEqual(restored.get_stats()["total_teams"], 2)
        self.assertEqual(restored.get_stats()["total_threads"], 1)

        # Remove team -> board history survives (soft reference invariant)
        restored.remove_team("root-t", cascade=True, delete_files=True)
        self.assertEqual(restored.get_stats()["total_teams"], 0)
        self.assertEqual(restored.get_stats()["total_threads"], 1)
        surviving = restored.get_thread(t1["thread_id"], show_all=True)
        assert surviving is not None
        self.assertEqual(surviving["title"], "Persistent Knowledge")

        # External reset of threads dir (deleting thread_0001.json) purges zombie thread on next run
        for tf in (self.root / "ultron" / "core" / "threads").glob("thread_*.json"):
            tf.unlink()
        reconciled = UltronCore(repo_root=self.root)
        self.assertEqual(reconciled.get_stats()["total_threads"], 0)

    def test_cli_invocation_from_nested_subdirectory(self) -> None:
        self.core.create_team(slug="nested", name="Nested", mission="Test CWD")
        nested_ws = self.root / "ultron" / "hive" / "nested" / "roles" / "lead" / "workspace"
        res = self.run_cli("stats", "--json", cwd=nested_ws)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        payload = json.loads(res.stdout)
        self.assertEqual(Path(payload["repo_root"]).resolve(), self.root)
        self.assertEqual(payload["total_teams"], 1)


if __name__ == "__main__":
    unittest.main()
