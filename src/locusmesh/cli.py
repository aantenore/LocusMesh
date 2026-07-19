"""Installable offline command-line interface for LocusMesh."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from yaml import YAMLError

from locusmesh import __version__
from locusmesh.adapters.fixture import FixtureTopologyProvider
from locusmesh.attestation import verify_attestation
from locusmesh.demo import run_demo
from locusmesh.io import load_json_model, load_yaml_model
from locusmesh.models import RouteAttestation, RoutePlan
from locusmesh.policy import AdmissionPolicy, admit_plan, topology_digest
from locusmesh.replay import SQLiteReplayStore
from locusmesh.schema_export import export_schemas


@dataclass(frozen=True)
class _Result:
    ok: bool
    data: Any
    exit_code: int = 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="locusmesh",
        description="Offline admission and signed route-evidence verification.",
    )
    parser.add_argument("--json", action="store_true", help="emit stable JSON on stdout")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor", help="report offline runtime readiness")

    probe = commands.add_parser("probe", help="inspect a fixture topology JSON file")
    probe.add_argument("--topology", type=Path, required=True)

    admit = commands.add_parser("admit", help="evaluate a route plan against YAML policy")
    admit.add_argument("--policy", type=Path, required=True)
    admit.add_argument("--plan", type=Path, required=True)

    verify = commands.add_parser("verify", help="verify a signed route attestation")
    verify.add_argument("--policy", type=Path, required=True)
    verify.add_argument("--attestation", type=Path, required=True)
    verify.add_argument("--nonce-store", type=Path)

    commands.add_parser("demo", help="run deterministic positive and negative scenarios")

    schema = commands.add_parser("schema", help="work with public contract schemas")
    schema_commands = schema.add_subparsers(dest="schema_command", required=True)
    schema_export = schema_commands.add_parser("export", help="export JSON Schemas")
    schema_export.add_argument("--out", type=Path, required=True)
    return parser


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _command_name(args: argparse.Namespace) -> str:
    if args.command == "schema":
        return f"schema {args.schema_command}"
    return str(args.command)


def _run(args: argparse.Namespace) -> _Result:
    if args.command == "doctor":
        packages = {
            name: importlib.metadata.version(name)
            for name in ("cryptography", "pydantic", "PyYAML")
        }
        return _Result(
            True,
            {
                "version": __version__,
                "python": ".".join(str(value) for value in sys.version_info[:3]),
                "offline": True,
                "network_required": False,
                "secret_required": False,
                "dependencies": packages,
            },
        )
    if args.command == "probe":
        topology = FixtureTopologyProvider(args.topology).snapshot()
        valid_at = _now()
        return _Result(
            True,
            {
                "snapshot_id": topology.snapshot_id,
                "local_peer_id": topology.local_peer_id,
                "peer_count": len(topology.peers),
                "edge_count": len(topology.edges),
                "valid_now": topology.captured_at <= valid_at < topology.expires_at,
                "topology_digest": topology_digest(topology),
                "peers": [
                    {
                        "peer_id": peer.peer_id,
                        "execution_scope": peer.execution_scope.value,
                        "evidence_level": peer.evidence_level.value,
                        "key_id": peer.key_id,
                    }
                    for peer in topology.peers
                ],
            },
        )
    if args.command == "admit":
        policy = load_yaml_model(args.policy, AdmissionPolicy)
        plan = load_json_model(args.plan, RoutePlan)
        assert isinstance(policy, AdmissionPolicy)
        assert isinstance(plan, RoutePlan)
        decision = admit_plan(plan, policy, now=_now())
        return _Result(
            decision.admitted, decision.model_dump(mode="json"), 0 if decision.admitted else 3
        )
    if args.command == "verify":
        policy = load_yaml_model(args.policy, AdmissionPolicy)
        attestation = load_json_model(args.attestation, RouteAttestation)
        assert isinstance(policy, AdmissionPolicy)
        assert isinstance(attestation, RouteAttestation)
        if args.nonce_store is None:
            decision = verify_attestation(attestation, policy, now=_now())
        else:
            with SQLiteReplayStore(args.nonce_store) as replay_store:
                decision = verify_attestation(
                    attestation,
                    policy,
                    now=_now(),
                    replay_store=replay_store,
                )
        return _Result(
            decision.admitted, decision.model_dump(mode="json"), 0 if decision.admitted else 4
        )
    if args.command == "demo":
        return _Result(True, {"scenarios": run_demo()})
    if args.command == "schema" and args.schema_command == "export":
        paths = export_schemas(args.out)
        return _Result(
            True,
            {"output_dir": str(args.out.resolve()), "files": [path.name for path in paths]},
        )
    raise AssertionError("unreachable command")


def _envelope(command: str, result: _Result) -> dict[str, Any]:
    return {
        "schema_version": "locusmesh.cli-output.v1",
        "command": command,
        "ok": result.ok,
        "data": result.data,
        "error": None,
    }


def _error_envelope(command: str, code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": "locusmesh.cli-output.v1",
        "command": command,
        "ok": False,
        "data": None,
        "error": {"code": code, "message": message},
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = _parser()
    args = parser.parse_args(argv)
    command = _command_name(args)
    try:
        result = _run(args)
    except ValidationError as exc:
        details = [
            {
                "location": [str(part) for part in error["loc"]],
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors(include_input=False, include_url=False)
        ]
        message = json.dumps(details, sort_keys=True)
        print(f"locusmesh: INPUT_INVALID: {message}", file=sys.stderr)
        if args.json:
            print(json.dumps(_error_envelope(command, "INPUT_INVALID", message), sort_keys=True))
        return 2
    except YAMLError:
        message = "invalid YAML input"
        print(f"locusmesh: INPUT_INVALID: {message}", file=sys.stderr)
        if args.json:
            print(json.dumps(_error_envelope(command, "INPUT_INVALID", message), sort_keys=True))
        return 2
    except sqlite3.Error:
        message = "configured state store is unavailable"
        print(f"locusmesh: STATE_UNAVAILABLE: {message}", file=sys.stderr)
        if args.json:
            print(
                json.dumps(_error_envelope(command, "STATE_UNAVAILABLE", message), sort_keys=True)
            )
        return 2
    except (OSError, ValueError) as exc:
        message = str(exc)
        print(f"locusmesh: INPUT_INVALID: {message}", file=sys.stderr)
        if args.json:
            print(json.dumps(_error_envelope(command, "INPUT_INVALID", message), sort_keys=True))
        return 2

    if args.json:
        print(json.dumps(_envelope(command, result), sort_keys=True))
    else:
        if result.ok:
            print(json.dumps(result.data, indent=2, sort_keys=True))
        else:
            print("locusmesh: decision denied", file=sys.stderr)
            print(json.dumps(result.data, indent=2, sort_keys=True))
    return result.exit_code
