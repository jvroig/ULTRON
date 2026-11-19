#!/usr/bin/env python3
"""ULTRON Mission Control: strictly read-only stdlib HTTP server & JSON API."""

from __future__ import annotations

import argparse
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse
import webbrowser

try:
    from ultron.core.core import PRIME_ID, UltronCore, now_iso
except ImportError:  # pragma: no cover - script-relative execution from ultron/core/
    from core import PRIME_ID, UltronCore, now_iso  # type: ignore[no-redef]

WEB_ASSETS_DIR = Path(__file__).resolve().parent / "web"
ALLOWED_ASSETS = frozenset({"tokens.css", "styles.css", "sprites.js", "app.js"})
ASSET_MIME_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8420
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})

WATCHED_FILENAMES = frozenset({"AGENTS.md", ".gitattributes"})
WATCHED_SUFFIXES = (".json", ".jsonl")

CSP_HEADER = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)


def compute_state_etag(core: Any) -> str:
    """Compute a fast quoted ETag from stat metadata without creating lazy dirs."""
    entries: List[str] = []
    if core.sessions_file.is_file():
        try:
            st = core.sessions_file.stat()
            entries.append(
                f".runtime/sessions.json:{st.st_ino}:{st.st_mtime_ns}:{st.st_size}"
            )
        except OSError:
            pass

    seen_dirs: set[Path] = set()
    watch_dirs: List[Path] = [
        core.hive_dir,
        core.projects_dir,
        core.decisions_dir,
        core.threads_dir,
        getattr(core, "blueprints_dir", Path("")),
        getattr(core, "_builtin_blueprints_dir", Path("")),
    ]
    for root_dir in watch_dirs:
        if not root_dir or not str(root_dir) or not root_dir.is_dir():
            continue
        resolved_dir = root_dir.resolve()
        if resolved_dir in seen_dirs:
            continue
        seen_dirs.add(resolved_dir)
        for dirpath, dirnames, filenames in os.walk(root_dir, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for fname in sorted(filenames):
                if fname.startswith(".") and fname not in WATCHED_FILENAMES:
                    continue
                if fname not in WATCHED_FILENAMES and not fname.endswith(WATCHED_SUFFIXES):
                    continue
                fpath = Path(dirpath) / fname
                try:
                    st = fpath.stat()
                except OSError:
                    continue
                try:
                    rel = fpath.relative_to(core.repo_root).as_posix()
                except ValueError:
                    rel = fpath.as_posix()
                entries.append(f"{rel}:{st.st_ino}:{st.st_mtime_ns}:{st.st_size}")

    entries.sort()
    digest = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()[:24]
    return f'"{digest}"'


def _etag_matches(header_value: Optional[str], current_etag: str) -> bool:
    if not header_value:
        return False
    for raw_part in header_value.split(","):
        token = raw_part.strip()
        if not token:
            continue
        if token == "*":
            return True
        if token.startswith(("W/", "w/")):
            token = token[2:].strip()
        if token == current_etag:
            return True
    return False


def build_snapshot(core: Any) -> Dict[str, Any]:
    """Assemble the complete read-only Mission Control snapshot from UltronCore."""
    prime = core.get_agent(PRIME_ID)
    if prime is None:
        prime = {
            "agent_id": PRIME_ID,
            "conversation_id": "",
            "harness": "",
            "last_seen": "",
            "registered_at": "",
            "responsibilities": "Ultimate Leader of Teams, Roles, and Operational Nodes",
            "role": "prime",
            "role_path": "ultron/core",
            "status": "unregistered",
            "title": "ULTRON PRIME",
        }

    return {
        "blueprints": core.list_blueprints(),
        "decisions": core.list_decisions(limit=500),
        "generated_at": now_iso(),
        "prime": prime,
        "projects": core.list_projects(include_archived=True),
        "repo_name": core.repo_root.name or str(core.repo_root),
        "repo_root": str(core.repo_root),
        "stats": core.get_stats(),
        "teams": core.list_teams(include_archived=True),
        "threads": core.list_threads(show_all=True, limit=500),
    }


class UltronWebServer(ThreadingHTTPServer):
    """Thread-safe HTTP server holding UltronCore and an ETag-keyed snapshot cache."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: Tuple[str, int],
        core: Any,
        assets_dir: Optional[Path] = None,
        quiet: bool = False,
    ) -> None:
        self.core = core
        self.assets_dir = (assets_dir or WEB_ASSETS_DIR).resolve()
        self.quiet = quiet
        self._cache_lock = threading.Lock()
        self._cached_etag: Optional[str] = None
        self._cached_snapshot: Optional[bytes] = None
        super().__init__(server_address, UltronWebHandler)

    def get_snapshot_payload(self, if_none_match: Optional[str]) -> Tuple[int, str, Optional[bytes]]:
        with self._cache_lock:
            for _ in range(2):
                etag = compute_state_etag(self.core)
                if _etag_matches(if_none_match, etag):
                    return HTTPStatus.NOT_MODIFIED, etag, None
                if self._cached_etag == etag and self._cached_snapshot is not None:
                    return HTTPStatus.OK, etag, self._cached_snapshot
                snapshot = build_snapshot(self.core)
                payload = json.dumps(
                    snapshot, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                etag_after = compute_state_etag(self.core)
                if etag_after == etag:
                    self._cached_etag = etag
                    self._cached_snapshot = payload
                    return HTTPStatus.OK, etag, payload
            # Concurrent external writes persisted across both attempts; return fresh response without caching mismatch
            return HTTPStatus.OK, etag_after, payload


class UltronWebHandler(BaseHTTPRequestHandler):
    """Strictly read-only request handler for ULTRON Mission Control."""

    server_version = "UltronMissionControl/1.0"
    protocol_version = "HTTP/1.1"
    server: UltronWebServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        if getattr(self.server, "quiet", False):
            return
        super().log_message(format, *args)

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        head_only: bool = False,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            if not head_only and body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_empty(
        self, status: int, extra_headers: Optional[Dict[str, str]] = None
    ) -> None:
        try:
            self.send_response(status)
            self.send_header("X-Content-Type-Options", "nosniff")
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(
        self,
        status: int,
        data: Any,
        head_only: bool = False,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Cache-Control": "no-cache"}
        if extra_headers:
            headers.update(extra_headers)
        self._send_bytes(
            status,
            body,
            "application/json; charset=utf-8",
            head_only=head_only,
            extra_headers=headers,
        )

    def _reject_mutation(self) -> None:
        self.close_connection = True
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"ok": False, "error": "ULTRON Web UI is strictly read-only."},
            extra_headers={"Allow": "GET, HEAD", "Connection": "close"},
        )

    def do_POST(self) -> None:
        self._reject_mutation()

    def do_PUT(self) -> None:
        self._reject_mutation()

    def do_PATCH(self) -> None:
        self._reject_mutation()

    def do_DELETE(self) -> None:
        self._reject_mutation()

    def do_OPTIONS(self) -> None:
        self._reject_mutation()

    def do_HEAD(self) -> None:
        self._dispatch(head_only=True)

    def do_GET(self) -> None:
        self._dispatch(head_only=False)

    def _serve_index(self, head_only: bool) -> None:
        index_path = self.server.assets_dir / "index.html"
        if not index_path.is_file():
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": f"Web asset missing: {index_path.name}"},
                head_only=head_only,
            )
            return
        body = index_path.read_bytes()
        self._send_bytes(
            HTTPStatus.OK,
            body,
            "text/html; charset=utf-8",
            head_only=head_only,
            extra_headers={
                "Cache-Control": "no-cache",
                "Content-Security-Policy": CSP_HEADER,
            },
        )

    def _serve_asset(self, raw_name: str, head_only: bool) -> None:
        name = unquote(raw_name)
        if (
            not name
            or "/" in name
            or "\\" in name
            or "\x00" in name
            or name in {".", ".."}
            or name not in ALLOWED_ASSETS
        ):
            self._send_json(
                HTTPStatus.NOT_FOUND, {"ok": False, "error": "Asset not found."}, head_only=head_only
            )
            return
        assets_root = self.server.assets_dir
        target = (assets_root / name).resolve()
        if target.parent != assets_root or not target.is_file():
            self._send_json(
                HTTPStatus.NOT_FOUND, {"ok": False, "error": "Asset not found."}, head_only=head_only
            )
            return
        mime = ASSET_MIME_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._send_bytes(
            HTTPStatus.OK,
            target.read_bytes(),
            mime,
            head_only=head_only,
            extra_headers={"Cache-Control": "no-cache"},
        )

    def _dispatch(self, head_only: bool) -> None:
        try:
            self._dispatch_inner(head_only=head_only)
        except Exception as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": str(exc)},
                head_only=head_only,
            )

    def _dispatch_inner(self, head_only: bool) -> None:
        parsed = urlparse(self.path)
        raw_path = parsed.path or "/"

        if raw_path in {"/", "/index.html"}:
            self._serve_index(head_only=head_only)
            return

        if raw_path.startswith("/assets/"):
            self._serve_asset(raw_path[len("/assets/") :], head_only=head_only)
            return

        if raw_path == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "read_only": True,
                    "repo_name": self.server.core.repo_root.name or str(self.server.core.repo_root),
                },
                head_only=head_only,
            )
            return

        if raw_path == "/api/snapshot":
            status, etag, payload = self.server.get_snapshot_payload(
                self.headers.get("If-None-Match")
            )
            if status == HTTPStatus.NOT_MODIFIED:
                self._send_empty(
                    HTTPStatus.NOT_MODIFIED,
                    extra_headers={"ETag": etag, "Cache-Control": "no-cache"},
                )
                return
            assert payload is not None
            self._send_bytes(
                HTTPStatus.OK,
                payload,
                "application/json; charset=utf-8",
                head_only=head_only,
                extra_headers={"ETag": etag, "Cache-Control": "no-cache"},
            )
            return

        if raw_path.startswith("/api/threads/"):
            ref = unquote(raw_path[len("/api/threads/") :])
            if not ref or "/" in ref or "\\" in ref or "\x00" in ref:
                self._send_json(
                    HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"}, head_only=head_only
                )
                return
            try:
                thread = self.server.core.get_thread(ref, show_all=True)
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)}, head_only=head_only
                )
                return
            if thread is None:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"ok": False, "error": f"Thread '{ref}' not found."},
                    head_only=head_only,
                )
                return
            self._send_json(HTTPStatus.OK, thread, head_only=head_only)
            return

        if raw_path.startswith("/api/decisions/"):
            ref = unquote(raw_path[len("/api/decisions/") :])
            if not ref or "/" in ref or "\\" in ref or "\x00" in ref:
                self._send_json(
                    HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"}, head_only=head_only
                )
                return
            try:
                decision = self.server.core.get_decision(ref)
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)}, head_only=head_only
                )
                return
            if decision is None:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"ok": False, "error": f"Decision '{ref}' not found."},
                    head_only=head_only,
                )
                return
            self._send_json(HTTPStatus.OK, decision, head_only=head_only)
            return

        if raw_path == "/api/verify":
            try:
                res = self.server.core.verify(prune_orphans=False)
                self._send_json(HTTPStatus.OK, {"ok": True, **res}, head_only=head_only)
            except (ValueError, FileNotFoundError, RuntimeError, OSError) as exc:
                self._send_json(
                    HTTPStatus.OK, {"ok": False, "error": str(exc)}, head_only=head_only
                )
            return

        if raw_path == "/api/liveness":
            qs = parse_qs(parsed.query)
            team = qs.get("team", [None])[0]
            try:
                res = self.server.core.probe_liveness(team_slug=team)
                self._send_json(HTTPStatus.OK, {"ok": True, **res}, head_only=head_only)
            except (ValueError, RuntimeError, FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
                self._send_json(
                    HTTPStatus.OK, {"ok": False, "error": str(exc)}, head_only=head_only
                )
            return

        self._send_json(
            HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"}, head_only=head_only
        )


def create_server(
    core: Any,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    assets_dir: Optional[Path] = None,
    quiet: bool = False,
) -> UltronWebServer:
    """Create a configured read-only UltronWebServer instance."""
    return UltronWebServer((host, port), core=core, assets_dir=assets_dir, quiet=quiet)


def serve(
    core: Any,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    assets_dir: Optional[Path] = None,
    quiet: bool = False,
) -> int:
    """Start ULTRON Mission Control server until interrupted."""
    clean_host = (host or DEFAULT_HOST).strip() or DEFAULT_HOST
    if clean_host.lower() not in LOOPBACK_HOSTS:
        print(
            f"[ULTRON Warning] Binding Mission Control to non-loopback host '{clean_host}' "
            f"exposes read-only Hive/board state on that network interface.",
            file=sys.stderr,
        )
    try:
        server = create_server(
            core, host=clean_host, port=port, assets_dir=assets_dir, quiet=quiet
        )
    except OSError as exc:
        raise RuntimeError(f"Failed to start Mission Control on {clean_host}:{port}: {exc}") from exc

    bound_host, bound_port = server.server_address[:2]
    url_host = "127.0.0.1" if bound_host == "0.0.0.0" else bound_host
    url = f"http://{url_host}:{bound_port}"
    print(
        f"[ULTRON] Mission Control (read-only) serving '{core.repo_root}' at {url} (Ctrl+C to stop)",
        flush=True,
    )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ULTRON Mission Control (Read-Only Web UI)")
    parser.add_argument("--root", default=None, help="Repository root containing ultron/")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bind address (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port (default: {DEFAULT_PORT})")
    parser.add_argument("--no-open", action="store_true", help="Do not launch default browser")
    args = parser.parse_args(argv)
    role_id = os.environ.get("ULTRON_AGENT_ID", "").strip()
    if role_id and role_id != PRIME_ID:
        print(
            f"[ULTRON Error] 'ui' is for {PRIME_ID} only; this shell belongs to role '{role_id}'.",
            file=sys.stderr,
        )
        return 1
    core = UltronCore(repo_root=args.root)
    return serve(core, host=args.host, port=args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    sys.exit(main())
