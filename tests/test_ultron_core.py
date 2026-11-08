#!/usr/bin/env python3
"""
Comprehensive unit & integration test suite for pure Git-native ULTRON Core (ultron/core/core.py).
Verifies N-layer Hive scaffolding, ephemeral .runtime/sessions.json separation,
append-only JSONL event folding, real Git branch `merge=union` conflict-free merges,
short-ID resolution, visibility isolation, authorization, and CLI contracts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ultron.core.core import PRIME_ID, UltronCore  # noqa: E402


class UltronCoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve()
        (self.root / "ultron" / "core" / "threads").mkdir(parents=True)
        (self.root / "ultron" / "hive").mkdir(parents=True)

        # Copy real templates & .gitignore/.gitattributes into isolated test repo root
        shutil.copytree(
            REPO_ROOT / "ultron" / "core" / "templates",
            self.root / "ultron" / "core" / "templates",
        )
        shutil.copy2(
            REPO_ROOT / "ultron" / "core" / ".gitignore",
            self.root / "ultron" / "core" / ".gitignore",
        )
        shutil.copy2(
            REPO_ROOT / "ultron" / "core" / "threads" / ".gitattributes",
            self.root / "ultron" / "core" / "threads" / ".gitattributes",
        )

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

    def test_zero_state_and_verify(self) -> None:
        stats = self.core.get_stats()
        self.assertEqual(stats["total_teams"], 0)
        self.assertEqual(stats["total_agents"], 0)
        self.assertEqual(stats["total_threads"], 0)

        ver = self.core.verify()
        self.assertTrue(ver["ok"])
        self.assertTrue(ver["gitattributes_union_merge"])

        res_tree = self.run_cli("org-tree")
        self.assertEqual(res_tree.returncode, 0)
        self.assertIn("No teams created", res_tree.stdout)

        res_list = self.run_cli("list", "--all")
        self.assertEqual(res_list.returncode, 0)
        self.assertIn("No visible threads", res_list.stdout)

    def test_arbitrary_n_layer_hierarchy_and_repo_relocation(self) -> None:
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
        self.assertTrue((deep_dir / "roles" / "lead" / "role.json").is_file())
        self.assertTrue((deep_dir / "roles" / "lead" / "AGENTS.md").is_file())
        self.assertTrue((deep_dir / "roles" / "lead" / "workspace" / ".gitkeep").is_file())

        # Verify zero absolute paths in team.json and role.json
        team_raw = (deep_dir / "team.json").read_text(encoding="utf-8")
        role_raw = (deep_dir / "roles" / "lead" / "role.json").read_text(encoding="utf-8")
        self.assertNotIn(str(self.root), team_raw)
        self.assertNotIn(str(self.root), role_raw)

        # Relocate entire repo to a brand-new path and verify immediate operation without rebuild
        with tempfile.TemporaryDirectory() as moved_parent:
            moved_root = Path(moved_parent).resolve() / "relocated_project"
            shutil.copytree(self.root, moved_root)
            relocated_core = UltronCore(repo_root=moved_root)
            self.assertEqual(relocated_core.get_stats()["total_teams"], 8)
            self.assertTrue(relocated_core.verify()["ok"])

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
        self.assertTrue(auditor_spec["read_only_mode"])
        self.assertFalse(auditor_spec["define_subagent"]["EnableSubagentTools"])
        self.assertTrue(auditor_spec["define_subagent"]["EnableWriteTools"])
        self.assertIn("[READ-ONLY ROLE MODE]", auditor_spec["define_subagent"]["SystemPrompt"])
        self.assertEqual(auditor_spec["invoke_subagent"]["Model"], "flash_lite")

    def test_lifecycle_guards_whois_and_clean_git_working_tree(self) -> None:
        self.core.create_team(slug="parent-t", name="Parent", mission="Parent team")
        self.core.add_role("parent-t", "coder", "Coder", "Write code")
        self.core.create_team(
            slug="child-t", name="Child", mission="Child team", parent_team="parent-t"
        )

        team_json_before = (self.root / "ultron" / "hive" / "parent-t" / "team.json").read_text(encoding="utf-8")
        role_json_before = (
            self.root / "ultron" / "hive" / "parent-t" / "roles" / "lead" / "role.json"
        ).read_text(encoding="utf-8")

        self.core.register_prime("00000000-0000-0000-0000-000000000001")

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

        # Ephemeral activations MUST NOT mutate Git-tracked team.json or role.json!
        self.assertEqual(
            team_json_before,
            (self.root / "ultron" / "hive" / "parent-t" / "team.json").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            role_json_before,
            (self.root / "ultron" / "hive" / "parent-t" / "roles" / "lead" / "role.json").read_text(
                encoding="utf-8"
            ),
        )

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

    def test_visibility_isolation_append_only_jsonl_and_short_ids(self) -> None:
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

        t_personal = self.core.create_thread(
            title="Coder JSONL Lesson",
            author="team-a/coder",
            visibility="personal",
            category="lesson",
            content="Use append_jsonl_event with fcntl.flock.",
        )
        t_team_a = self.core.create_thread(
            title="Team A Sprint Plan",
            author="team-a/lead",
            visibility="team",
            category="task",
            content="Implement parser module.",
        )
        t_handoff = self.core.create_thread(
            title="Subtask Delegation to A1",
            author="team-a/lead",
            visibility="team",
            with_team="team-a1",
            category="task",
            content="Please validate token schema.",
        )
        t_global = self.core.create_thread(
            title="Global Coding Standard",
            author="ultron-prime",
            visibility="global",
            category="architecture",
            content="Zero third-party dependencies in core.",
        )

        # Verify pure append-only JSONL behavior (earlier lines never mutated)
        handoff_file = self.root / "ultron" / "core" / "threads" / f"{t_handoff['thread_id']}.jsonl"
        line1_before = handoff_file.read_text(encoding="utf-8").splitlines()[0]

        # Reply and set-status using ONLY the 8-hex short suffix of thread_id!
        short_handoff = t_handoff["thread_id"].rsplit("-", 1)[-1]
        self.core.add_post(
            short_handoff,
            author="team-a1/lead",
            content="Acknowledged via short ID, starting validation.",
        )
        self.assertTrue(self.core.set_thread_status(short_handoff, "resolved", as_agent="team-a/lead"))

        lines_after = handoff_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines_after), 3)
        self.assertEqual(lines_after[0], line1_before)

        # Missing identity must fail loud
        with self.assertRaises(PermissionError):
            self.core.list_threads()
        with self.assertRaises(PermissionError):
            self.core.get_thread(t_global["thread_id"])
        with self.assertRaises(PermissionError):
            self.core.search("fcntl.flock")
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

        # Search respects visibility
        self.assertEqual(len(self.core.search("fcntl.flock", as_agent="team-a/coder")), 1)
        self.assertEqual(len(self.core.search("fcntl.flock", as_agent="team-a/lead")), 0)
        self.assertEqual(len(self.core.search("fcntl.flock", show_all=True)), 1)

        # Unauthorized view & reply blocked
        with self.assertRaises(PermissionError):
            self.core.get_thread(t_personal["thread_id"], as_agent="team-a/lead")
        with self.assertRaises(PermissionError):
            self.core.add_post(t_team_a["thread_id"], author="team-b/lead", content="Intrusion!")
        with self.assertRaises(PermissionError):
            self.core.add_post(t_handoff["thread_id"], author="team-b/lead", content="Intrusion!")

        # Disable & respawn team-a with brand-new UUIDs -> personal memory still belongs to team-a/coder
        self.core.disable_team("team-a", cascade=True)
        self.core.activate_team("team-a", {"lead": "uuid-a-lead-v2", "coder": "uuid-a-coder-v2"})
        personal_after = self.core.list_threads(as_agent="team-a/coder", visibility="personal")
        self.assertEqual(len(personal_after), 1)
        self.assertEqual(personal_after[0]["id"], t_personal["thread_id"])

        # Non-prime cannot reclassify
        with self.assertRaises(PermissionError):
            self.core.reclassify_thread(
                t_personal["thread_id"], visibility="global", as_agent="team-a/lead"
            )

        # Reclassify personal lesson -> global standard by ULTRON PRIME
        self.core.reclassify_thread(
            t_personal["thread_id"], visibility="global", as_agent="ultron-prime"
        )
        self.assertEqual(len(self.core.search("fcntl.flock", as_agent="team-b/lead")), 1)

    def test_reclassify_target_existence_and_set_status_auth(self) -> None:
        self.core.register_prime("uuid-prime")
        self.core.create_team(slug="team-a", name="Team A", mission="Alpha")
        self.core.create_team(slug="team-b", name="Team B", mission="Beta")

        t = self.core.create_thread(
            title="Scoped Task",
            author="team-a/lead",
            visibility="team",
            content="Task body",
        )
        tid = t["thread_id"]

        self.assertTrue(self.core.set_thread_status(tid, "resolved", as_agent="team-a/lead"))
        with self.assertRaises(PermissionError):
            self.core.set_thread_status(tid, "open", as_agent="team-b/lead")

        with self.assertRaises(ValueError):
            self.core.reclassify_thread(
                tid, visibility="team", team_slug="ghost-team", show_all=True
            )
        with self.assertRaises(ValueError):
            self.core.reclassify_thread(
                tid, visibility="team", team_slug="team-a", with_team="ghost-subteam", show_all=True
            )
        with self.assertRaises(ValueError):
            self.core.reclassify_thread(
                tid, visibility="personal", owner_agent="ghost-team/coder", show_all=True
            )

    def test_punctuation_and_multitoken_search_plus_contacts_warning(self) -> None:
        self.core.register_prime("uuid-prime-live")
        self.core.create_team(slug="parent-t", name="Parent", mission="Parent")
        self.core.create_team(
            slug="child-t", name="Child", mission="Child", parent_team="parent-t"
        )

        self.core.activate_team("child-t", {"lead": "uuid-child"}, allow_detached=True)
        contacts = self.core.get_contacts("child-t/lead")
        self.assertTrue(contacts["parent_disabled_warning"])
        self.assertEqual(contacts["prime_fallback"]["conversation_id"], "uuid-prime-live")

        self.core.create_thread(
            title="JSON Config Syntax",
            author="child-t/lead",
            visibility="personal",
            content='Config snippet: {"strict": true} and status:active OR ("unclosed C++',
        )
        self.assertEqual(
            len(self.core.search('status:active OR ("unclosed', as_agent="child-t/lead")), 1
        )
        # Multi-token split search across title + content
        self.assertEqual(
            len(self.core.search("config c++", as_agent="child-t/lead")), 1
        )
        self.assertEqual(
            len(self.core.search('status:active OR ("unclosed', as_agent="parent-t/lead")), 0
        )

    def test_real_git_branch_union_merge_conflict_free(self) -> None:
        """
        End-to-end Git test: two divergent Git branches concurrently append replies/status
        to the EXACT SAME .jsonl thread AND create separate teams, then `git merge` cleanly
        with zero conflicts thanks to `.gitattributes` (`*.jsonl merge=union`) and Hive manifests!
        """
        def git(*gargs: str) -> None:
            res = subprocess.run(
                ["git", *gargs],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, msg=f"git {gargs} failed: {res.stderr}\n{res.stdout}")

        git("init", "-b", "main")
        git("config", "user.name", "ULTRON Test")
        git("config", "user.email", "ultron@example.com")

        self.core.create_team(slug="shared", name="Shared Team", mission="Shared coordination")
        t = self.core.create_thread(
            title="Cross-Branch Design Thread",
            author="shared/lead",
            visibility="team",
            content="Initial proposal on main.",
        )
        tid = t["thread_id"]

        # Activate team -> verify .runtime/ is gitignored so git status only sees real files!
        self.core.activate_team("shared", {"lead": "uuid-shared-lead"})
        git("add", ".")
        git("commit", "-m", "feat: initial shared team and thread")

        status_after_commit = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertEqual(status_after_commit, "")

        # Branch A: reply + status update + create team-alpha
        git("checkout", "-b", "branch-a")
        core_a = UltronCore(repo_root=self.root)
        core_a.create_team(slug="team-alpha", name="Alpha", mission="Branch A team")
        core_a.add_post(tid, author="shared/lead", content="Reply from branch-a")
        core_a.set_thread_status(tid, "in_progress", as_agent="shared/lead")
        git("add", ".")
        git("commit", "-m", "feat(a): reply and team-alpha")

        # Branch B (from main): reply to SAME thread + create team-beta
        git("checkout", "main")
        git("checkout", "-b", "branch-b")
        core_b = UltronCore(repo_root=self.root)
        core_b.create_team(slug="team-beta", name="Beta", mission="Branch B team")
        core_b.add_post(tid, author="shared/lead", content="Concurrent reply from branch-b")
        git("add", ".")
        git("commit", "-m", "feat(b): concurrent reply and team-beta")

        # Merge branch-a into branch-b -> MUST succeed with zero conflicts!
        git("merge", "--no-edit", "branch-a")

        merged_core = UltronCore(repo_root=self.root)
        self.assertTrue(merged_core.verify()["ok"])
        self.assertEqual(
            {tm["slug"] for tm in merged_core.list_teams()},
            {"shared", "team-alpha", "team-beta"},
        )
        merged_thread = merged_core.get_thread(tid, show_all=True)
        assert merged_thread is not None
        self.assertEqual(merged_thread["status"], "in_progress")
        self.assertEqual(merged_thread["post_count"], 3)
        bodies = [p["content"] for p in merged_thread["posts"]]
        self.assertIn("Reply from branch-a", bodies)
        self.assertIn("Concurrent reply from branch-b", bodies)

    def test_soft_reference_survival_on_team_removal_and_nested_cwd(self) -> None:
        self.core.create_team(slug="root-t", name="Root", mission="Root")
        nested_ws = self.root / "ultron" / "hive" / "root-t" / "roles" / "lead" / "workspace"

        res = self.run_cli("stats", "--json", cwd=nested_ws)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertEqual(json.loads(res.stdout)["total_teams"], 1)

        t1 = self.core.create_thread(
            title="Persistent Knowledge",
            author="root-t/lead",
            visibility="team",
            content="Keep this history across team removals.",
        )
        self.core.remove_team("root-t", delete_files=True)
        self.assertEqual(self.core.get_stats()["total_teams"], 0)
        surviving = self.core.get_thread(t1["thread_id"], show_all=True)
        assert surviving is not None
        self.assertEqual(surviving["title"], "Persistent Knowledge")

    def test_tier2_audit_regressions_ghost_sessions_partial_and_contacts(self) -> None:
        # 1. Layer-1 lead contacts before register-prime must warn parent_disabled_warning=True
        self.core.create_team(slug="ghost", name="Ghost Team", mission="Test ghost sessions")
        self.core.add_role("ghost", "coder", "Coder", "Write code")
        c_unreg = self.core.get_contacts("ghost/lead")
        self.assertIsNone(c_unreg["reports_to"])
        self.assertTrue(c_unreg["parent_disabled_warning"])

        # 2. activate_team --partial MUST still reject inactive lead unless --allow-detached
        with self.assertRaises(ValueError):
            self.core.activate_team("ghost", {"coder": "uuid-coder"}, partial=True)
        # Missing specialist UUID without partial=True must also fail loud
        with self.assertRaises(ValueError):
            self.core.activate_team("ghost", {"lead": "uuid-lead"}, partial=False)
        # With partial=True and lead included, activation succeeds cleanly
        self.core.activate_team("ghost", {"lead": "uuid-lead"}, partial=True)
        self.core.activate_agent("ghost/coder", "uuid-coder")

        # 3. Simulate external branch checkout deleting ultron/hive/ghost while .runtime/sessions.json stays
        shutil.rmtree(self.root / "ultron" / "hive" / "ghost")

        # verify() must detect orphan runtime sessions fail-loud, and --prune-orphans repairs them
        with self.assertRaises(ValueError):
            self.core.verify(prune_orphans=False)

        # Re-inject ghost sessions to also test create_team / add_role automatic purge
        recreated = self.core.create_team(slug="ghost", name="Ghost Reborn", mission="Fresh start")
        self.assertEqual(recreated["status"], "disabled")
        self.assertEqual(recreated["roles"][0]["status"], "disabled")
        self.assertEqual(recreated["roles"][0]["conversation_id"], "")

        # Inject stale role session manually before add_role -> add_role must purge it and start disabled
        sess_path = self.root / "ultron" / "core" / ".runtime" / "sessions.json"
        sess_data = json.loads(sess_path.read_text(encoding="utf-8"))
        sess_data["agents"]["ghost/coder"] = {
            "conversation_id": "stale-coder-uuid",
            "last_seen": "2026-11-07T00:00:00Z",
            "status": "active",
        }
        sess_data["agents"]["orphan-team/lead"] = {
            "conversation_id": "stale-orphan-uuid",
            "last_seen": "2026-11-07T00:00:00Z",
            "status": "active",
        }
        sess_path.write_text(json.dumps(sess_data) + "\n", encoding="utf-8")

        reborn_coder = self.core.add_role("ghost", "coder", "Coder", "Fresh coder")
        self.assertEqual(reborn_coder["status"], "disabled")
        self.assertEqual(reborn_coder["conversation_id"], "")

        # verify --prune-orphans cleans orphan-team/lead
        healed = self.core.verify(prune_orphans=True)
        self.assertEqual(healed["pruned_orphan_sessions"], ["orphan-team/lead"])
        self.assertTrue(self.core.verify(prune_orphans=False)["ok"])

    def test_external_target_repo_inheritance_override_and_spawn(self) -> None:
        ext_game = self.root.parent / "game_dev_trial"
        ext_xcom = self.root.parent / "XCOMBench"

        t_game = self.core.create_team(
            slug="game-team",
            name="Game Dev Team",
            mission="Build game prototype",
            target_repo=str(ext_game),
        )
        self.assertEqual(t_game["target_repo"], str(ext_game))
        self.assertEqual(t_game["target_repo_abs"], str(ext_game.resolve()))

        # Child team inherits parent target_repo automatically when omitted
        t_child = self.core.create_team(
            slug="game-ui",
            name="Game UI Subteam",
            mission="Build HUD",
            parent_team="game-team",
        )
        self.assertEqual(t_child["target_repo"], str(ext_game))

        # Role can optionally override target_repo
        r_override = self.core.add_role(
            team_slug="game-team",
            role="benchmarker",
            title="Benchmark Specialist",
            responsibilities="Run XCOM benchmarks",
            target_repo="~/Dev/XCOMBench",
        )
        self.assertEqual(r_override["target_repo"], "~/Dev/XCOMBench")
        self.assertTrue(r_override["target_repo_abs"].endswith("XCOMBench"))

        # render-spawn injects Dual-Directory Execution Rule
        specs = {s["role"]: s for s in self.core.render_spawn("game-team")}
        self.assertIn("Dual-Directory Execution Rule", specs["lead"]["define_subagent"]["SystemPrompt"])
        self.assertIn(str(ext_game.resolve()), specs["lead"]["define_subagent"]["SystemPrompt"])
        self.assertIn("XCOMBench", specs["benchmarker"]["define_subagent"]["SystemPrompt"])

        # set-target-repo CLI updates and clears cleanly
        res_set = self.run_cli("set-target-repo", "game-team", str(ext_xcom), "--cascade")
        self.assertEqual(res_set.returncode, 0, msg=res.stderr if "res" in locals() else res_set.stderr)
        self.assertEqual(self.core.get_team("game-ui")["target_repo"], str(ext_xcom))

        res_clear = self.run_cli("set-target-repo", "game-team", "--clear", "--cascade")
        self.assertEqual(res_clear.returncode, 0, msg=res_clear.stderr)
        self.assertEqual(self.core.get_team("game-team")["target_repo"], "")
        self.assertEqual(self.core.get_team("game-ui")["target_repo"], "")


if __name__ == "__main__":
    unittest.main()
