"""Read-only Mesh-LLM status observation without topology authority."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from ipaddress import ip_address
from typing import Any, Literal
from urllib import error, request
from urllib.parse import urlparse, urlunparse

from pydantic import ValidationError

from locusmesh.canonical import sha256_digest
from locusmesh.models import (
    ExecutionIntent,
    FabricCandidateObservation,
    FabricObservation,
)

_MAX_RESPONSE_BYTES = 1_048_576
_MAX_CANDIDATES = 256
_MAX_MODELS = 256
_NODE_STATES = frozenset({"client", "standby", "loading", "serving"})
_SCOPE_RANK = {
    ExecutionIntent.DEVICE_ONLY: 0,
    ExecutionIntent.PRIVATE_MESH: 1,
    ExecutionIntent.PUBLIC_MESH: 2,
}


class FabricObservationError(RuntimeError):
    """A redacted provider-observation failure that grants no authority."""


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class MeshLlmStatusObserver:
    """Project Mesh-LLM `/api/status` into non-authoritative candidates.

    The management URL is deliberately limited to loopback. This protects the
    observer from becoming a generic network probe; it does not establish that
    inference remains local because Mesh-LLM may route beyond the first hop.
    """

    provider = "mesh_llm"

    def __init__(
        self,
        management_url: str,
        *,
        requested_max_scope: ExecutionIntent,
        timeout_seconds: float = 2.0,
        ttl_seconds: int = 5,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        if not 0.1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 0.1 and 30")
        if not 1 <= ttl_seconds <= 60:
            raise ValueError("ttl_seconds must be between 1 and 60")
        self._source_endpoint, self._status_url = _status_url(management_url)
        self._requested_max_scope = requested_max_scope
        self._timeout_seconds = timeout_seconds
        self._ttl_seconds = ttl_seconds
        self._opener = opener or request.build_opener(_NoRedirect()).open

    def observe(self, *, now: datetime) -> FabricObservation:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("timezone-aware observation time required")
        payload = self._fetch()
        try:
            return self._project(payload, now=now)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise FabricObservationError(
                "Mesh-LLM status does not match the supported observation projection"
            ) from exc

    def _fetch(self) -> Mapping[str, Any]:
        http_request = request.Request(
            self._status_url,
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with self._opener(http_request, timeout=self._timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise FabricObservationError("Mesh-LLM status endpoint was unavailable")
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except (error.HTTPError, error.URLError, OSError, TimeoutError) as exc:
            raise FabricObservationError("Mesh-LLM status endpoint was unavailable") from exc
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise FabricObservationError("Mesh-LLM status response exceeded 1 MiB")
        try:
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise FabricObservationError("Mesh-LLM status response was not strict JSON") from exc
        if not isinstance(payload, Mapping):
            raise FabricObservationError("Mesh-LLM status response must be a JSON object")
        return payload

    def _project(self, payload: Mapping[str, Any], *, now: datetime) -> FabricObservation:
        version = _string(payload, "version", maximum=64)
        local_id = _string(payload, "node_id", maximum=128)
        local_state = _state(payload, "node_state")
        local_models = _models(payload, "serving_models")
        local_owner = _mapping(payload, "owner")
        local_owner_verified = _boolean(local_owner, "verified")
        discovery = {
            "mesh_discovery_mode": _string(payload, "mesh_discovery_mode", maximum=64),
            "discovery_scope": _string(payload, "discovery_scope", maximum=64),
            "discovery_source": _string(payload, "discovery_source", maximum=128),
            "nostr_discovery": _boolean(payload, "nostr_discovery"),
            "publication_state": _string(payload, "publication_state", maximum=64),
        }
        observed_scope = _observed_scope(discovery)

        projected_peers: list[dict[str, Any]] = []
        peers = payload.get("peers")
        if not isinstance(peers, list):
            raise TypeError("peers must be a list")
        if len(peers) >= _MAX_CANDIDATES:
            raise ValueError("peer count exceeds observation bound")
        for raw_peer in peers:
            if not isinstance(raw_peer, Mapping):
                raise TypeError("peer must be an object")
            peer_owner = _mapping(raw_peer, "owner")
            projected_peers.append(
                {
                    "candidate_id": _string(raw_peer, "id", maximum=128),
                    "state": _state(raw_peer, "state"),
                    "serving_models": _models(raw_peer, "serving_models"),
                    "provider_claimed_owner_verified": _boolean(peer_owner, "verified"),
                }
            )

        local_projected: dict[str, Any] = {
            "candidate_id": local_id,
            "state": local_state,
            "serving_models": local_models,
            "provider_claimed_owner_verified": local_owner_verified,
        }
        projection: dict[str, Any] = {
            "provider": self.provider,
            "provider_version": version,
            "local": local_projected,
            "peers": projected_peers,
            "discovery": discovery,
        }
        candidates = (
            _candidate(
                local_projected,
                local_node=True,
                observed_scope=observed_scope,
            ),
            *(
                _candidate(peer, local_node=False, observed_scope=observed_scope)
                for peer in projected_peers
            ),
        )
        within_scope = _SCOPE_RANK[observed_scope] <= _SCOPE_RANK[self._requested_max_scope]
        return FabricObservation(
            provider=self.provider,
            provider_version=version,
            provider_contract="mesh-llm.api-status.unversioned",
            source_endpoint=self._source_endpoint,
            projection_digest=sha256_digest(projection),
            observed_at=now,
            expires_at=now + timedelta(seconds=self._ttl_seconds),
            requested_max_scope=self._requested_max_scope,
            observed_scope=observed_scope,
            within_requested_scope=within_scope,
            candidates=candidates,
            reason_codes=(
                "OBSERVATION_ONLY",
                "UNVERSIONED_PROVIDER_SCHEMA",
                (
                    "PRIVATE_LAN_STATUS_SIGNAL"
                    if observed_scope is ExecutionIntent.PRIVATE_MESH
                    else "PUBLIC_OR_AMBIGUOUS_STATUS_SIGNAL"
                ),
                ("SCOPE_SIGNAL_WITHIN_MAXIMUM" if within_scope else "SCOPE_SIGNAL_EXCEEDS_MAXIMUM"),
            ),
        )


def _candidate(
    projected: Mapping[str, Any],
    *,
    local_node: bool,
    observed_scope: Literal[
        ExecutionIntent.PRIVATE_MESH,
        ExecutionIntent.PUBLIC_MESH,
    ],
) -> FabricCandidateObservation:
    return FabricCandidateObservation(
        provider=MeshLlmStatusObserver.provider,
        candidate_id=projected["candidate_id"],
        local_node=local_node,
        state=projected["state"],
        serving_models=tuple(projected["serving_models"]),
        provider_claimed_owner_verified=projected["provider_claimed_owner_verified"],
        observed_scope=observed_scope,
    )


def _observed_scope(
    discovery: Mapping[str, Any],
) -> Literal[ExecutionIntent.PRIVATE_MESH, ExecutionIntent.PUBLIC_MESH]:
    """Return the widest status signal; Mesh transport is never device-only."""

    explicitly_private = (
        discovery["publication_state"] == "private"
        and discovery["discovery_scope"] in {"private", "lan", "local"}
        and discovery["mesh_discovery_mode"] in {"mdns", "private", "local"}
        and not discovery["nostr_discovery"]
    )
    return ExecutionIntent.PRIVATE_MESH if explicitly_private else ExecutionIntent.PUBLIC_MESH


def _status_url(value: str) -> tuple[str, str]:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("management_url must be an HTTP(S) loopback origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("management_url must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("management_url must be an origin without a path")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("management_url contains an invalid port") from exc
    host = parsed.hostname.rstrip(".").lower()
    if host != "localhost":
        try:
            if not ip_address(host).is_loopback:
                raise ValueError("management_url must use a loopback host")
        except ValueError as exc:
            raise ValueError("management_url must use a loopback host") from exc
    origin = urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")
    return origin, f"{origin}/api/status"


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise TypeError(f"{key} must be an object")
    return item


def _string(value: Mapping[str, Any], key: str, *, maximum: int) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item or len(item) > maximum:
        raise TypeError(f"{key} must be a bounded non-empty string")
    return item


def _boolean(value: Mapping[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise TypeError(f"{key} must be a boolean")
    return item


def _state(value: Mapping[str, Any], key: str) -> str:
    state = _string(value, key, maximum=64).lower()
    if state not in _NODE_STATES:
        raise ValueError(f"{key} is not a supported node state")
    return state


def _models(value: Mapping[str, Any], key: str) -> tuple[str, ...]:
    models = value.get(key)
    if not isinstance(models, list) or len(models) > _MAX_MODELS:
        raise TypeError(f"{key} must be a bounded list")
    if any(not isinstance(model, str) or not model or len(model) > 512 for model in models):
        raise TypeError(f"{key} must contain bounded non-empty strings")
    if len(models) != len(set(models)):
        raise ValueError(f"{key} must contain unique values")
    return tuple(models)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result
