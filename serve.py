"""Local dashboard server with a refresh endpoint.

    .venv\\Scripts\\python serve.py        ->  http://127.0.0.1:8765

GET  /               dashboard
POST /api/refresh    start the data pipeline in the background (one run at a time)
GET  /api/status     {"running", "last_exit", "last_finished", "log_tail"}
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard"

_state = {"running": False, "last_exit": None, "last_finished": None, "log_tail": ""}
_lock = threading.Lock()


def _run_build() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "pipeline.build"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    log = (proc.stdout + proc.stderr).strip().splitlines()
    with _lock:
        _state.update(
            running=False,
            last_exit=proc.returncode,
            last_finished=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            log_tail="\n".join(log[-25:]),
        )


class Handler(SimpleHTTPRequestHandler):
    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self) -> None:
        if self.path.startswith("/data/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path == "/api/status":
            with _lock:
                return self._json(200, dict(_state))
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/refresh":
            return self._json(404, {"error": "not found"})
        with _lock:
            if _state["running"]:
                return self._json(202, {"started": False, "running": True})
            _state["running"] = True
        threading.Thread(target=_run_build, daemon=True).start()
        return self._json(202, {"started": True, "running": True})

    def log_message(self, fmt, *args):
        if "/api/status" not in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))["server"]
    server = ThreadingHTTPServer((cfg["host"], cfg["port"]), partial(Handler, directory=str(DASHBOARD)))
    print(f"Dashboard: http://{cfg['host']}:{cfg['port']}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
