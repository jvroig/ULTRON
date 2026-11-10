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
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ultron.core.core import BG_SESSION_ID_RE, PRIME_ID, ROLE_CONTEXT_FILENAME, ROLE_CONTEXT_IMPORT, UltronCore  # noqa: E402


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

    def test_team_blueprints_coding_light_direct_peers_and_save_blueprint(self) -> None:
        bps = self.core.list_blueprints()
        bp_slugs = [b["slug"] for b in bps]
        self.assertIn("coding-light", bp_slugs)
        self.assertIn("tech-docs", bp_slugs)
        self.assertIn("thought-leadership", bp_slugs)

        bp_info = self.core.get_blueprint("coding-light")
        self.assertEqual(bp_info["role_names"], ["lead", "spec", "dev", "qa"])

        td_info = self.core.get_blueprint("tech-docs")
        self.assertEqual(td_info["role_names"], ["lead", "writer", "visualizer", "auditor"])

        tl_info = self.core.get_blueprint("thought-leadership")
        self.assertEqual(
            tl_info["role_names"],
            ["lead", "drafter", "voice-style-qa", "anti-slop-qa"],
        )

        # Instantiate a thought-leadership team and verify both QA gates are read-only
        tl_team = self.core.create_team(
            slug="editorial-pod",
            blueprint="thought-leadership",
            mission="Write launch essay on pure Git-native multi-agent systems",
        )
        self.assertEqual(tl_team["blueprint"], "thought-leadership")
        tl_specs = {s["role"]: s for s in self.core.render_spawn("editorial-pod")}
        self.assertTrue(tl_specs["voice-style-qa"]["read_only_mode"])
        self.assertTrue(tl_specs["anti-slop-qa"]["read_only_mode"])
        self.assertIn(
            "Mandatory Anti-Slop Inspection Categories",
            tl_specs["anti-slop-qa"]["define_subagent"]["SystemPrompt"],
        )

        # Instantiate a tech-docs team and verify auditor is read-only
        td_team = self.core.create_team(
            slug="docs-pod",
            blueprint="tech-docs",
            mission="Document system architecture and visual showcase",
        )
        self.assertEqual(td_team["blueprint"], "tech-docs")
        td_specs = {s["role"]: s for s in self.core.render_spawn("docs-pod")}
        self.assertTrue(td_specs["auditor"]["read_only_mode"])
        self.assertIn(
            "[READ-ONLY ROLE MODE]",
            td_specs["auditor"]["define_subagent"]["SystemPrompt"],
        )
        self.assertIn(
            "Strict Inline SVG Markup Hygiene",
            td_specs["visualizer"]["define_subagent"]["SystemPrompt"],
        )

        # Instantiate a team from coding-light blueprint via CLI without needing --name
        res_ct = self.run_cli(
            "create-team",
            "--slug",
            "alpha-code",
            "--blueprint",
            "coding-light",
            "--mission",
            "Build high-speed parser module",
            "--target-repo",
            "~/Dev/game_dev_trial",
        )
        self.assertEqual(res_ct.returncode, 0, msg=res_ct.stderr)

        team = self.core.get_team("alpha-code")
        assert team is not None
        self.assertEqual(team["blueprint"], "coding-light")
        self.assertEqual(team["name"], "Coding Team Light (alpha-code)")
        self.assertEqual(
            [r["agent_id"] for r in team["roles"]],
            ["alpha-code/lead", "alpha-code/dev", "alpha-code/qa", "alpha-code/spec"],
        )

        # Verify direct intra-team peer contacts
        dev_contacts = self.core.get_contacts("alpha-code/dev")
        self.assertTrue(dev_contacts["direct_peers_allowed"])
        self.assertEqual(
            [p["agent_id"] for p in dev_contacts["team_peers"]],
            ["alpha-code/lead", "alpha-code/qa", "alpha-code/spec"],
        )

        # Verify render-spawn includes blueprint workflow & role-specific protocols
        specs = {s["role"]: s for s in self.core.render_spawn("alpha-code")}
        self.assertIn(
            "Formal Intra-Team Workflow (`coding-light` State Machine)",
            specs["spec"]["define_subagent"]["SystemPrompt"],
        )
        self.assertIn(
            "Phase 4 — Final Spec & Architectural Compliance Audit",
            specs["spec"]["define_subagent"]["SystemPrompt"],
        )
        self.assertIn(
            "Phase 3 — Rigorous Verification Against the Spec",
            specs["qa"]["define_subagent"]["SystemPrompt"],
        )
        self.assertIn(
            "Collaborate Directly Within Your Team:",
            specs["dev"]["define_subagent"]["SystemPrompt"],
        )

        # Test user-extensible save-blueprint -> instantiate round-trip
        saved_bp = self.core.save_blueprint(
            team_slug="alpha-code",
            blueprint_slug="custom-pod",
            name="Custom Engineering Pod",
            description="Exported from alpha-code",
        )
        self.assertEqual(saved_bp["slug"], "custom-pod")
        cloned_team = self.core.create_team(
            slug="beta-code",
            blueprint="custom-pod",
            mission="Build second module",
        )
        self.assertEqual(cloned_team["blueprint"], "custom-pod")
        self.assertEqual(len(cloned_team["roles"]), 4)
        self.assertIn(
            "beta-code/spec",
            (self.root / "ultron" / "hive" / "beta-code" / "AGENTS.md").read_text(encoding="utf-8"),
        )

    def test_export_thread_cli_and_api(self) -> None:
        # Create team and roles for authorization testing
        self.core.create_team(slug="eng", name="Engineering", mission="Engineering pod")
        self.core.add_role("eng", "dev", "Developer", "Code features")
        self.core.create_team(slug="ops", name="Operations", mission="Operations pod")

        # Create a thread with tags and reply
        t = self.core.create_thread(
            title="Export Feature Architecture",
            author="eng/lead",
            visibility="team",
            category="architecture",
            tags="export,cli,api",
            content="Initial proposal for export-thread capability.",
        )
        tid = t["thread_id"]
        short_id = tid.rsplit("-", 1)[-1]
        root_post_id = t["post_id"]

        # Add reply with parent pointer
        reply = self.core.add_post(
            tid,
            author="eng/dev",
            content="Looks solid, proceeding to implement.",
            parent_post_id=root_post_id,
            tags="implementation",
        )
        reply_post_id = reply["post_id"]

        # AC-1: CLI parser registration and help
        res_help = self.run_cli("export-thread", "--help")
        self.assertEqual(res_help.returncode, 0)
        self.assertIn("--format", res_help.stdout)
        self.assertIn("--output", res_help.stdout)
        self.assertIn("--as", res_help.stdout)
        self.assertIn("--all", res_help.stdout)

        # AC-2: Core Python API signature and behavior (full, short, and '#' prefixed ID)
        md_full = self.core.export_thread(tid, format="md", show_all=True)
        md_short = self.core.export_thread(short_id, format="md", show_all=True)
        md_hash = self.core.export_thread(f"#{tid}", format="md", show_all=True)
        self.assertEqual(md_full, md_short)
        self.assertEqual(md_full, md_hash)
        self.assertIsInstance(md_full, str)

        json_full = self.core.export_thread(tid, format="json", show_all=True)
        json_short = self.core.export_thread(short_id, format="json", show_all=True)
        self.assertEqual(json_full, json_short)

        # Case-insensitivity check in API
        self.assertEqual(self.core.export_thread(tid, format="MD", show_all=True), md_full)
        self.assertEqual(self.core.export_thread(tid, format="JSON", show_all=True), json_full)

        # Edge case: single-post thread with empty tags (no replies, tags omitted)
        solo = self.core.create_thread(
            title="Solo Note",
            author="eng/lead",
            visibility="team",
            category="task",
            content="Just a note without replies or tags.",
        )
        md_solo = self.core.export_thread(solo["thread_id"], show_all=True)
        self.assertIn(f"# Thread: Solo Note ({solo['thread_id']})", md_solo)
        self.assertIn("- **Total Posts:** 1", md_solo)
        self.assertNotIn("- **Tags:**", md_solo)
        self.assertIn("## Root Post", md_solo)
        self.assertNotIn("## Reply", md_solo)

        # AC-3: Markdown export formatting fidelity
        self.assertTrue(md_full.startswith(f"# Thread: Export Feature Architecture ({tid})"))
        self.assertIn(f"- **Thread ID:** `{tid}`", md_full)
        self.assertIn("- **Category:** `architecture`", md_full)
        self.assertIn("- **Status:** `open`", md_full)
        self.assertIn("- **Visibility:** `team`", md_full)
        self.assertIn("- **Scope:** `team:eng`", md_full)
        self.assertIn("- **Author:** `@eng/lead`", md_full)
        self.assertIn("- **Total Posts:** 2", md_full)
        self.assertIn("---", md_full)
        self.assertIn(f"## Root Post ({root_post_id})", md_full)
        self.assertIn("- **Author:** `@eng/lead`", md_full)
        self.assertIn("- **Tags:** [export,cli,api]", md_full)
        self.assertIn("Initial proposal for export-thread capability.", md_full)
        self.assertIn(f"## Reply ({reply_post_id})", md_full)
        self.assertIn("- **Author:** `@eng/dev`", md_full)
        self.assertIn(f"- **In Reply To:** {root_post_id}", md_full)
        self.assertIn("- **Tags:** [implementation]", md_full)
        self.assertIn("Looks solid, proceeding to implement.", md_full)

        # AC-4: JSON export formatting fidelity
        data = json.loads(json_full)
        self.assertEqual(data["id"], tid)
        self.assertEqual(data["title"], "Export Feature Architecture")
        self.assertEqual(data["category"], "architecture")
        self.assertEqual(data["status"], "open")
        self.assertEqual(data["visibility"], "team")
        self.assertEqual(data["team_slug"], "eng")
        self.assertEqual(data["post_count"], 2)
        self.assertEqual(len(data["posts"]), 2)
        self.assertEqual(data["posts"][0]["id"], root_post_id)
        self.assertEqual(data["posts"][0]["tags"], "export,cli,api")
        self.assertEqual(data["posts"][1]["id"], reply_post_id)
        self.assertEqual(data["posts"][1]["parent_post_id"], root_post_id)
        self.assertEqual(data["posts"][1]["tags"], "implementation")
        # Ensure indent=2 sort_keys=True
        expected_json = json.dumps(data, indent=2, sort_keys=True)
        self.assertEqual(json_full, expected_json)

        # AC-5: CLI output routing - stdout (default md and explicit json)
        res_cli_md = self.run_cli("export-thread", tid, "--as", "eng/lead")
        self.assertEqual(res_cli_md.returncode, 0)
        self.assertEqual(res_cli_md.stdout, md_full)

        res_cli_json = self.run_cli("export-thread", tid, "--format", "json", "--as", "eng/lead")
        self.assertEqual(res_cli_json.returncode, 0)
        self.assertEqual(json.loads(res_cli_json.stdout), data)

        # AC-6: CLI file output with nested directory creation and confirmation message
        nested_out_md = self.root / "exports" / "nested" / "dirs" / "thread.md"
        self.assertFalse(nested_out_md.parent.exists())
        res_file_md = self.run_cli(
            "export-thread", tid, "--output", str(nested_out_md), "--as", "eng/lead"
        )
        self.assertEqual(res_file_md.returncode, 0)
        self.assertIn(
            f"[ULTRON] Exported thread '{tid}' to {nested_out_md} (md).",
            res_file_md.stdout,
        )
        self.assertTrue(nested_out_md.is_file())
        self.assertEqual(nested_out_md.read_text(encoding="utf-8"), md_full)

        # File export overwrite test via API and CLI
        nested_out_json = self.root / "exports" / "nested" / "dirs" / "thread.json"
        res_api_file = self.core.export_thread(
            tid, format="json", output_path=nested_out_json, as_agent="eng/lead"
        )
        self.assertEqual(res_api_file, json_full)
        self.assertEqual(nested_out_json.read_text(encoding="utf-8"), json_full)

        # Overwrite with CLI
        res_file_ovw = self.run_cli(
            "export-thread",
            tid,
            "--format",
            "json",
            "--output",
            str(nested_out_json),
            "--as",
            "eng/lead",
        )
        self.assertEqual(res_file_ovw.returncode, 0)
        self.assertIn(
            f"[ULTRON] Exported thread '{tid}' to {nested_out_json} (json).",
            res_file_ovw.stdout,
        )

        # AC-7: Fail-loud missing thread handling
        with self.assertRaises(ValueError) as ctx_missing:
            self.core.export_thread("t-20261108-nonexistent", show_all=True)
        self.assertIn("not found", str(ctx_missing.exception))

        res_missing_cli = self.run_cli("export-thread", "t-20261108-nonexistent", "--all")
        self.assertEqual(res_missing_cli.returncode, 1)
        self.assertIn("[ULTRON Error]", res_missing_cli.stderr)
        self.assertIn("not found", res_missing_cli.stderr)

        # AC-8: Fail-loud visibility and permission enforcement
        # ops/lead should NOT be able to view eng team-private thread
        with self.assertRaises(PermissionError) as ctx_perm:
            self.core.export_thread(tid, as_agent="ops/lead")
        self.assertIn("not authorized", str(ctx_perm.exception))

        res_perm_cli = self.run_cli("export-thread", tid, "--as", "ops/lead")
        self.assertEqual(res_perm_cli.returncode, 1)
        self.assertIn("[ULTRON Error]", res_perm_cli.stderr)
        self.assertIn("not authorized", res_perm_cli.stderr)

        # But with --all or show_all=True it succeeds
        res_perm_all = self.run_cli("export-thread", tid, "--all")
        self.assertEqual(res_perm_all.returncode, 0)

        # AC-9: Fail-loud format validation
        with self.assertRaises(ValueError) as ctx_fmt:
            self.core.export_thread(tid, format="xml", show_all=True)
        self.assertIn("Invalid export format 'xml'", str(ctx_fmt.exception))

        res_bad_fmt = self.run_cli("export-thread", tid, "--format", "xml", "--all")
        self.assertNotEqual(res_bad_fmt.returncode, 0)
        self.assertIn("invalid choice", res_bad_fmt.stderr)

    def test_legacy_model_names_load_as_neutral_tiers(self) -> None:
        self.core.create_team(slug="api", name="API", mission="m", default_model="pro")
        self.core.add_role(team_slug="api", role="coder", title="Coder", responsibilities="r", model="flash_lite")
        agents = {a["agent_id"]: a for a in self.core.list_agents(team_slug="api")}
        self.assertEqual(agents["api/lead"]["model"], "large")
        self.assertEqual(agents["api/coder"]["model"], "small")

        role_json = self.root / "ultron/hive/api/roles/coder/role.json"
        raw = json.loads(role_json.read_text(encoding="utf-8"))
        raw["model"] = "flash"
        role_json.write_text(json.dumps(raw), encoding="utf-8")
        agents = {a["agent_id"]: a for a in self.core.list_agents(team_slug="api")}
        self.assertEqual(agents["api/coder"]["model"], "medium")

    def test_unknown_model_tier_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.core.create_team(slug="api", name="API", mission="m", default_model="gpt")
        res = self.run_cli("create-team", "--slug", "api", "--name", "API", "--mission", "m", "--model", "gpt")
        self.assertNotEqual(res.returncode, 0)
        res = self.run_cli("create-team", "--slug", "api", "--name", "API", "--mission", "m", "--model", "pro")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.core.get_team("api")["default_model"], "large")


FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as log:
    log.write(json.dumps({"args": args, "cwd": os.getcwd()}) + "\\n")
if args[0] == "--bg":
    name = args[args.index("-n") + 1]
    if name == os.environ.get("FAKE_CLAUDE_FAIL_NAME"):
        print("launch refused", file=sys.stderr)
        sys.exit(1)
    count = sum(1 for _ in open(os.environ["FAKE_CLAUDE_LOG"]))
    print(f"  claude attach {count:08x}    open in this terminal")
elif args[0] == "stop":
    if args[1] == os.environ.get("FAKE_CLAUDE_FAIL_STOP"):
        print("No job matching", file=sys.stderr)
        sys.exit(1)
    print(f"stopped {args[1]}")
"""


class ClaudeCodeLifecycleTestCase(unittest.TestCase):
    tearDown = UltronCoreTestCase.tearDown
    run_cli = UltronCoreTestCase.run_cli

    def setUp(self) -> None:
        UltronCoreTestCase.setUp(self)
        self.fake_bin = self.root / "fake_claude"
        self.fake_bin.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.fake_bin.chmod(0o755)
        self.call_log = self.root / "claude_calls.jsonl"
        env = {"ULTRON_CLAUDE_BIN": str(self.fake_bin), "FAKE_CLAUDE_LOG": str(self.call_log),
               "ULTRON_HARNESS": "claude-code"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for marker in ("CLAUDE_CODE_SESSION_ID", "ANTIGRAVITY_AGENT", "ANTIGRAVITY_CONVERSATION_ID"):
            os.environ.pop(marker, None)
        self.core.create_team(slug="api", name="API", mission="m", default_model="large")
        self.core.add_role(team_slug="api", role="coder", title="Coder", responsibilities="r", model="small")

    def calls(self) -> list[dict]:
        if not self.call_log.exists():
            return []
        return [json.loads(line) for line in self.call_log.read_text(encoding="utf-8").splitlines()]

    def role_dir(self, role: str) -> Path:
        return self.root / "ultron" / "hive" / "api" / "roles" / role

    def test_scaffolded_role_charters_import_the_generated_context(self) -> None:
        for role in ("lead", "coder"):
            lines = (self.role_dir(role) / "AGENTS.md").read_text(encoding="utf-8").splitlines()
            self.assertIn(ROLE_CONTEXT_IMPORT, lines)

    def test_spawn_launches_each_role_in_its_own_folder_lead_first_and_binds_names(self) -> None:
        res = self.core.spawn_team("api", mission_brief="Build it")
        bg_calls = [c for c in self.calls() if c["args"][0] == "--bg"]
        self.assertEqual([Path(c["cwd"]).resolve() for c in bg_calls],
                         [self.role_dir("lead").resolve(), self.role_dir("coder").resolve()])
        lead_args = bg_calls[0]["args"]
        self.assertIn("Build it", lead_args[1])
        self.assertEqual(lead_args[lead_args.index("-n") + 1], "ultron--api--lead")
        self.assertEqual(lead_args[lead_args.index("--model") + 1], "opus")
        self.assertIn("--dangerously-skip-permissions", lead_args)
        coder_args = bg_calls[1]["args"]
        self.assertEqual(coder_args[coder_args.index("--model") + 1], "haiku")

        self.assertEqual(self.core.get_team("api")["status"], "active")
        whois = self.run_cli("whois", "api/coder", "--id-only")
        self.assertEqual(whois.stdout.strip(), "ultron--api--coder")
        self.assertEqual({s["agent_id"] for s in res["sessions"]}, {"api/lead", "api/coder"})

    def test_generated_context_uses_absolute_core_path_and_is_gitignored(self) -> None:
        self.core.spawn_team("api")
        ctx = (self.role_dir("coder") / ROLE_CONTEXT_FILENAME).read_text(encoding="utf-8")
        self.assertIn(str(self.root / "ultron" / "core" / "core.py"), ctx)
        self.assertNotIn("python3 ultron/core/core.py", ctx)
        self.assertIn("ultron--api--coder", ctx)
        self.assertNotIn("{{", ctx)

        shutil.copy2(REPO_ROOT / ".gitignore", self.root / ".gitignore")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(self.role_dir("coder") / ROLE_CONTEXT_FILENAME)],
            cwd=self.root,
        )
        self.assertEqual(ignored.returncode, 0)

    def test_spawn_lets_each_role_edit_the_shared_checkout_without_a_worktree(self) -> None:
        self.core.spawn_team("api")
        settings_path = self.role_dir("coder") / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(settings["worktree"]["bgIsolation"], "none")
        self.assertIn("Agent", settings["permissions"]["deny"])
        self.assertIn("Bash(claude *)", settings["permissions"]["deny"])

        shutil.copy2(REPO_ROOT / ".gitignore", self.root / ".gitignore")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        ignored = subprocess.run(["git", "check-ignore", "-q", str(settings_path)], cwd=self.root)
        self.assertEqual(ignored.returncode, 0)

    def test_target_repo_is_passed_as_add_dir_with_equals_so_it_cannot_swallow_the_prompt(self) -> None:
        target = self.root / "target"
        target.mkdir()
        self.core.set_target_repo(team_slug="api", target_repo=str(target))
        self.core.spawn_team("api")
        for call in (c for c in self.calls() if c["args"][0] == "--bg"):
            self.assertEqual(call["args"][0:1], ["--bg"])
            self.assertNotIn("--add-dir", call["args"])
            self.assertIn(f"--add-dir={target.resolve()}", call["args"])

    def test_spawn_refuses_a_claude_md_above_the_role_folder(self) -> None:
        (self.root / "ultron" / "CLAUDE.md").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "CLAUDE.md"):
            self.core.spawn_team("api")
        self.assertEqual(self.calls(), [])

    def test_spawn_refuses_a_role_charter_without_the_context_import(self) -> None:
        charter = self.role_dir("coder") / "AGENTS.md"
        charter.write_text("# charter only\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, ROLE_CONTEXT_IMPORT):
            self.core.spawn_team("api")
        self.assertEqual(self.calls(), [])

    def test_a_failed_launch_stops_the_roles_already_launched_and_leaves_team_disabled(self) -> None:
        with mock.patch.dict(os.environ, {"FAKE_CLAUDE_FAIL_NAME": "ultron--api--coder"}):
            with self.assertRaisesRegex(RuntimeError, "launch refused"):
                self.core.spawn_team("api")
        stops = [c["args"] for c in self.calls() if c["args"][0] == "stop"]
        self.assertEqual(stops, [["stop", "00000001"]])
        self.assertEqual(self.core.get_team("api")["status"], "disabled")

    def test_stop_team_stops_by_session_id_not_name_then_disables(self) -> None:
        self.core.spawn_team("api")
        res = self.core.stop_team("api")
        stops = sorted(c["args"][1] for c in self.calls() if c["args"][0] == "stop")
        self.assertEqual(stops, ["00000001", "00000002"])
        self.assertEqual(res["stop_failures"], {})
        self.assertEqual(self.core.get_team("api")["status"], "disabled")

    def test_stop_team_cli_exits_nonzero_when_a_session_will_not_stop(self) -> None:
        self.core.spawn_team("api")
        res = self.run_cli("stop-team", "api", env_extra={"FAKE_CLAUDE_FAIL_STOP": "00000002"})
        self.assertEqual(res.returncode, 1)
        self.assertIn("api/coder", res.stderr)
        self.assertEqual(self.core.get_team("api")["status"], "disabled")

    def test_harness_comes_from_flag_then_env_then_claude_code_detection(self) -> None:
        from ultron.core.core import resolve_harness

        self.assertEqual(resolve_harness("antigravity"), "antigravity")
        self.assertEqual(resolve_harness(), "claude-code")
        with mock.patch.dict(os.environ, {"ULTRON_HARNESS": "", "CLAUDE_CODE_SESSION_ID": "x"}):
            self.assertEqual(resolve_harness(), "claude-code")
        with mock.patch.dict(os.environ, {"ULTRON_HARNESS": ""}):
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            with self.assertRaisesRegex(ValueError, "--harness"):
                resolve_harness()
        with self.assertRaisesRegex(ValueError, "Unknown harness"):
            resolve_harness("cursor")

    def test_antigravity_spawn_returns_a_plan_for_prime_and_launches_nothing(self) -> None:
        res = self.core.spawn_team("api", harness="antigravity")
        self.assertEqual(res["status"], "awaiting_prime")
        self.assertEqual({sp["agent_id"] for sp in res["specs"]}, {"api/lead", "api/coder"})
        self.assertTrue(any("activate-team api" in step for step in res["next_steps"]))
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.core.get_team("api")["status"], "disabled")

    def test_antigravity_stop_returns_a_kill_plan_and_leaves_the_team_active(self) -> None:
        self.core.activate_team("api", {"lead": "uuid-lead", "coder": "uuid-coder"})
        res = self.core.stop_team("api", harness="antigravity")
        self.assertEqual(res["status"], "awaiting_prime")
        self.assertIn("uuid-coder", res["next_steps"][0])
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.core.get_team("api")["status"], "active")

    def test_spawn_refuses_a_harness_other_than_prime_runs_on(self) -> None:
        self.core.register_prime("prime-session", harness="antigravity")
        with self.assertRaisesRegex(ValueError, "cannot doorbell each other"):
            self.core.spawn_team("api", harness="claude-code")
        self.assertEqual(self.calls(), [])

    def test_register_prime_records_the_detected_harness(self) -> None:
        res = self.run_cli("register-prime", "--id", "prime-session")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.core.get_prime_harness(), "claude-code")

    def test_render_spawn_cli_prints_each_harness_without_crashing(self) -> None:
        for harness, marker in (("claude-code", "ultron--api--coder"), ("antigravity", "TypeName=ultron--api--coder")):
            with self.subTest(harness=harness):
                res = self.run_cli("render-spawn", "api", "--harness", harness)
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertIn(marker, res.stdout)

    def test_an_antigravity_session_needs_no_harness_flag(self) -> None:
        del os.environ["ULTRON_HARNESS"]
        os.environ["ANTIGRAVITY_CONVERSATION_ID"] = "conv-1"
        res = self.run_cli("render-spawn", "api")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("TypeName=ultron--api--coder", res.stdout)

    def test_without_env_markers_the_harness_follows_prime(self) -> None:
        self.core.register_prime("prime-uuid", harness="antigravity")
        del os.environ["ULTRON_HARNESS"]
        res = self.run_cli("stop-team", "api")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("on antigravity", res.stdout)

    def test_activate_team_records_the_harness(self) -> None:
        self.core.register_prime("prime-uuid", harness="antigravity")
        del os.environ["ULTRON_HARNESS"]
        res = self.run_cli("activate-team", "api", "--uuids", json.dumps({"lead": "u1", "coder": "u2"}))
        self.assertEqual(res.returncode, 0, res.stderr)
        sessions = json.loads((self.core.sessions_file).read_text(encoding="utf-8"))
        self.assertEqual(sessions["agents"]["api/coder"]["harness"], "antigravity")

    def test_antigravity_system_prompt_omits_the_claude_import_line(self) -> None:
        for spec in self.core.render_spawn("api", harness="antigravity"):
            self.assertNotIn(ROLE_CONTEXT_IMPORT, spec["define_subagent"]["SystemPrompt"])

    def test_session_id_parsing_accepts_non_hex_ids(self) -> None:
        match = BG_SESSION_ID_RE.search("  claude attach 3f2a9c1e-bg_Z7    open in this terminal")
        self.assertEqual(match.group(1), "3f2a9c1e-bg_Z7")

    def test_spawn_refuses_an_already_active_team(self) -> None:
        self.core.spawn_team("api")
        with self.assertRaisesRegex(ValueError, "already active"):
            self.core.spawn_team("api")


class RenderSpawnGoldenTestCase(unittest.TestCase):
    def assert_matches_golden(self, harness: str) -> None:
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from render_spawn_fixture import build_fixture_hive, render_all

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            rendered = render_all(build_fixture_hive(root), root, harness) + "\n"
        golden = (REPO_ROOT / "tests" / "golden" / f"render_spawn_{harness}.json").read_text(encoding="utf-8")
        self.assertEqual(rendered, golden)

    def test_antigravity_spawn_output_is_unchanged(self) -> None:
        self.assert_matches_golden("antigravity")

    def test_claude_code_spawn_output_is_unchanged(self) -> None:
        self.assert_matches_golden("claude-code")


class HarnessAdapterContractTestCase(unittest.TestCase):
    FOREIGN_TOOL_NAMES = {
        "claude-code": ["run_command", "write_file", "edit_file", "read_file", "grep_search",
                        "find_by_name", "send_message", "manage_task", "WaitMsBeforeAsync"],
        "antigravity": ["SendMessage", "EnterWorktree", "`Bash`", "`Write`", "`Edit`"],
    }
    SHARED_SPEC_KEYS = {"agent_id", "team_slug", "role", "read_only_mode", "target_repo", "target_repo_abs"}

    def setUp(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from render_spawn_fixture import build_fixture_hive

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.core = build_fixture_hive(Path(tmp.name).resolve())

    def render(self, harness: str) -> list[dict]:
        return [sp for team in ("api", "auth") for sp in self.core.render_spawn(team, harness=harness)]

    def test_no_adapter_leaks_another_harness_tool_names(self) -> None:
        for harness, foreign in self.FOREIGN_TOOL_NAMES.items():
            text = json.dumps(self.render(harness))
            for name in foreign:
                with self.subTest(harness=harness, tool=name):
                    self.assertNotIn(name, text)

    def test_every_adapter_maps_every_model_tier(self) -> None:
        from ultron.core.core import HARNESS_ADAPTERS, MODEL_TIERS

        for adapter in HARNESS_ADAPTERS.values():
            for tier in MODEL_TIERS:
                with self.subTest(harness=adapter.name, tier=tier):
                    self.assertTrue(adapter.model_for_tier.get(tier))

    def test_every_adapter_reports_the_same_role_identity_fields(self) -> None:
        by_harness = {h: self.render(h) for h in self.FOREIGN_TOOL_NAMES}
        for harness, specs in by_harness.items():
            for sp in specs:
                with self.subTest(harness=harness, agent=sp["agent_id"]):
                    self.assertLessEqual(self.SHARED_SPEC_KEYS, set(sp))
        identity = {h: [{k: sp[k] for k in self.SHARED_SPEC_KEYS} for sp in specs] for h, specs in by_harness.items()}
        self.assertEqual(identity["antigravity"], identity["claude-code"])

    def test_unknown_harness_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown harness"):
            self.render("cursor")


if __name__ == "__main__":
    unittest.main()
