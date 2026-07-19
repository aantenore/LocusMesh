from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from typing import Any, cast
from urllib import error

import pytest
from pydantic import ValidationError

from locusmesh import cli
from locusmesh.adapters.mesh_llm import FabricObservationError, MeshLlmStatusObserver
from locusmesh.models import (
    ExecutionIntent,
    FabricCandidateObservation,
    FabricObservation,
    TopologySnapshot,
)
from locusmesh.ports import FabricObserver

NOW = datetime(2030, 4, 5, 12, 0, tzinfo=UTC)


class _Response(BytesIO):
    status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _status(*, public: bool = False, token: str = "sensitive-invite-token") -> dict[str, Any]:
    return {
        "version": "0.73.1",
        "node_id": "node-local",
        "node_state": "serving",
        "serving_models": ["Qwen3-8B-Q4_K_M"],
        "owner": {"verified": True},
        "mesh_discovery_mode": "nostr" if public else "mdns",
        "discovery_scope": "public" if public else "lan",
        "discovery_source": "nostr-relay" if public else "mdns",
        "nostr_discovery": public,
        "publication_state": "public" if public else "private",
        "token": token,
        "peers": [
            {
                "id": "peer-a",
                "state": "standby",
                "serving_models": [],
                "owner": {"verified": False},
                "hostname": "must-not-be-projected.local",
            }
        ],
    }


def _opener(payload: dict[str, Any]) -> Any:
    raw = json.dumps(payload).encode()

    def open_status(request: Any, *, timeout: float) -> _Response:
        assert request.full_url == "http://127.0.0.1:3131/api/status"
        assert timeout == 2.0
        return _Response(raw)

    return open_status


def _observe(
    payload: dict[str, Any],
    *,
    requested_scope: ExecutionIntent = ExecutionIntent.PRIVATE_MESH,
) -> Any:
    return MeshLlmStatusObserver(
        "http://127.0.0.1:3131",
        requested_max_scope=requested_scope,
        opener=_opener(payload),
    ).observe(now=NOW)


def test_private_status_becomes_bounded_observation_not_authority() -> None:
    observation = _observe(_status())

    assert observation.observed_scope is ExecutionIntent.PRIVATE_MESH
    assert observation.within_requested_scope
    assert observation.admission_authority is False
    assert observation.expires_at == NOW + timedelta(seconds=5)
    assert observation.reason_codes == (
        "OBSERVATION_ONLY",
        "UNVERSIONED_PROVIDER_SCHEMA",
        "PRIVATE_LAN_STATUS_SIGNAL",
        "SCOPE_SIGNAL_WITHIN_MAXIMUM",
    )
    assert [candidate.candidate_id for candidate in observation.candidates] == [
        "node-local",
        "peer-a",
    ]
    assert all(candidate.admission_authority is False for candidate in observation.candidates)
    assert all(
        candidate.observed_scope is ExecutionIntent.PRIVATE_MESH
        for candidate in observation.candidates
    )
    rendered = observation.model_dump_json()
    assert "sensitive-invite-token" not in rendered
    assert "must-not-be-projected" not in rendered

    with pytest.raises(ValidationError):
        TopologySnapshot.model_validate(observation.model_dump(mode="json"))


def test_public_signal_exceeds_private_scope_and_mesh_is_never_device_only() -> None:
    public = _observe(_status(public=True))
    private_under_device_policy = _observe(
        _status(),
        requested_scope=ExecutionIntent.DEVICE_ONLY,
    )

    assert public.observed_scope is ExecutionIntent.PUBLIC_MESH
    assert public.within_requested_scope is False
    assert "PUBLIC_OR_AMBIGUOUS_STATUS_SIGNAL" in public.reason_codes
    assert "SCOPE_SIGNAL_EXCEEDS_MAXIMUM" in public.reason_codes
    assert private_under_device_policy.observed_scope is ExecutionIntent.PRIVATE_MESH
    assert private_under_device_policy.within_requested_scope is False


def test_projection_digest_excludes_provider_secret_and_rejects_bad_boundaries() -> None:
    first = _observe(_status(token="first-secret"))
    second = _observe(_status(token="second-secret"))
    assert first.projection_digest == second.projection_digest

    with pytest.raises(ValueError, match="loopback"):
        MeshLlmStatusObserver(
            "https://mesh.example.com",
            requested_max_scope=ExecutionIntent.PUBLIC_MESH,
        )
    with pytest.raises(ValueError, match="without a path"):
        MeshLlmStatusObserver(
            "http://127.0.0.1:3131/api/status",
            requested_max_scope=ExecutionIntent.PUBLIC_MESH,
        )
    for endpoint in (
        "http://user:secret@127.0.0.1:3131",
        "http://127.0.0.1:3131?target=elsewhere",
        "http://127.0.0.1:3131#fragment",
    ):
        with pytest.raises(ValueError, match="must not contain"):
            MeshLlmStatusObserver(
                endpoint,
                requested_max_scope=ExecutionIntent.PUBLIC_MESH,
            )
    with pytest.raises(ValueError, match="invalid port"):
        MeshLlmStatusObserver(
            "http://127.0.0.1:not-a-port",
            requested_max_scope=ExecutionIntent.PUBLIC_MESH,
        )

    for ttl in (0, 61):
        with pytest.raises(ValueError, match="ttl_seconds"):
            MeshLlmStatusObserver(
                "http://127.0.0.1:3131",
                requested_max_scope=ExecutionIntent.PRIVATE_MESH,
                ttl_seconds=ttl,
            )
    with pytest.raises(ValueError, match="timezone-aware"):
        MeshLlmStatusObserver(
            "http://127.0.0.1:3131",
            requested_max_scope=ExecutionIntent.PRIVATE_MESH,
            opener=_opener(_status()),
        ).observe(now=datetime(2030, 4, 5, 12, 0))


