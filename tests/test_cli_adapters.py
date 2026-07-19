from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
import yaml

from conftest import MODEL_DIGEST, NOW, RUNTIME_DIGEST, deterministic_signer, make_plan
from locusmesh import cli
from locusmesh.adapters.fixture import FixtureTopologyProvider
from locusmesh.adapters.local_signer import LocalEd25519Signer
from locusmesh.attestation import build_attestation
from locusmesh.models import EvidenceLevel, ExecutionIntent, PeerManifest, RoutePlan, TopologyEdge
from locusmesh.policy import AdmissionPolicy

FIXTURES = Path(__file__).parent / "fixtures"


def _json_stdout(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    output = capsys.readouterr().out
    return cast(dict[str, object], json.loads(output))


def test_fixture_provider_and_cli_probe(capsys: pytest.CaptureFixture[str]) -> None:
    topology = FixtureTopologyProvider(FIXTURES / "topology.json").snapshot()
    assert topology.local_peer_id == "device-local"

    exit_code = cli.main(["--json", "probe", "--topology", str(FIXTURES / "topology.json")])
    result = _json_stdout(capsys)
    assert exit_code == 0
    assert result["ok"] is True
    assert result["data"]["peer_count"] == 2  # type: ignore[index]


def test_probed_topology_cannot_expand_selected_policy_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    policy: AdmissionPolicy,
) -> None:
    observed_signer = deterministic_signer("cli-observed-only-peer")
    observed_peer = PeerManifest(
        peer_id="observed-only",
        execution_scope=ExecutionIntent.PRIVATE_MESH,
        model_digest=MODEL_DIGEST,
        runtime_digest=RUNTIME_DIGEST,
        evidence_level=EvidenceLevel.PEER_ASSERTED,
        key_id=observed_signer.key_id,
        public_key=observed_signer.public_key,
        valid_from=NOW.replace(hour=10),
        expires_at=NOW.replace(hour=14),
    )
    observed_topology = policy.topology.model_copy(
        update={
            "snapshot_id": "untrusted-observed-topology",
            "peers": (*policy.topology.peers, observed_peer),
            "edges": (
                *policy.topology.edges,
                TopologyEdge(
                    source_peer_id="device-local",
                    target_peer_id="observed-only",
                ),
            ),
        }
    )
    plan = make_plan(
        intent=ExecutionIntent.PRIVATE_MESH,
        hops=("device-local", "observed-only"),
        request_id="observed-topology-request",
        nonce="observed-topology-0001",
    )
    topology_path = tmp_path / "observed-topology.json"
    policy_path = tmp_path / "selected-policy.yaml"
    plan_path = tmp_path / "observed-route-plan.json"
    topology_path.write_text(observed_topology.model_dump_json(indent=2), encoding="utf-8")
    policy_path.write_text(
        yaml.safe_dump(policy.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(cli, "_now", lambda: NOW)

    assert cli.main(["--json", "probe", "--topology", str(topology_path)]) == 0
    probe = _json_stdout(capsys)
    assert probe["data"]["peer_count"] == len(policy.topology.peers) + 1  # type: ignore[index]

    assert (
        cli.main(
            [
                "--json",
                "admit",
                "--policy",
                str(policy_path),
                "--plan",
                str(plan_path),
            ]
        )
        == 3
    )
    decision = _json_stdout(capsys)
    assert decision["ok"] is False
    assert "PEER_UNKNOWN:observed-only" in decision["data"]["reason_codes"]  # type: ignore[index]
    assert (
        "EDGE_NOT_ALLOWED:device-local->observed-only" in decision["data"]["reason_codes"]  # type: ignore[index]
    )


def test_cli_doctor_demo_admit_and_schema_export(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--json", "doctor"]) == 0
    assert _json_stdout(capsys)["ok"] is True
    assert cli.main(["--json", "demo"]) == 0
    demo = _json_stdout(capsys)
    scenarios = demo["data"]["scenarios"]  # type: ignore[index]
    assert scenarios["device-local"]["admitted"] is True
    assert scenarios["loopback-escape"]["admitted"] is False
    assert scenarios["replay"]["second"]["reason_codes"] == ["REPLAY_DETECTED"]

    assert (
        cli.main(
            [
                "--json",
                "admit",
                "--policy",
                str(FIXTURES / "policy.yaml"),
                "--plan",
                str(FIXTURES / "plan.json"),
            ]
        )
        == 0
    )
    assert _json_stdout(capsys)["data"]["admitted"] is True  # type: ignore[index]

    output_dir = tmp_path / "schemas"
    assert cli.main(["--json", "schema", "export", "--out", str(output_dir)]) == 0
    exported = _json_stdout(capsys)
    assert len(exported["data"]["files"]) == 12  # type: ignore[index]
    assert (output_dir / "fabric-observation.schema.json").exists()
    assert (output_dir / "route-attestation.schema.json").exists()


def test_cli_verify_and_replay_exit_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    policy: AdmissionPolicy,
    device_plan: RoutePlan,
    signers: dict[str, LocalEd25519Signer],
) -> None:
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    attestation = build_attestation(device_plan, policy, signers, observed_at=NOW)
    policy_path = tmp_path / "policy.yaml"
    attestation_path = tmp_path / "attestation.json"
    store_path = tmp_path / "nonce.sqlite3"
    policy_path.write_text(
        yaml.safe_dump(policy.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    attestation_path.write_text(attestation.model_dump_json(indent=2), encoding="utf-8")
    argv = [
        "--json",
        "verify",
        "--policy",
        str(policy_path),
        "--attestation",
        str(attestation_path),
        "--nonce-store",
        str(store_path),
    ]

    assert cli.main(argv) == 0
    assert _json_stdout(capsys)["ok"] is True
    assert cli.main(argv) == 4
    replay = _json_stdout(capsys)
    assert replay["data"]["reason_codes"] == ["REPLAY_DETECTED"]  # type: ignore[index]


def test_cli_fails_closed_when_replay_state_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    policy: AdmissionPolicy,
    device_plan: RoutePlan,
    signers: dict[str, LocalEd25519Signer],
) -> None:
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    attestation = build_attestation(device_plan, policy, signers, observed_at=NOW)
    policy_path = tmp_path / "policy.yaml"
    attestation_path = tmp_path / "attestation.json"
    unavailable_store = tmp_path / "state-directory"
    unavailable_store.mkdir()
    policy_path.write_text(
        yaml.safe_dump(policy.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    attestation_path.write_text(attestation.model_dump_json(indent=2), encoding="utf-8")

    exit_code = cli.main(
        [
            "--json",
            "verify",
            "--policy",
            str(policy_path),
            "--attestation",
            str(attestation_path),
            "--nonce-store",
            str(unavailable_store),
        ]
    )
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert exit_code == 2
    assert result["ok"] is False
    assert result["error"] == {
        "code": "STATE_UNAVAILABLE",
        "message": "configured state store is unavailable",
    }
    assert str(unavailable_store) not in captured.out
    assert str(unavailable_store) not in captured.err


def test_strict_duplicate_and_invalid_input_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":"x","schema_version":"y"}', encoding="utf-8")

    assert cli.main(["--json", "probe", "--topology", str(duplicate)]) == 2
    result = _json_stdout(capsys)
    assert result["error"]["code"] == "INPUT_INVALID"  # type: ignore[index]

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * 1_048_577)
    assert cli.main(["--json", "probe", "--topology", str(oversized)]) == 2
    _json_stdout(capsys)


def test_validation_errors_do_not_echo_rejected_secret_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "do-not-print-this-private-value"
    policy_path = tmp_path / "bad-policy.yaml"
    policy_path.write_text(f"private_key: {secret}\n", encoding="utf-8")

    exit_code = cli.main(
        [
            "--json",
            "admit",
            "--policy",
            str(policy_path),
            "--plan",
            str(FIXTURES / "plan.json"),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert secret not in captured.out
    assert secret not in captured.err


def test_unexpected_internal_errors_are_redacted_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "sensitive-internal-detail"

    def fail(_args: object) -> object:
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "_run", fail)

    exit_code = cli.main(["--json", "doctor"])
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert exit_code == 1
    assert result == {
        "schema_version": "locusmesh.cli-output.v1",
        "command": "doctor",
        "ok": False,
        "data": None,
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "unexpected internal failure; no admission granted",
        },
    }
    assert secret not in captured.out
    assert secret not in captured.err
