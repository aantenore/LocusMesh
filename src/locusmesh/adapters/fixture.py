"""Strict JSON fixture topology adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from locusmesh.models import TopologySnapshot


class FixtureTopologyProvider:
    """Load one topology snapshot from a local JSON fixture."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def snapshot(self) -> TopologySnapshot:
        if self._path.stat().st_size > 1_048_576:
            raise ValueError("topology fixture exceeds 1 MiB")
        data = json.loads(
            self._path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
        return TopologySnapshot.model_validate(data)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result
