"""Smoke-test the installed CLI against a real loopback HTTP exchange."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_SECRET = "package-smoke-invite-token-must-not-leak"
_PAYLOAD = json.dumps(
    {
        "version": "0.73.1",
        "node_id": "package-smoke-node",
        "node_state": "serving",
        "serving_models": ["package-smoke-model"],
        "owner": {"verified": True},
        "mesh_discovery_mode": "mdns",
        "discovery_scope": "lan",
        "discovery_source": "mdns",
        "nostr_discovery": False,
        "publication_state": "private",
        "token": _SECRET,
        "peers": [],
    }
).encode()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/api/status":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(_PAYLOAD)))
        self.end_headers()
        self.wfile.write(_PAYLOAD)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def main(argv: list[str] | None = None) -> int:
    arguments = argv if argv is not None else sys.argv[1:]
    if len(arguments) != 1:
        raise SystemExit("usage: smoke_installed_observer.py LOCUSMESH_EXECUTABLE")
    executable = Path(arguments[0])
    if not executable.is_file():
        raise SystemExit("installed locusmesh executable was not found")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = subprocess.run(
            [
                str(executable),
                "--json",
                "observe",
                "mesh-llm",
                "--management-url",
                f"http://127.0.0.1:{server.server_port}",
                "--max-scope",
                "private_mesh",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if _SECRET in completed.stdout or _SECRET in completed.stderr:
            raise RuntimeError("provider token leaked from installed observer")
        result = json.loads(completed.stdout)
        observation = result["data"]
        if result["ok"] is not True:
            raise RuntimeError("installed observer did not succeed")
        if observation["admission_authority"] is not False:
            raise RuntimeError("installed observer granted authority")
        if observation["observed_scope"] != "private_mesh":
            raise RuntimeError("installed observer returned the wrong scope")
        if observation["provider_contract"] != "mesh-llm.api-status.unversioned":
            raise RuntimeError("installed observer returned the wrong provider contract")
        print(
            json.dumps(
                {
                    "candidate_count": len(observation["candidates"]),
                    "installed_observer_smoke": "passed",
                    "observed_scope": observation["observed_scope"],
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
