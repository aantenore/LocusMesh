"""Bounded, strict file parsing at the CLI adapter boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

_MAX_INPUT_BYTES = 1_048_576


def _read_bounded(path: Path) -> str:
    if path.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds {_MAX_INPUT_BYTES} bytes")
    return path.read_text(encoding="utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_json_model(path: Path, model: type[BaseModel]) -> BaseModel:
    """Parse one strict bounded JSON file into a Pydantic model."""

    data = json.loads(_read_bounded(path), object_pairs_hook=_reject_duplicate_keys)
    return model.model_validate(data)


def load_yaml_model(path: Path, model: type[BaseModel]) -> BaseModel:
    """Parse policy/config YAML only, rejecting duplicate keys."""

    data = yaml.load(_read_bounded(path), Loader=_UniqueKeySafeLoader)
    return model.model_validate(data)
