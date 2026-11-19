#!/usr/bin/env python3
"""Unit & integration tests for strictly read-only ULTRON Mission Control (ultron/core/web.py)."""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ultron.core.core import UltronCore  # noqa: E402
from ultron.core.web import CSP_HEADER, create_server  # noqa: E402


class UltronWebServerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.core = UltronCore(repo_root=self.root)
        self.assets_dir = self.root / "_test_assets"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        (self.assets_dir / "index.html").write_text("<!doctype html><h1>ULTRON</h1>", encoding="utf-8")
        (self.assets_dir / "tokens.css").write_text(":root { --bg: #000; }", encoding="utf-8")
        (self.assets_dir / "styles.css").write_text("body { margin: 0; }", encoding="utf-8")
        (self.assets_dir / "sprites.js").write_text("window.UltronSprites = {};", encoding="utf-8")
        (self.assets_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")

        self.server = create_server(
            self.core, host="127.0.0.1", port=0, assets_dir=self.assets_dir, quiet=True
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self._tmp.cleanup()

    def request(
        self, method: str, path: str, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, headers=headers or {})
            resp = conn.getresponse()
            body = resp.read()
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, resp_headers, body
        finally:
            conn.close()

    def test_zero_state_health_snapshot_and_no_lazy_dir_side_effects(self) -> None:
        status, headers, body = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")
        health = json.loads(body.decode("utf-8"))
        self.assertTrue(health["ok"])
        self.assertTrue(health["read_only"])

        status, snap_headers, snap_body = self.request("GET", "/api/snapshot")
        self.assertEqual(status, 200)
        etag = snap_headers["etag"]
        snap = json.loads(snap_body.decode("utf-8"))
        self.assertEqual(snap["prime"]["status"], "unregistered")
        self.assertEqual(snap["teams"], [])
        self.assertEqual(snap["projects"], [])
        self.assertEqual(snap["decisions"], [])
        self.assertEqual(snap["threads"], [])

        # Zero lazy directories created by health, snapshot, or verify
        status, _, v_body = self.request("GET", "/api/verify")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(v_body.decode("utf-8"))["ok"])
        self.assertFalse((self.root / "ultron" / "core" / "projects").exists())
        self.assertFalse((self.root / "ultron" / "core" / "decisions").exists())

        # Conditional ETag -> 304 Not Modified (exact and weak form)
        for inm in (etag, f"W/{etag}", f'"deadbeef", {etag}'):
            with self.subTest(if_none_match=inm):
                st_304, h_304, b_304 = self.request(
                    "GET", "/api/snapshot", headers={"If-None-Match": inm}
                )
                self.assertEqual(st_304, 304)
                self.assertEqual(b_304, b"")
                self.assertEqual(h_304["etag"], etag)

    def test_strictly_read_only_rejects_mutating_methods_and_traversal(self) -> None:
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=method):
                status, headers, body = self.request(method, "/api/snapshot")
                self.assertEqual(status, 405)
                self.assertEqual(headers.get("allow"), "GET, HEAD")
                data = json.loads(body.decode("utf-8"))
                self.assertFalse(data["ok"])
                self.assertIn("read-only", data["error"])

        # Static index + allowed assets + HEAD behavior
        st_idx, h_idx, b_idx = self.request("GET", "/")
        self.assertEqual(st_idx, 200)
        self.assertEqual(h_idx.get("content-security-policy"), CSP_HEADER)
        self.assertIn(b"ULTRON", b_idx)

        st_head, h_head, b_head = self.request("HEAD", "/assets/tokens.css")
        self.assertEqual(st_head, 200)
        self.assertIn("text/css", h_head.get("content-type", ""))
        self.assertGreater(int(h_head["content-length"]), 0)
        self.assertEqual(b_head, b"")

        # Traversal & non-allowlisted asset attempts -> 404
        for bad_path in (
            "/assets/../core.py",
            "/assets/%2e%2e/core.py",
            "/assets/..%5ccore.py",
            "/assets/evil.js",
            "/assets/",
            "/api/unknown",
        ):
            with self.subTest(bad_path=bad_path):
                st_bad, _, _ = self.request("GET", bad_path)
                self.assertEqual(st_bad, 404)

    def test_snapshot_invalidation_detail_routes_and_verify_failure(self) -> None:
        _, h0, _ = self.request("GET", "/api/snapshot")
        etag0 = h0["etag"]

        self.core.register_prime("prime-ui-addr", harness="antigravity")
        self.core.create_project(slug="alpha", name="Alpha Project", repo_path="~/Dev/alpha")
        self.core.create_team(
            slug="core-eng",
            name="Core Eng",
            mission="Build core API",
            project="alpha",
            lifespan="permanent",
        )
        self.core.add_role("core-eng", "reviewer", "Auditor", "Audit diffs", write_tools=False)
        d1 = self.core.log_decision(
            title="JSONL Format",
            decision="Use union-merge append-only JSONL.",
            rationale="Conflict-free branch merges.",
            origin="prime_autonomous",
            project_slug="alpha",
        )
        self.core.review_decision(
            d1["id"],
            review_status="approved",
            notes="Looks solid.",
            replacement_decision="Use union-merge JSONL across threads and decisions.",
        )
        t1 = self.core.create_thread(
            title="Kickoff",
            author="core-eng/lead",
            visibility="team",
            content="Initial task spec.",
        )
        self.core.add_post(t1["thread_id"], author="core-eng/reviewer", content="Audit complete.")

        # ETag changed -> 200 even if client passes old ETag
        st_new, h1, body1 = self.request(
            "GET", "/api/snapshot", headers={"If-None-Match": etag0}
        )
        self.assertEqual(st_new, 200)
        self.assertNotEqual(h1["etag"], etag0)
        snap = json.loads(body1.decode("utf-8"))
        self.assertEqual(snap["prime"]["status"], "active")
        self.assertEqual(len(snap["projects"]), 1)
        self.assertEqual(len(snap["teams"]), 1)
        self.assertEqual(len(snap["decisions"]), 1)
        self.assertEqual(len(snap["threads"]), 1)

        # Thread detail by short suffix
        short_tid = t1["thread_id"].rsplit("-", 1)[-1]
        st_t, _, b_t = self.request("GET", f"/api/threads/{short_tid}")
        self.assertEqual(st_t, 200)
        t_detail = json.loads(b_t.decode("utf-8"))
        self.assertEqual(len(t_detail["posts"]), 2)
        self.assertEqual(self.request("GET", "/api/threads/deadbeef")[0], 404)

        # Decision detail by short suffix + ambiguous suffix -> 400
        short_did = d1["id"].rsplit("-", 1)[-1]
        st_d, _, b_d = self.request("GET", f"/api/decisions/{short_did}")
        self.assertEqual(st_d, 200)
        d_detail = json.loads(b_d.decode("utf-8"))
        self.assertEqual(
            d_detail["decision"],
            "Use union-merge JSONL across threads and decisions.",
        )
        self.assertEqual(d_detail["original_decision"], "Use union-merge append-only JSONL.")
        self.assertEqual(len(d_detail["reviews"]), 1)
        self.assertEqual(self.request("GET", "/api/decisions/missing1")[0], 404)

        # Ambiguous decision short ID returns 400 cleanly
        dup_path = self.root / "ultron/core/decisions/d-20261119-abcd1234.jsonl"
        dup_path2 = self.root / "ultron/core/decisions/d-20261120-abcd1234.jsonl"
        ev = {
            "created_at": "2026-11-19T00:00:00Z",
            "decided_by": "ultron-prime",
            "decision": "X",
            "decision_id": "d-20261119-abcd1234",
            "event_id": "e-1",
            "origin": "prime_autonomous",
            "project_slug": "",
            "rationale": "",
            "review_status": "pending_review",
            "scope": "global",
            "tags": "",
            "team_slug": "",
            "title": "X",
            "type": "decision",
        }
        dup_path.write_text(json.dumps(ev) + "\n", encoding="utf-8")
        dup_path2.write_text(
            json.dumps({**ev, "decision_id": "d-20261120-abcd1234", "event_id": "e-2"}) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(self.request("GET", "/api/decisions/abcd1234")[0], 400)

        # Liveness endpoint succeeds on Antigravity plan (no external binary required)
        st_live, _, b_live = self.request("GET", "/api/liveness")
        self.assertEqual(st_live, 200)
        self.assertTrue(json.loads(b_live.decode("utf-8"))["ok"])

        # Dangling missing project triggers ok: False in /api/verify (fail loud)
        (self.root / "ultron/core/projects/alpha.json").unlink()
        st_ver, _, b_ver = self.request("GET", "/api/verify")
        self.assertEqual(st_ver, 200)
        ver_data = json.loads(b_ver.decode("utf-8"))
        self.assertFalse(ver_data["ok"])
        self.assertIn("missing project 'alpha'", ver_data["error"])

    def test_core_ui_cli_help_and_prime_only_guard(self) -> None:
        help_res = subprocess.run(
            [sys.executable, str(REPO_ROOT / "ultron/core/core.py"), "ui", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(help_res.returncode, 0, msg=help_res.stderr)
        self.assertIn("--port", help_res.stdout)
        self.assertIn("--no-open", help_res.stdout)

        denied_env = {**os.environ, "ULTRON_AGENT_ID": "core-eng/reviewer"}
        denied_res = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "ultron/core/core.py"),
                "--root",
                str(self.root),
                "ui",
                "--no-open",
            ],
            capture_output=True,
            text=True,
            env=denied_env,
            check=False,
        )
        self.assertEqual(denied_res.returncode, 1)
        self.assertIn("ultron-prime only", denied_res.stderr)

        with mock.patch("ultron.core.web.serve", return_value=0) as mocked_serve:
            from ultron.core.core import main as core_main

            rc = core_main(["--root", str(self.root), "ui", "--port", "8491", "--no-open"])
            self.assertEqual(rc, 0)
            mocked_serve.assert_called_once()
            call_args, kwargs = mocked_serve.call_args
            self.assertEqual(call_args[0].repo_root, self.root)
            self.assertEqual(kwargs["host"], "127.0.0.1")
            self.assertEqual(kwargs["port"], 8491)
            self.assertFalse(kwargs["open_browser"])

    def test_tier2_web_audit_fixes_and_cli_flag_ordering(self) -> None:
        from ultron.core.web import compute_state_etag, main as web_main

        # 1. Keep-alive POST with body returns 405 + Connection: close; subsequent GET works cleanly
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(
                "POST",
                "/api/snapshot",
                body=b'{"x":1}',
                headers={"Content-Type": "application/json", "Content-Length": "7"},
            )
            r1 = conn.getresponse()
            r1.read()
            self.assertEqual(r1.status, 405)
            self.assertEqual(r1.getheader("connection"), "close")
            conn.request("GET", "/api/health")
            r2 = conn.getresponse()
            self.assertEqual(r2.status, 200)
            self.assertTrue(json.loads(r2.read().decode("utf-8"))["ok"])
        finally:
            conn.close()

        # 2. Backslash & null-byte refs return 404 (not 400/500)
        self.assertEqual(self.request("GET", "/api/threads/..%5Ccore")[0], 404)
        self.assertEqual(self.request("GET", "/api/decisions/bad%00id")[0], 404)

        # 3. compute_state_etag reflects blueprints_dir changes
        etag_before = compute_state_etag(self.core)
        bp_dir = self.root / "ultron/core/blueprints/custom-bp"
        bp_dir.mkdir(parents=True, exist_ok=True)
        (bp_dir / "blueprint.json").write_text('{"slug":"custom-bp"}\n', encoding="utf-8")
        self.assertNotEqual(compute_state_etag(self.core), etag_before)

        # 4. Concurrent ETag change during build_snapshot retries & never poisons cache
        etags = iter(['"etag-a"', '"etag-b"', '"etag-c"', '"etag-c"'])
        with (
            mock.patch("ultron.core.web.compute_state_etag", side_effect=lambda _c: next(etags)),
            mock.patch("ultron.core.web.build_snapshot", return_value={"snap": 1}),
        ):
            st, et, body = self.server.get_snapshot_payload(None)
            self.assertEqual(st, 200)
            self.assertEqual(et, '"etag-c"')
            self.assertEqual(self.server._cached_etag, '"etag-c"')
            self.assertIsNotNone(body)

        # Persistent ETag churn across both retries does not poison cache with stale tag
        self.server._cached_etag = None
        self.server._cached_snapshot = None
        churn_etags = iter(['"e1"', '"e2"', '"e3"', '"e4"'])
        with (
            mock.patch("ultron.core.web.compute_state_etag", side_effect=lambda _c: next(churn_etags)),
            mock.patch("ultron.core.web.build_snapshot", return_value={"snap": 2}),
        ):
            st2, et2, _ = self.server.get_snapshot_payload(None)
            self.assertEqual(st2, 200)
            self.assertEqual(et2, '"e4"')
            self.assertIsNone(self.server._cached_etag)

        # 5. Direct web.py main() enforces ULTRON_AGENT_ID prime-only guard
        import contextlib
        import io

        err_buf = io.StringIO()
        with (
            mock.patch.dict(os.environ, {"ULTRON_AGENT_ID": "team/coder"}),
            contextlib.redirect_stderr(err_buf),
        ):
            self.assertEqual(web_main(["--root", str(self.root), "--no-open"]), 1)
        self.assertIn("ultron-prime only", err_buf.getvalue())

        # 6. CLI --root and --json work both BEFORE and AFTER any subcommand
        for argv in (
            ["--root", str(self.root), "--json", "stats"],
            ["stats", "--root", str(self.root), "--json"],
        ):
            res = subprocess.run(
                [sys.executable, str(REPO_ROOT / "ultron/core/core.py"), *argv],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, msg=res.stderr)
            parsed = json.loads(res.stdout)
            self.assertEqual(Path(parsed["repo_root"]).resolve(), self.root)

    def test_real_web_assets_serve_cleanly(self) -> None:
        from ultron.core.web import ALLOWED_ASSETS, WEB_ASSETS_DIR

        srv = create_server(self.core, host="127.0.0.1", port=0, quiet=True)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            self.assertTrue((WEB_ASSETS_DIR / "index.html").is_file())
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                conn.request("GET", "/")
                r = conn.getresponse()
                body = r.read().decode("utf-8")
                self.assertEqual(r.status, 200)
                self.assertIn("ULTRON Mission Control", body)
                for asset in sorted(ALLOWED_ASSETS):
                    conn.request("GET", f"/assets/{asset}")
                    ra = conn.getresponse()
                    ba = ra.read()
                    self.assertEqual(ra.status, 200, msg=f"Failed serving {asset}")
                    self.assertGreater(len(ba), 50)
                    self.assertNotIn(b"innerHTML", ba)
            finally:
                conn.close()
        finally:
            srv.shutdown()
            srv.server_close()
            t.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
