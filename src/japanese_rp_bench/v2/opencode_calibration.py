"""Preregistered fixed-conversation calibration for OpenCode Go judges."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import shutil
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

from japanese_rp_bench.v2.providers import ModelSpec, RateLimitError, _reasoning_request_config
from japanese_rp_bench.v2.rolepacks import load_role_pack
from japanese_rp_bench.v2.scoring import score_conversation
from japanese_rp_bench.v2.runner import (
    _run_scenario,
    _run_synchronous_pilot_judges,
    _safe_name,
)
from japanese_rp_bench.v2.schemas import Conversation, JudgeEvaluation, RolePack, SchemaError


DEFAULT_PLAN = Path("configs/opencode_judge_calibration_2026-07-27.json")
DEFAULT_ANALYSIS_PLAN = Path("configs/opencode_judge_calibration_analysis_2026-07-27.json")
MODEL_ENDPOINT = "https://opencode.ai/zen/go/v1/models"
MODEL_SNAPSHOT_SCHEMA = "1.0"
MANIFEST_SCHEMA = "1.0"
CALIBRATION_METRICS = (
    "role_fidelity_score",
    "conversation_quality_score",
    "persona_stability_score",
    "robustness_score",
)
PRIMARY_CALIBRATION_METRICS = CALIBRATION_METRICS[:3]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_plan(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    if not isinstance(value, dict):
        raise SchemaError("Calibration plan must be a JSON object")
    validate_plan(value)
    return value


def _candidate_specs(plan: Mapping[str, Any]) -> dict[str, ModelSpec]:
    return {
        str(raw["id"]): ModelSpec.from_dict(raw)
        for raw in plan["judge_candidates"]
    }


def validate_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("schema_version") != "1.0":
        raise SchemaError("Unsupported calibration plan schema")
    split = plan.get("split")
    if not isinstance(split, Mapping):
        raise SchemaError("Calibration plan is missing split")
    calibration = tuple(str(item) for item in split.get("calibration_target_ids", []))
    holdout = tuple(str(item) for item in split.get("holdout_target_ids", []))
    if len(calibration) != 9 or len(holdout) != 6 or set(calibration) & set(holdout):
        raise SchemaError("Calibration/holdout must be disjoint 9/6 target-model splits")
    if set(holdout) != set(str(item) for item in plan.get("targets", [])):
        raise SchemaError("Holdout must contain exactly the six registered Stage B targets")
    scenarios = tuple(str(item) for item in plan.get("challenge_scenario_ids", []))
    if len(scenarios) != 6 or len(set(scenarios)) != 6:
        raise SchemaError("Exactly six unique Challenge scenario IDs are required")

    policy = plan.get("judge_policy")
    if not isinstance(policy, Mapping):
        raise SchemaError("Calibration plan is missing judge_policy")
    if policy.get("abstract_reasoning") != "low":
        raise SchemaError("All calibration judges must use abstract reasoning=low")
    if int(policy.get("challenge_max_output_tokens", 0)) != 8192:
        raise SchemaError("Calibration Judge output limit must be 8192")
    candidates = plan.get("judge_candidates")
    if not isinstance(candidates, list) or len(candidates) != 5:
        raise SchemaError("Exactly five preregistered Judge candidates are required")
    candidate_specs = _candidate_specs_unvalidated(candidates)
    target_models = {item.removeprefix("opencode-go-") for item in holdout}
    for raw, spec in zip(candidates, candidate_specs):
        if spec.reasoning != "low":
            raise SchemaError(f"Judge candidate must use reasoning=low: {spec.id}")
        if spec.model in target_models:
            raise SchemaError(f"Judge candidate duplicates a target model ID: {spec.model}")
        expected = raw.get("reasoning_request")
        actual = _reasoning_request_config(spec)
        if expected != actual:
            raise SchemaError(
                f"Reasoning request mismatch for {spec.id}: expected={expected} actual={actual}"
            )

    expected = plan.get("expected_judge_outputs", {})
    calibration_outputs = (
        int(split["calibration_target_responses"])
        * len(candidates)
        * int(policy["calibration_repetitions_per_candidate"])
    )
    holdout_outputs = (
        int(split["holdout_target_responses"])
        * int(plan["ensemble_selection"]["size"])
        * int(policy["holdout_repetitions_for_selected_ensemble"])
    )
    pilot_outputs = int(plan["technical_pilot"]["requests_per_candidate"]) * len(candidates)
    if (
        int(expected.get("calibration", -1)) != calibration_outputs
        or int(expected.get("holdout", -1)) != holdout_outputs
        or int(expected.get("technical_pilot", -1)) != pilot_outputs
    ):
        raise SchemaError("Expected Judge output counts do not match the registered design")
    return {
        "status": "valid",
        "calibration_targets": len(calibration),
        "holdout_targets": len(holdout),
        "candidates": len(candidates),
        "expected_judge_outputs": pilot_outputs + calibration_outputs + holdout_outputs,
    }


def _candidate_specs_unvalidated(candidates: Sequence[Mapping[str, Any]]) -> list[ModelSpec]:
    return [ModelSpec.from_dict(item) for item in candidates]


def snapshot_models(output: Path) -> dict[str, Any]:
    request = urllib.request.Request(
        MODEL_ENDPOINT,
        headers={
            "Accept": "application/json",
            "User-Agent": "Japanese-RP-Bench/0.1 OpenCode-Judge-Calibration",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    payload = json.loads(raw)
    models = payload.get("data")
    if not isinstance(models, list):
        raise SchemaError("OpenCode Go model endpoint returned no data list")
    ids = sorted(str(item["id"]) for item in models if isinstance(item, Mapping) and item.get("id"))
    snapshot = {
        "schema_version": MODEL_SNAPSHOT_SCHEMA,
        "fetched_at": _now(),
        "endpoint": MODEL_ENDPOINT,
        "model_ids": ids,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
    }
    _write_json(output, snapshot)
    return snapshot


def _load_packs(repo: Path, plan: Mapping[str, Any]) -> tuple[list[RolePack], dict[str, RolePack]]:
    packs = [load_role_pack(repo / str(relative)) for relative in plan["role_packs"]]
    by_scenario: dict[str, RolePack] = {}
    for pack in packs:
        for scenario_id in pack.scenarios:
            if scenario_id in by_scenario:
                raise SchemaError(f"Duplicate scenario ID across packs: {scenario_id}")
            by_scenario[scenario_id] = pack
    if set(plan["challenge_scenario_ids"]) != set(by_scenario):
        raise SchemaError("Registered scenario IDs do not match the current Role Packs")
    return packs, by_scenario


def _artifact(path: Path, source_repo: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SchemaError(f"Required source artifact is missing: {path}")
    return {
        "path": str(path.relative_to(source_repo)),
        "sha256": _sha256_file(path),
    }


def _challenge_conversations(source_root: Path, target_id: str) -> list[Path]:
    return sorted(
        path
        for path in (source_root / "conversations" / target_id).glob("*.json")
        if not path.name.startswith("legacy-base-ja__")
    )


def build_case_registry(
    repo: Path,
    source_repo: Path,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    source_map_path = source_repo / str(plan["source"]["artifact_map"])
    source_map = _read_json(source_map_path)
    _, pack_by_scenario = _load_packs(repo, plan)
    split_for_target = {
        target_id: split
        for split, key in (
            ("calibration", "calibration_target_ids"),
            ("holdout", "holdout_target_ids"),
        )
        for target_id in plan["split"][key]
    }
    repeatability_root = source_repo / str(plan["source"]["repeatability_root"])
    cases: list[dict[str, Any]] = []
    counts = {
        "calibration": {"conversations": 0, "target_responses": 0},
        "holdout": {"conversations": 0, "target_responses": 0},
    }
    for target_id in itertools.chain(
        plan["split"]["calibration_target_ids"],
        plan["split"]["holdout_target_ids"],
    ):
        record = source_map.get("targets", {}).get(target_id)
        if not isinstance(record, Mapping):
            raise SchemaError(f"Source map has no target: {target_id}")
        source_root = source_repo / str(record["source_root"])
        conversations = _challenge_conversations(source_root, target_id)
        if len(conversations) != 6:
            raise SchemaError(f"Expected six Challenge conversations for {target_id}")
        seen_scenarios: set[str] = set()
        for conversation_path in conversations:
            payload = _read_json(conversation_path)
            scenario_id = str(payload["scenario_id"])
            if scenario_id not in pack_by_scenario or scenario_id in seen_scenarios:
                raise SchemaError(f"Unknown or duplicate scenario for {target_id}: {scenario_id}")
            seen_scenarios.add(scenario_id)
            pack_id = pack_by_scenario[scenario_id].id
            current_stem = f"{_safe_name(pack_id)}__{_safe_name(scenario_id)}"
            official_stem = conversation_path.stem
            split = split_for_target[target_id]
            turns = len(payload["turns"])
            round_artifacts = {}
            for round_name in ("round-01", "round-02"):
                round_root = repeatability_root / round_name
                round_artifacts[round_name] = {
                    "judgments": _artifact(
                        round_root / "judgments" / target_id / f"{current_stem}.jsonl",
                        source_repo,
                    ),
                    "report": _artifact(
                        round_root / "reports" / target_id / f"{current_stem}.json",
                        source_repo,
                    ),
                }
            cases.append(
                {
                    "case_id": "|".join((target_id, pack_id, scenario_id)),
                    "split": split,
                    "target_id": target_id,
                    "pack_id": pack_id,
                    "scenario_id": scenario_id,
                    "target_responses": turns,
                    "source_run_fingerprint": record["source_run_fingerprint"],
                    "conversation": _artifact(conversation_path, source_repo),
                    "official": {
                        "judgments": _artifact(
                            source_root / "judgments" / target_id / f"{official_stem}.jsonl",
                            source_repo,
                        ),
                        "report": _artifact(
                            source_root / "reports" / target_id / f"{official_stem}.json",
                            source_repo,
                        ),
                    },
                    "repeatability": round_artifacts,
                }
            )
            counts[split]["conversations"] += 1
            counts[split]["target_responses"] += turns
        if seen_scenarios != set(plan["challenge_scenario_ids"]):
            raise SchemaError(f"Scenario coverage mismatch for {target_id}")
    cases.sort(key=lambda item: item["case_id"])
    expected = plan["split"]
    for split in ("calibration", "holdout"):
        if counts[split]["conversations"] != int(expected[f"{split}_conversations"]):
            raise SchemaError(f"{split} conversation count mismatch")
        if counts[split]["target_responses"] != int(expected[f"{split}_target_responses"]):
            raise SchemaError(f"{split} target-response count mismatch")
    return {
        "schema_version": "1.0",
        "created_at": _now(),
        "source_map": _artifact(source_map_path, source_repo),
        "counts": counts,
        "cases": cases,
        "registry_sha256": _sha256_json(cases),
    }


def prepare(
    repo: Path,
    source_repo: Path,
    plan_path: Path,
    output: Path,
    model_snapshot_path: Path,
) -> dict[str, Any]:
    plan = _load_plan(plan_path)
    snapshot = _read_json(model_snapshot_path)
    available = set(str(item) for item in snapshot.get("model_ids", []))
    missing = sorted(spec.model for spec in _candidate_specs(plan).values() if spec.model not in available)
    if missing:
        raise SchemaError(f"Judge candidates missing from model snapshot: {missing}")
    plan_sha = _sha256_file(plan_path)
    fingerprint_seed = {
        "experiment_id": plan["experiment_id"],
        "plan_sha256": plan_sha,
        "model_snapshot_sha256": _sha256_file(model_snapshot_path),
    }
    fingerprint = _sha256_json(fingerprint_seed)
    manifest_path = output / "manifest.json"
    if output.exists() and not manifest_path.is_file() and any(output.iterdir()):
        raise SchemaError(f"Output exists without calibration manifest: {output}")
    if manifest_path.is_file():
        existing = _read_json(manifest_path)
        if existing.get("experiment_fingerprint") != fingerprint:
            raise SchemaError("Existing calibration output has a different fingerprint")
        return existing
    output.mkdir(parents=True, exist_ok=True)
    registry = build_case_registry(repo, source_repo, plan)
    _write_json(output / "case-registry.json", registry)
    shutil.copyfile(model_snapshot_path, output / "model-snapshot.json")
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "experiment_id": plan["experiment_id"],
        "status": "prepared",
        "prepared_at": _now(),
        "experiment_fingerprint": fingerprint,
        "plan": {"path": str(plan_path), "sha256": plan_sha},
        "model_snapshot_sha256": _sha256_file(output / "model-snapshot.json"),
        "case_registry_sha256": _sha256_file(output / "case-registry.json"),
        "source_repo": str(source_repo),
        "official_leaderboard_changes": False,
        "api_calls_made": 0,
    }
    _write_json(manifest_path, manifest)
    return manifest


def _source_target_spec(source_repo: Path, registry_case: Mapping[str, Any]) -> ModelSpec:
    source_root = source_repo / str(registry_case["conversation"]["path"])
    source_manifest = source_root.parents[2] / "manifest.json"
    manifest = _read_json(source_manifest)
    target_id = str(registry_case["target_id"])
    raw = next(item for item in manifest["targets"] if item["id"] == target_id)
    raw = dict(raw)
    raw["api_key_env"] = "UNUSED_FIXED_CONVERSATION"
    raw["batch"] = False
    return ModelSpec.from_dict(raw)


def _run_fingerprint(
    experiment_fingerprint: str,
    phase: str,
    candidate_id: str,
    repetition: int,
    case_ids: Sequence[str],
) -> str:
    return _sha256_json(
        {
            "experiment_fingerprint": experiment_fingerprint,
            "phase": phase,
            "candidate_id": candidate_id,
            "repetition": repetition,
            "case_ids": list(case_ids),
        }
    )


def _select_cases(plan: Mapping[str, Any], registry: Mapping[str, Any], phase: str) -> list[dict[str, Any]]:
    cases = list(registry["cases"])
    if phase == "pilot":
        targets = set(plan["technical_pilot"]["target_ids"])
        scenarios = set(plan["technical_pilot"]["scenario_ids"])
        selected = [
            item
            for item in cases
            if item["target_id"] in targets and item["scenario_id"] in scenarios
        ]
        expected = int(plan["technical_pilot"]["requests_per_candidate"])
        if len(selected) != expected:
            raise SchemaError(f"Pilot case count mismatch: {len(selected)} != {expected}")
        return selected
    selected = [item for item in cases if item["split"] == phase]
    if not selected:
        raise SchemaError(f"No registry cases for phase: {phase}")
    return selected


def _prepare_run(
    repo: Path,
    source_repo: Path,
    output: Path,
    plan: Mapping[str, Any],
    phase: str,
    candidate: ModelSpec,
    repetition: int,
) -> tuple[Path, list[tuple[RolePack, Any, ModelSpec]], str]:
    experiment = _read_json(output / "manifest.json")
    registry = _read_json(output / "case-registry.json")
    cases = _select_cases(plan, registry, phase)
    run_root = output / "runs" / phase / _safe_name(candidate.id) / f"repeat-{repetition:02d}"
    case_ids = sorted(str(item["case_id"]) for item in cases)
    fingerprint = _run_fingerprint(
        str(experiment["experiment_fingerprint"]), phase, candidate.id, repetition, case_ids
    )
    manifest_path = run_root / "manifest.json"
    if manifest_path.is_file():
        existing = _read_json(manifest_path)
        if existing.get("run_fingerprint") != fingerprint:
            raise SchemaError(f"Run fingerprint mismatch: {run_root}")
    elif run_root.exists() and any(run_root.iterdir()):
        raise SchemaError(f"Run artifacts exist without manifest: {run_root}")
    packs, pack_by_scenario = _load_packs(repo, plan)
    del packs
    jobs = []
    for case in cases:
        conversation_source = source_repo / str(case["conversation"]["path"])
        payload = _read_json(conversation_source)
        payload.setdefault("metadata", {})["run_fingerprint"] = fingerprint
        payload["metadata"]["opencode_judge_calibration"] = {
            "case_id": case["case_id"],
            "fixed_source_path": case["conversation"]["path"],
            "fixed_source_sha256": case["conversation"]["sha256"],
            "phase": phase,
            "candidate_id": candidate.id,
            "repetition": repetition,
        }
        destination = (
            run_root
            / "conversations"
            / _safe_name(str(case["target_id"]))
            / f"{_safe_name(str(case['pack_id']))}__{_safe_name(str(case['scenario_id']))}.json"
        )
        if destination.is_file():
            existing = _read_json(destination)
            provenance = existing.get("metadata", {}).get("opencode_judge_calibration", {})
            if provenance.get("fixed_source_sha256") != case["conversation"]["sha256"]:
                raise SchemaError(f"Conversation provenance mismatch: {destination}")
        else:
            _write_json(destination, payload)
        target_spec = _source_target_spec(source_repo, case)
        pack = pack_by_scenario[str(case["scenario_id"])]
        jobs.append((pack, pack.scenarios[str(case["scenario_id"])], target_spec))
    run_manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "phase": phase,
        "candidate": {
            "id": candidate.id,
            "model": candidate.model,
            "api_style": candidate.api_style,
            "reasoning": candidate.reasoning,
            "reasoning_request": _reasoning_request_config(candidate),
        },
        "repetition": repetition,
        "status": "prepared",
        "prepared_at": _now(),
        "run_fingerprint": fingerprint,
        "case_count": len(cases),
        "expected_judge_outputs": (
            len(cases)
            if phase == "pilot"
            else sum(int(item["target_responses"]) for item in cases)
        ),
        "judge_max_output_tokens": int(plan["judge_policy"]["challenge_max_output_tokens"]),
        "use_balance_confirmed_off": False,
        "failures": [],
    }
    if manifest_path.is_file():
        old = _read_json(manifest_path)
        for key in ("status", "started_at", "completed_at", "failures", "use_balance_confirmed_off"):
            if key in old:
                run_manifest[key] = old[key]
    _write_json(manifest_path, run_manifest)
    return run_root, jobs, fingerprint


def _judge_output_count(run_root: Path) -> int:
    count = 0
    for path in (run_root / "judgments").glob("**/*.jsonl"):
        if path.name.endswith(".raw-attempts.jsonl"):
            continue
        count += len(_read_jsonl(path))
    return count


def _validate_call_contract(run_root: Path, candidate: ModelSpec, max_tokens: int) -> list[str]:
    errors: list[str] = []
    expected_reasoning = _reasoning_request_config(candidate)
    for path in sorted((run_root / "judgments").glob("**/*.jsonl")):
        if path.name.endswith(".raw-attempts.jsonl"):
            continue
        for item in _read_jsonl(path):
            calls = item.get("metadata", {}).get("calls", [])
            if not calls:
                errors.append(f"{path}: successful artifact has no call metadata")
                continue
            for call_index, call in enumerate(calls, start=1):
                if call.get("reasoning_config") != expected_reasoning:
                    errors.append(f"{path}: call {call_index} reasoning_config mismatch")
                if int(call.get("requested_max_output_tokens", 0)) != max_tokens:
                    errors.append(f"{path}: call {call_index} requested_max_output_tokens mismatch")
                if call.get("termination_category") != "completed":
                    errors.append(f"{path}: call {call_index} non-completed termination")
                if call.get("incomplete_reason"):
                    errors.append(f"{path}: call {call_index} incomplete_reason is set")
    return errors


def _first_attempt_structured_success_rate(run_root: Path) -> float:
    attempts_per_output = []
    for path in sorted((run_root / "judgments").glob("**/*.jsonl")):
        if path.name.endswith(".raw-attempts.jsonl"):
            continue
        for item in _read_jsonl(path):
            attempts_per_output.append(len(item.get("metadata", {}).get("calls", [])))
    if not attempts_per_output:
        return 0.0
    return sum(attempts == 1 for attempts in attempts_per_output) / len(attempts_per_output)


def _recorded_run_failures(run_root: Path) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    path = run_root / "run-events.jsonl"
    if path.is_file():
        for event in _read_jsonl(path):
            failures.extend(
                dict(item)
                for item in event.get("failures", [])
                if isinstance(item, Mapping)
            )
    return failures


def _terminal_outcome_count(run_root: Path) -> int:
    count = 0
    for path in sorted((run_root / "judgments").glob("**/*.raw-attempts.jsonl")):
        for item in _read_jsonl(path):
            call = item.get("call") or {}
            if call.get("termination_category") != "completed":
                count += 1
    return count


def _refresh_api_call_count(output: Path) -> int:
    response_ids: set[str] = set()
    fallback_calls = 0
    for path in sorted((output / "runs").glob("**/*.jsonl")):
        for item in _read_jsonl(path):
            calls = []
            if path.name.endswith(".raw-attempts.jsonl"):
                call = item.get("call")
                if isinstance(call, Mapping):
                    calls.append(call)
            else:
                calls.extend(
                    call
                    for call in item.get("metadata", {}).get("calls", [])
                    if isinstance(call, Mapping)
                )
            for call in calls:
                response_id = str(call.get("response_id", ""))
                if response_id:
                    response_ids.add(response_id)
                else:
                    fallback_calls += 1
    total = len(response_ids) + fallback_calls
    manifest_path = output / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["api_calls_made"] = total
    manifest["last_api_call_counted_at"] = _now()
    _write_json(manifest_path, manifest)
    return total


def run_pilot(
    repo: Path,
    source_repo: Path,
    plan_path: Path,
    output: Path,
    candidate_ids: Sequence[str],
    confirm_use_balance_off: bool,
) -> dict[str, Any]:
    if not confirm_use_balance_off:
        raise SchemaError("Refusing API calls without --confirm-use-balance-off")
    plan = _load_plan(plan_path)
    specs = _candidate_specs(plan)
    requested = list(candidate_ids) or list(specs)
    unknown = sorted(set(requested) - set(specs))
    if unknown:
        raise SchemaError(f"Unknown Judge candidates: {unknown}")
    if not os.environ.get("OPENCODE_GO_API_KEY"):
        raise SchemaError("OPENCODE_GO_API_KEY is not set")
    summary_path = output / "pilot-summary.json"
    previous = _read_json(summary_path) if summary_path.is_file() else {"candidates": {}}
    results = dict(previous.get("candidates", {}))
    config = {
        "evaluation": {
            "judge_ensemble": {"minimum_judges": 1},
            "judge_max_output_tokens": int(plan["judge_policy"]["challenge_max_output_tokens"]),
            "base_judge_max_output_tokens": 8192,
        }
    }
    for candidate_id in requested:
        candidate = specs[candidate_id]
        run_root, jobs, fingerprint = _prepare_run(
            repo, source_repo, output, plan, "pilot", candidate, 1
        )
        manifest_path = run_root / "manifest.json"
        manifest = _read_json(manifest_path)
        manifest["status"] = "running"
        manifest["started_at"] = manifest.get("started_at", _now())
        manifest["use_balance_confirmed_off"] = True
        _write_json(manifest_path, manifest)
        run_error = None
        try:
            _run_synchronous_pilot_judges(
                run_root,
                jobs,
                [candidate],
                config,
                "",
                fingerprint,
            )
        except Exception as exc:
            run_error = f"{type(exc).__name__}: {exc}"
        count = _judge_output_count(run_root)
        errors = _validate_call_contract(
            run_root, candidate, int(plan["judge_policy"]["challenge_max_output_tokens"])
        )
        expected = int(plan["technical_pilot"]["requests_per_candidate"])
        first_attempt_rate = _first_attempt_structured_success_rate(run_root)
        passed = count == expected and not errors and run_error is None and first_attempt_rate == 1.0
        manifest["status"] = "complete" if passed else "failed"
        manifest["completed_at"] = _now()
        manifest["successful_judge_outputs"] = count
        manifest["first_attempt_structured_success_rate"] = first_attempt_rate
        manifest["contract_errors"] = errors
        manifest["run_error"] = run_error
        _write_json(manifest_path, manifest)
        results[candidate_id] = {
            "passed": passed,
            "outputs": count,
            "first_attempt_structured_success_rate": first_attempt_rate,
            "errors": errors,
            "run_error": run_error,
        }
    summary = {"schema_version": "1.0", "completed_at": _now(), "candidates": results}
    _write_json(summary_path, summary)
    summary["api_calls_made"] = _refresh_api_call_count(output)
    _write_json(summary_path, summary)
    return summary


def _execute_jobs_with_rate_limit_resume(
    run_root: Path,
    jobs: Sequence[tuple[RolePack, Any, ModelSpec]],
    candidate: ModelSpec,
    config: Mapping[str, Any],
    fingerprint: str,
    workers: int,
    max_attempts: int,
) -> list[dict[str, Any]]:
    pending = list(jobs)
    reports: list[dict[str, Any]] = []
    current_workers = max(1, min(workers, len(pending)))
    for attempt in range(1, max_attempts + 1):
        limited = []
        failures = []
        with ThreadPoolExecutor(max_workers=current_workers) as executor:
            futures = {
                executor.submit(
                    _run_scenario,
                    run_root,
                    pack,
                    scenario,
                    target,
                    None,
                    [candidate],
                    config,
                    "",
                    fingerprint,
                ): (pack, scenario, target)
                for pack, scenario, target in pending
            }
            for future in as_completed(futures):
                job = futures[future]
                try:
                    reports.append(future.result())
                except RateLimitError as exc:
                    limited.append(job)
                    failures.append({"type": "RateLimitError", "error": str(exc)})
                except Exception as exc:
                    failures.append({
                        "target": job[2].id,
                        "scenario": job[1].id,
                        "type": type(exc).__name__,
                        "error": str(exc),
                    })
        if failures:
            event = {
                "recorded_at": _now(),
                "attempt": attempt,
                "workers": current_workers,
                "failures": failures,
                "rate_limited_jobs": len(limited),
            }
            path = run_root / "run-events.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        non_rate_limit = [item for item in failures if item["type"] != "RateLimitError"]
        if non_rate_limit:
            raise SchemaError(f"Calibration Judge run failed: {non_rate_limit[0]}")
        if not limited:
            return reports
        if attempt == max_attempts:
            raise RateLimitError(f"{len(limited)} calibration jobs remain rate-limited")
        pending = sorted(limited, key=lambda item: (item[2].id, item[1].id))
        current_workers = max(1, current_workers // 2)
        time.sleep(min(30 * attempt, 60))
    return reports


def run_calibration(
    repo: Path,
    source_repo: Path,
    plan_path: Path,
    output: Path,
    candidate_id: str,
    repetition: int,
    workers: int,
    confirm_use_balance_off: bool,
) -> dict[str, Any]:
    if not confirm_use_balance_off:
        raise SchemaError("Refusing API calls without --confirm-use-balance-off")
    plan = _load_plan(plan_path)
    specs = _candidate_specs(plan)
    if candidate_id not in specs:
        raise SchemaError(f"Unknown Judge candidate: {candidate_id}")
    max_repetitions = int(plan["judge_policy"]["calibration_repetitions_per_candidate"])
    if repetition not in range(1, max_repetitions + 1):
        raise SchemaError(f"Calibration repetition must be 1..{max_repetitions}")
    pilot_summary = _read_json(output / "pilot-summary.json")
    if not pilot_summary.get("candidates", {}).get(candidate_id, {}).get("passed"):
        raise SchemaError(f"Candidate has not passed technical pilot: {candidate_id}")
    if not os.environ.get("OPENCODE_GO_API_KEY"):
        raise SchemaError("OPENCODE_GO_API_KEY is not set")
    candidate = specs[candidate_id]
    run_root, jobs, fingerprint = _prepare_run(
        repo, source_repo, output, plan, "calibration", candidate, repetition
    )
    manifest_path = run_root / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["status"] = "running"
    manifest["started_at"] = manifest.get("started_at", _now())
    manifest["use_balance_confirmed_off"] = True
    _write_json(manifest_path, manifest)
    config = {
        "evaluation": {
            "judge_ensemble": {"minimum_judges": 1},
            "judge_max_output_tokens": int(plan["judge_policy"]["challenge_max_output_tokens"]),
            "base_judge_max_output_tokens": 8192,
        }
    }
    run_exception: Exception | None = None
    try:
        _execute_jobs_with_rate_limit_resume(
            run_root,
            jobs,
            candidate,
            config,
            fingerprint,
            workers,
            int(plan["judge_policy"]["max_attempts_per_request"]),
        )
    except Exception as exc:
        run_exception = exc
    count = _judge_output_count(run_root)
    expected = int(plan["split"]["calibration_target_responses"])
    errors = _validate_call_contract(
        run_root, candidate, int(plan["judge_policy"]["challenge_max_output_tokens"])
    )
    first_attempt_rate = _first_attempt_structured_success_rate(run_root)
    report_count = len(list((run_root / "reports").glob("**/*.json")))
    failures = _recorded_run_failures(run_root)
    terminal_outcomes = _terminal_outcome_count(run_root)
    passed = (
        run_exception is None
        and count == expected
        and report_count == int(plan["split"]["calibration_conversations"])
        and not errors
        and terminal_outcomes == 0
    )
    manifest["status"] = "complete" if passed else "failed"
    manifest["completed_at"] = _now()
    manifest["successful_judge_outputs"] = count
    manifest["reports"] = report_count
    manifest["first_attempt_structured_success_rate"] = first_attempt_rate
    manifest["contract_errors"] = errors
    manifest["failures"] = failures
    manifest["terminal_outcomes"] = terminal_outcomes
    manifest["run_error"] = (
        f"{type(run_exception).__name__}: {run_exception}" if run_exception else None
    )
    manifest["experiment_api_calls_made"] = _refresh_api_call_count(output)
    _write_json(manifest_path, manifest)
    if run_exception is not None:
        raise run_exception
    if not passed:
        raise SchemaError(f"Calibration run incomplete: {manifest}")
    return manifest


def reconcile_calibration(
    plan_path: Path,
    output: Path,
    candidate_id: str,
    repetition: int,
) -> dict[str, Any]:
    """Finalize an interrupted run from persisted artifacts without API calls."""
    plan = _load_plan(plan_path)
    specs = _candidate_specs(plan)
    if candidate_id not in specs:
        raise SchemaError(f"Unknown Judge candidate: {candidate_id}")
    run_root = output / "runs" / "calibration" / _safe_name(candidate_id) / f"repeat-{repetition:02d}"
    manifest_path = run_root / "manifest.json"
    manifest = _read_json(manifest_path)
    candidate = specs[candidate_id]
    count = _judge_output_count(run_root)
    report_count = len(list((run_root / "reports").glob("**/*.json")))
    errors = _validate_call_contract(
        run_root, candidate, int(plan["judge_policy"]["challenge_max_output_tokens"])
    )
    failures = _recorded_run_failures(run_root)
    terminal_outcomes = _terminal_outcome_count(run_root)
    expected = int(plan["split"]["calibration_target_responses"])
    passed = (
        count == expected
        and report_count == int(plan["split"]["calibration_conversations"])
        and not errors
        and not failures
        and terminal_outcomes == 0
    )
    manifest.update({
        "status": "complete" if passed else "failed",
        "completed_at": _now(),
        "successful_judge_outputs": count,
        "reports": report_count,
        "first_attempt_structured_success_rate": _first_attempt_structured_success_rate(run_root),
        "contract_errors": errors,
        "failures": failures,
        "terminal_outcomes": terminal_outcomes,
        "run_error": None if passed else "reconciled_from_persisted_run_failures",
        "experiment_api_calls_made": _refresh_api_call_count(output),
    })
    _write_json(manifest_path, manifest)
    return manifest


def _rankdata(values: Sequence[float]) -> list[float]:
    """Return one-based average ranks, including deterministic tie handling."""
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        rank = ((start + 1) + end) / 2.0
        for original_index, _ in indexed[start:end]:
            ranks[original_index] = rank
        start = end
    return ranks


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = mean(left)
    right_mean = mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_ss = sum((value - left_mean) ** 2 for value in left)
    right_ss = sum((value - right_mean) ** 2 for value in right)
    if left_ss == 0.0 or right_ss == 0.0:
        return 1.0 if list(left) == list(right) else None
    return numerator / math.sqrt(left_ss * right_ss)


def _spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    return _pearson(_rankdata(left), _rankdata(right))


def _cohens_kappa(reference: Sequence[bool], predicted: Sequence[bool]) -> dict[str, Any]:
    if len(reference) != len(predicted) or not reference:
        raise SchemaError("Major agreement requires equally sized non-empty labels")
    tp = sum(old and new for old, new in zip(reference, predicted))
    tn = sum(not old and not new for old, new in zip(reference, predicted))
    fp = sum(not old and new for old, new in zip(reference, predicted))
    fn = sum(old and not new for old, new in zip(reference, predicted))
    total = len(reference)
    observed = (tp + tn) / total
    reference_positive = (tp + fn) / total
    predicted_positive = (tp + fp) / total
    expected = (
        reference_positive * predicted_positive
        + (1.0 - reference_positive) * (1.0 - predicted_positive)
    )
    kappa = 1.0 if expected == 1.0 and observed == 1.0 else (
        None if expected == 1.0 else (observed - expected) / (1.0 - expected)
    )
    positive_denominator = 2 * tp + fp + fn
    negative_denominator = 2 * tn + fp + fn
    return {
        "cases": total,
        "cohens_kappa": kappa,
        "positive_agreement": None
        if positive_denominator == 0
        else 2 * tp / positive_denominator,
        "negative_agreement": None
        if negative_denominator == 0
        else 2 * tn / negative_denominator,
        "reference_prevalence": reference_positive,
        "predicted_prevalence": predicted_positive,
        "confusion": {"true_positive": tp, "true_negative": tn, "false_positive": fp, "false_negative": fn},
    }


def _tree_hash(paths: Iterable[Path], root: Path) -> dict[str, Any]:
    rows = [f"{path.relative_to(root)}\t{_sha256_file(path)}" for path in sorted(paths)]
    return {
        "files": len(rows),
        "sha256": hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest(),
    }


def _structural_candidate_status(
    plan: Mapping[str, Any],
    output: Path,
    candidate_id: str,
) -> dict[str, Any]:
    repetitions = []
    terminal_failure = False
    required_rate = float(plan["judge_policy"]["structured_output_first_attempt_success_rate_min"])
    repeat_count = int(plan["judge_policy"]["calibration_repetitions_per_candidate"])
    for repetition in range(1, repeat_count + 1):
        path = (
            output
            / "runs"
            / "calibration"
            / _safe_name(candidate_id)
            / f"repeat-{repetition:02d}"
            / "manifest.json"
        )
        if not path.is_file():
            repetitions.append({"repetition": repetition, "status": "not_run"})
            continue
        manifest = _read_json(path)
        rate = float(manifest.get("first_attempt_structured_success_rate", 0.0))
        terminal = int(manifest.get("terminal_outcomes", 0))
        terminal_failure = terminal_failure or terminal > 0
        passed = (
            manifest.get("status") == "complete"
            and int(manifest.get("successful_judge_outputs", 0))
            == int(plan["split"]["calibration_target_responses"])
            and int(manifest.get("reports", 0))
            == int(plan["split"]["calibration_conversations"])
            and rate >= required_rate
            and not manifest.get("contract_errors")
            and not manifest.get("failures")
            and terminal == 0
        )
        repetitions.append({
            "repetition": repetition,
            "status": manifest.get("status"),
            "passed": passed,
            "first_attempt_structured_success_rate": rate,
            "terminal_outcomes": terminal,
            "manifest": str(path),
            "manifest_sha256": _sha256_file(path),
        })
    eligible = len(repetitions) == repeat_count and all(item.get("passed") for item in repetitions)
    return {
        "candidate_id": candidate_id,
        "eligible": eligible,
        "terminal_failure": terminal_failure,
        "repetitions": repetitions,
    }


def _reference_report_path(
    source_repo: Path,
    case: Mapping[str, Any],
    measurement: str,
) -> Path:
    if measurement == "official":
        return source_repo / str(case["official"]["report"]["path"])
    return source_repo / str(case["repeatability"][measurement]["report"]["path"])


def _model_means(
    reports: Mapping[str, Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, float | None]]:
    target_ids = sorted({str(case["target_id"]) for case in cases})
    result: dict[str, dict[str, float | None]] = {}
    for target_id in target_ids:
        target_cases = [case for case in cases if case["target_id"] == target_id]
        result[target_id] = {}
        for metric in CALIBRATION_METRICS:
            values = [
                reports[str(case["case_id"])]["summary"].get(metric)
                for case in target_cases
            ]
            present = [float(value) for value in values if value is not None]
            result[target_id][metric] = mean(present) if present else None
    return result


def _continuous_comparison(
    reference: Mapping[str, Mapping[str, float | None]],
    predicted: Mapping[str, Mapping[str, float | None]],
) -> dict[str, dict[str, Any]]:
    result = {}
    for metric in CALIBRATION_METRICS:
        pairs = [
            (target, float(reference[target][metric]), float(predicted[target][metric]))
            for target in sorted(reference)
            if reference[target][metric] is not None and predicted[target][metric] is not None
        ]
        if not pairs:
            result[metric] = {"models": 0, "spearman": None, "mae": None}
            continue
        old = [item[1] for item in pairs]
        new = [item[2] for item in pairs]
        result[metric] = {
            "models": len(pairs),
            "spearman": _spearman(old, new),
            "mae": mean(
                abs(reference_value - predicted_value)
                for _, reference_value, predicted_value in pairs
            ),
            "mean_bias": mean(
                predicted_value - reference_value
                for _, reference_value, predicted_value in pairs
            ),
            "residual_by_target": {
                target: predicted_value - reference_value
                for target, reference_value, predicted_value in pairs
            },
        }
    return result


def _ensemble_reports(
    repo: Path,
    plan: Mapping[str, Any],
    output: Path,
    cases: Sequence[Mapping[str, Any]],
    candidate_ids: Sequence[str],
    repetition: int,
) -> dict[str, dict[str, Any]]:
    _, pack_by_scenario = _load_packs(repo, plan)
    reports: dict[str, dict[str, Any]] = {}
    for case in cases:
        target = _safe_name(str(case["target_id"]))
        stem = f"{_safe_name(str(case['pack_id']))}__{_safe_name(str(case['scenario_id']))}"
        evaluations = []
        conversation = None
        for candidate_id in candidate_ids:
            run_root = (
                output
                / "runs"
                / "calibration"
                / _safe_name(candidate_id)
                / f"repeat-{repetition:02d}"
            )
            conversation_path = run_root / "conversations" / target / f"{stem}.json"
            current = Conversation.from_dict(_read_json(conversation_path))
            if conversation is None:
                conversation = current
            elif current.to_dict()["turns"] != conversation.to_dict()["turns"]:
                raise SchemaError(f"Candidate conversations differ for {case['case_id']}")
            role_pack = pack_by_scenario[str(case["scenario_id"])]
            role = role_pack.roles[current.role_id]
            judgment_path = run_root / "judgments" / target / f"{stem}.jsonl"
            evaluations.extend(
                JudgeEvaluation.from_dict(item, role) for item in _read_jsonl(judgment_path)
            )
        if conversation is None:
            raise SchemaError(f"Missing ensemble conversation: {case['case_id']}")
        role_pack = pack_by_scenario[str(case["scenario_id"])]
        report = score_conversation(
            role_pack,
            conversation,
            evaluations,
            minimum_judges=len(candidate_ids),
        )
        reports[str(case["case_id"])] = report
    return reports


def analyze_calibration(
    repo: Path,
    source_repo: Path,
    plan_path: Path,
    analysis_plan_path: Path,
    output: Path,
) -> dict[str, Any]:
    """Select a frozen ensemble from calibration only; never reads holdout Judge outputs."""
    plan = _load_plan(plan_path)
    analysis_plan = _read_json(analysis_plan_path)
    if analysis_plan.get("schema_version") != "1.0":
        raise SchemaError("Unsupported calibration analysis plan schema")
    registered_sha = str(analysis_plan.get("parent_preregistered_plan", {}).get("sha256", ""))
    if registered_sha != _sha256_file(plan_path):
        raise SchemaError("Calibration analysis plan does not match the preregistered plan hash")
    experiment_manifest = _read_json(output / "manifest.json")
    if experiment_manifest.get("plan", {}).get("sha256") != registered_sha:
        raise SchemaError("Calibration output was prepared from a different preregistered plan")
    registry = _read_json(output / "case-registry.json")
    cases = [item for item in registry["cases"] if item["split"] == "calibration"]
    structural = {
        candidate_id: _structural_candidate_status(plan, output, candidate_id)
        for candidate_id in _candidate_specs(plan)
    }
    eligible = sorted(
        candidate_id for candidate_id, item in structural.items() if item["eligible"]
    )
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "created_at": _now(),
        "phase": "calibration",
        "structural_candidates": structural,
        "eligible_candidates": eligible,
        "reference_policy": {
            "measurements": list(plan["source"]["reference_measurements"]),
            "continuous_gate_reduction": analysis_plan["continuous_reference_gate_reduction"],
            "major_reference_label": analysis_plan["major_reference_label"],
        },
        "analysis_plan": {
            "path": str(analysis_plan_path),
            "sha256": _sha256_file(analysis_plan_path),
        },
        "holdout_opened": False,
    }
    ensemble_size = int(plan["ensemble_selection"]["size"])
    if len(eligible) < ensemble_size:
        result.update({
            "status": "failed_insufficient_structurally_eligible_candidates",
            "selected_ensemble": None,
            "combinations": [],
        })
        _write_json(output / "calibration-analysis.json", result)
        return result

    measurements = list(plan["source"]["reference_measurements"])
    references: dict[str, dict[str, dict[str, Any]]] = {}
    reference_means = {}
    for measurement in measurements:
        reports = {
            str(case["case_id"]): _read_json(
                _reference_report_path(source_repo, case, measurement)
            )
            for case in cases
        }
        references[measurement] = reports
        reference_means[measurement] = _model_means(reports, cases)
    majority_major = {
        str(case["case_id"]): sum(
            int(references[measurement][str(case["case_id"])]["summary"]["major_violations"]) > 0
            for measurement in measurements
        ) >= 2
        for case in cases
    }
    unstable_major_cases = [
        str(case["case_id"])
        for case in cases
        if len({
            int(references[measurement][str(case["case_id"])]["summary"]["major_violations"]) > 0
            for measurement in measurements
        }) > 1
    ]
    spearman_limits = plan["calibration_gates"]["model_mean_spearman_min"]
    mae_limits = plan["calibration_gates"]["model_mean_mae_max_challenge_scale"]
    kappa_limit = float(plan["calibration_gates"]["major_cohens_kappa_min"])
    combinations = []
    for candidate_ids in itertools.combinations(eligible, ensemble_size):
        alignments = []
        for repetition in range(
            1, int(plan["judge_policy"]["calibration_repetitions_per_candidate"]) + 1
        ):
            reports = _ensemble_reports(repo, plan, output, cases, candidate_ids, repetition)
            predicted_means = _model_means(reports, cases)
            comparisons = {
                measurement: _continuous_comparison(reference_means[measurement], predicted_means)
                for measurement in measurements
            }
            worst = {}
            for metric in CALIBRATION_METRICS:
                spearman_values = [
                    comparisons[measurement][metric]["spearman"]
                    for measurement in measurements
                ]
                mae_values = [comparisons[measurement][metric]["mae"] for measurement in measurements]
                worst[metric] = {
                    "minimum_spearman": None
                    if any(value is None for value in spearman_values)
                    else min(float(value) for value in spearman_values),
                    "maximum_mae": None
                    if any(value is None for value in mae_values)
                    else max(float(value) for value in mae_values),
                }
            reference_labels = [majority_major[str(case["case_id"])] for case in cases]
            predicted_labels = [
                int(reports[str(case["case_id"])]["summary"]["major_violations"]) > 0
                for case in cases
            ]
            major = _cohens_kappa(reference_labels, predicted_labels)
            continuous_pass = all(
                worst[metric]["minimum_spearman"] is not None
                and worst[metric]["minimum_spearman"] >= float(spearman_limits[metric])
                for metric in PRIMARY_CALIBRATION_METRICS
            ) and all(
                worst[metric]["maximum_mae"] is not None
                and worst[metric]["maximum_mae"] <= float(mae_limits[metric])
                for metric in CALIBRATION_METRICS
            )
            major_pass = major["cohens_kappa"] is not None and major["cohens_kappa"] >= kappa_limit
            alignments.append({
                "repetition": repetition,
                "passed": continuous_pass and major_pass,
                "continuous_pass": continuous_pass,
                "major_pass": major_pass,
                "reference_comparisons": comparisons,
                "worst_across_references": worst,
                "major": major,
            })
        passed = all(item["passed"] for item in alignments)
        worst_normalized_mae = max(
            float(alignment["worst_across_references"][metric]["maximum_mae"])
            / float(mae_limits[metric])
            for alignment in alignments
            for metric in PRIMARY_CALIBRATION_METRICS
        )
        minimum_kappa = min(float(alignment["major"]["cohens_kappa"]) for alignment in alignments)
        minimum_spearman = min(
            float(alignment["worst_across_references"][metric]["minimum_spearman"])
            for alignment in alignments
            for metric in PRIMARY_CALIBRATION_METRICS
            if alignment["worst_across_references"][metric]["minimum_spearman"] is not None
        )
        combinations.append({
            "candidate_ids": list(candidate_ids),
            "passed": passed,
            "selection_values": {
                "worst_normalized_primary_metric_mae": worst_normalized_mae,
                "minimum_major_cohens_kappa": minimum_kappa,
                "minimum_primary_metric_spearman": minimum_spearman,
            },
            "alignments": alignments,
        })
    passed_combinations = [item for item in combinations if item["passed"]]
    passed_combinations.sort(key=lambda item: (
        item["selection_values"]["worst_normalized_primary_metric_mae"],
        -item["selection_values"]["minimum_major_cohens_kappa"],
        -item["selection_values"]["minimum_primary_metric_spearman"],
        item["candidate_ids"],
    ))
    selected = passed_combinations[0]["candidate_ids"] if passed_combinations else None
    result.update({
        "status": "selected" if selected else "failed_no_combination_passed",
        "selected_ensemble": selected,
        "major_reference_unstable_cases": unstable_major_cases,
        "combinations": combinations,
    })
    if selected:
        input_paths = []
        for candidate_id in selected:
            for repetition in (1, 2):
                run_root = (
                    output
                    / "runs"
                    / "calibration"
                    / _safe_name(candidate_id)
                    / f"repeat-{repetition:02d}"
                )
                input_paths.extend((run_root / "judgments").glob("**/*.jsonl"))
        result["selected_input_artifact_tree"] = _tree_hash(input_paths, output)
        _write_json(output / "selected-ensemble.json", {
            "schema_version": "1.0",
            "frozen_at": _now(),
            "candidate_ids": selected,
            "calibration_analysis_sha256_pending": True,
            "input_artifact_tree": result["selected_input_artifact_tree"],
            "holdout_opened": False,
        })
    _write_json(output / "calibration-analysis.json", result)
    if selected:
        frozen = _read_json(output / "selected-ensemble.json")
        frozen["calibration_analysis_sha256"] = _sha256_file(output / "calibration-analysis.json")
        frozen.pop("calibration_analysis_sha256_pending", None)
        _write_json(output / "selected-ensemble.json", frozen)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=_repo_root())
    parser.add_argument("--source-repo", type=Path, default=_repo_root())
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--analysis-plan", type=Path, default=DEFAULT_ANALYSIS_PLAN)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-plan")
    snapshot = sub.add_parser("snapshot-models")
    snapshot.add_argument("--output", type=Path, required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--model-snapshot", type=Path, required=True)
    pilot = sub.add_parser("run-pilot")
    pilot.add_argument("--output", type=Path, required=True)
    pilot.add_argument("--candidate", action="append", default=[])
    pilot.add_argument("--confirm-use-balance-off", action="store_true")
    calibration = sub.add_parser("run-calibration")
    calibration.add_argument("--output", type=Path, required=True)
    calibration.add_argument("--candidate", required=True)
    calibration.add_argument("--repetition", type=int, required=True)
    calibration.add_argument("--workers", type=int, default=2)
    calibration.add_argument("--confirm-use-balance-off", action="store_true")
    reconcile = sub.add_parser("reconcile-calibration")
    reconcile.add_argument("--output", type=Path, required=True)
    reconcile.add_argument("--candidate", required=True)
    reconcile.add_argument("--repetition", type=int, required=True)
    analysis = sub.add_parser("analyze-calibration")
    analysis.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    repo = args.repo.resolve()
    source_repo = args.source_repo.resolve()
    plan_path = args.plan if args.plan.is_absolute() else repo / args.plan
    analysis_plan_path = (
        args.analysis_plan if args.analysis_plan.is_absolute() else repo / args.analysis_plan
    )
    if args.command == "validate-plan":
        result = validate_plan(_read_json(plan_path))
    elif args.command == "snapshot-models":
        result = snapshot_models(args.output.resolve())
    elif args.command == "prepare":
        result = prepare(
            repo,
            source_repo,
            plan_path,
            args.output.resolve(),
            args.model_snapshot.resolve(),
        )
    elif args.command == "run-pilot":
        result = run_pilot(
            repo,
            source_repo,
            plan_path,
            args.output.resolve(),
            args.candidate,
            args.confirm_use_balance_off,
        )
    elif args.command == "run-calibration":
        result = run_calibration(
            repo,
            source_repo,
            plan_path,
            args.output.resolve(),
            args.candidate,
            args.repetition,
            args.workers,
            args.confirm_use_balance_off,
        )
    elif args.command == "reconcile-calibration":
        result = reconcile_calibration(
            plan_path,
            args.output.resolve(),
            args.candidate,
            args.repetition,
        )
    else:
        result = analyze_calibration(
            repo,
            source_repo,
            plan_path,
            analysis_plan_path,
            args.output.resolve(),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
