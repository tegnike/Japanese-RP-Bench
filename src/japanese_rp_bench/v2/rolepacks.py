"""Role pack loading and cross-file validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Mapping

import yaml

from japanese_rp_bench.v2.rules import evaluate_deterministic_rules
from japanese_rp_bench.v2.schemas import (
    RoleDefinition,
    RolePack,
    ScenarioDefinition,
    SchemaError,
)


def load_role_pack(path: str | Path) -> RolePack:
    root = Path(path).expanduser().resolve()
    manifest_path = root / "pack.yaml"
    if not manifest_path.is_file():
        raise SchemaError(f"Role pack manifest not found: {manifest_path}")

    manifest = _load_yaml(manifest_path)
    for key in ("id", "name", "version", "description", "roles", "scenarios"):
        if key not in manifest:
            raise SchemaError(f"Role pack manifest is missing {key}")

    roles: Dict[str, RoleDefinition] = {}
    for relative_path in _as_path_list(manifest["roles"], "roles"):
        role = RoleDefinition.from_dict(_load_pack_file(root, relative_path))
        try:
            evaluate_deterministic_rules(role, "", turn=1)
        except (ValueError, re.error) as exc:
            raise SchemaError(f"Invalid deterministic rule in role {role.id}: {exc}") from exc
        if role.id in roles:
            raise SchemaError(f"Duplicate role id in role pack: {role.id}")
        roles[role.id] = role

    scenarios: Dict[str, ScenarioDefinition] = {}
    for relative_path in _as_path_list(manifest["scenarios"], "scenarios"):
        scenario = ScenarioDefinition.from_dict(_load_pack_file(root, relative_path))
        if scenario.id in scenarios:
            raise SchemaError(f"Duplicate scenario id in role pack: {scenario.id}")
        if scenario.role_id not in roles:
            raise SchemaError(
                f"Scenario {scenario.id} references missing role {scenario.role_id}"
            )
        role_rule_ids = {rule.id for rule in roles[scenario.role_id].rules}
        for probe in scenario.probes:
            unknown = sorted(set(probe.rule_ids) - role_rule_ids)
            if unknown:
                raise SchemaError(
                    f"Probe {probe.id} references unknown rules: {', '.join(unknown)}"
                )
        scenarios[scenario.id] = scenario

    return RolePack(
        id=str(manifest["id"]),
        name=str(manifest["name"]),
        version=str(manifest["version"]),
        description=str(manifest["description"]),
        roles=roles,
        scenarios=scenarios,
        metadata=dict(manifest.get("metadata", {})),
    )


def _load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SchemaError(f"Failed to load YAML {path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise SchemaError(f"YAML root must be an object: {path}")
    return data


def _load_pack_file(root: Path, relative_path: str) -> Mapping[str, Any]:
    target = (root / relative_path).resolve()
    if root not in target.parents:
        raise SchemaError(f"Role pack path escapes the pack directory: {relative_path}")
    if not target.is_file():
        raise SchemaError(f"Role pack file not found: {target}")
    return _load_yaml(target)


def _as_path_list(value: Any, context: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SchemaError(f"Role pack {context} must be a list of file paths")
    if not value:
        raise SchemaError(f"Role pack {context} must not be empty")
    return value