def test_observation_contract_recomputes_boundary_invariants() -> None:
    observation = _observe(_status())
    wrong_scope_result = observation.model_dump(mode="json")
    wrong_scope_result["within_requested_scope"] = False
    wrong_scope_result["reason_codes"] = [
        "OBSERVATION_ONLY",
        "UNVERSIONED_PROVIDER_SCHEMA",
        "PRIVATE_LAN_STATUS_SIGNAL",
        "SCOPE_SIGNAL_EXCEEDS_MAXIMUM",
    ]
    with pytest.raises(ValidationError, match="scope lattice"):
        FabricObservation.model_validate(wrong_scope_result)

    excessive_lifetime = observation.model_dump(mode="json")
    excessive_lifetime["expires_at"] = (NOW + timedelta(seconds=61)).isoformat()
    with pytest.raises(ValidationError, match="cannot exceed"):
        FabricObservation.model_validate(excessive_lifetime)

    impossible_device_scope = observation.model_dump(mode="json")
    impossible_device_scope["observed_scope"] = "device_only"
    with pytest.raises(ValidationError):
        FabricObservation.model_validate(impossible_device_scope)

    candidate = observation.candidates[0].model_dump(mode="json")
    candidate["reason_codes"] = ["PROVIDER_STATUS_ONLY"]
    with pytest.raises(ValidationError, match="boundary reason"):
        FabricCandidateObservation.model_validate(candidate)


def test_strict_payload_and_candidate_bounds_fail_without_observation() -> None:
    duplicate_peer = _status()
    duplicate_peer["peers"].append(duplicate_peer["peers"][0])
    with pytest.raises(FabricObservationError):
        _observe(duplicate_peer)

    duplicate_model = _status()
    duplicate_model["serving_models"] = ["same-model", "same-model"]
    with pytest.raises(FabricObservationError):
        _observe(duplicate_model)

    unknown_state = _status()
    unknown_state["node_state"] = "future-state"
    with pytest.raises(FabricObservationError):
        _observe(unknown_state)

    def invalid_json(_request: object, *, timeout: float) -> _Response:
        assert timeout == 2.0
        return _Response(b'{"version":"secret", "version":"duplicate"}')

    with pytest.raises(FabricObservationError, match="strict JSON"):
        MeshLlmStatusObserver(
            "http://127.0.0.1:3131",
            requested_max_scope=ExecutionIntent.PRIVATE_MESH,
            opener=invalid_json,
        ).observe(now=NOW)

    def unavailable(_request: object, *, timeout: float) -> _Response:
        assert timeout == 2.0
        raise error.URLError("sensitive network detail")

    with pytest.raises(FabricObservationError, match="unavailable") as failure:
        MeshLlmStatusObserver(
            "http://127.0.0.1:3131",
            requested_max_scope=ExecutionIntent.PRIVATE_MESH,
            opener=unavailable,
        ).observe(now=NOW)
    assert "sensitive network detail" not in str(failure.value)

    def oversized(_request: object, *, timeout: float) -> _Response:
        assert timeout == 2.0
        return _Response(b" " * 1_048_577)

    observer = MeshLlmStatusObserver(
        "http://127.0.0.1:3131",
        requested_max_scope=ExecutionIntent.PRIVATE_MESH,
        opener=oversized,
    )
    with pytest.raises(FabricObservationError, match="exceeded"):
        observer.observe(now=NOW)


def test_observer_implements_provider_neutral_port() -> None:
    observer = MeshLlmStatusObserver(
        "http://127.0.0.1:3131",
        requested_max_scope=ExecutionIntent.PRIVATE_MESH,
        opener=_opener(_status()),
    )
    assert isinstance(observer, FabricObserver)


def test_cli_observes_real_loopback_http_and_uses_scope_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps(_status()).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/api/status":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    try:
        assert (
            cli.main(
                [
                    "--json",
                    "observe",
                    "mesh-llm",
                    "--management-url",
                    endpoint,
                    "--max-scope",
                    "private_mesh",
                ]
            )
            == 0
        )
        accepted = json.loads(capsys.readouterr().out)
        assert accepted["ok"] is True
        assert accepted["data"]["admission_authority"] is False

        assert (
            cli.main(
                [
                    "--json",
                    "observe",
                    "mesh-llm",
                    "--management-url",
                    endpoint,
                    "--max-scope",
                    "device_only",
                ]
            )
            == 5
        )
        rejected = json.loads(capsys.readouterr().out)
        assert rejected["ok"] is False
        assert rejected["error"] is None
        assert rejected["data"]["within_requested_scope"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_default_http_client_denies_redirects() -> None:
    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            port = cast(tuple[str, int], self.server.server_address)[1]
            self.send_header("Location", f"http://127.0.0.1:{port}/target")
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(FabricObservationError, match="unavailable"):
            MeshLlmStatusObserver(
                f"http://127.0.0.1:{server.server_port}",
                requested_max_scope=ExecutionIntent.PRIVATE_MESH,
            ).observe(now=NOW)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
