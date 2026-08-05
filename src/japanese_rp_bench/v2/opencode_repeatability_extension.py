"""Run one-model extensions of the frozen OpenCode Challenge benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from japanese_rp_bench.v2.opencode_calibration import snapshot_models
from japanese_rp_bench.v2.opencode_judge_audit_v21 import resolve_v21_rubric
from japanese_rp_bench.v2.opencode_repeatability import (
    JUDGE_IDS,
    SCENARIO_IDS,
    _judgment_artifact_paths,
    _load_packs,
    _read_json,
    _read_jsonl,
    _resolved_specs,
    _runtime_config,
    _sha256_file,
    _sha256_json,
    _validate_registered_reasoning,
    _write_json,
    audit_run,
)
from japanese_rp_bench.v2.runner import run_benchmark
from japanese_rp_bench.v2.runner import _generate_judgments, _load_model_specs
from japanese_rp_bench.v2.schemas import Conversation, SchemaError


DEFAULT_PLAN = Path("configs/opencode_qwen38_repeatability_extension_2026-08-05.json")
TARGET_ID = "opencode-go-qwen3.8-max"
MODEL_ID = "qwen3.8-max"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_plan(path: Path) -> dict[str, Any]:
    plan = _read_json(path)
    if not isinstance(plan, dict):
        raise SchemaError("Extension plan must be a JSON object")
    return plan


def validate_plan(repo: Path, plan_path: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("schema_version") != "1.0":
        raise SchemaError("Unsupported repeatability extension schema")
    if plan.get("status") != "preregistered_before_qwen38_target_or_judge_api_calls":
        raise SchemaError("Extension must be frozen before paid API calls")
    parent = plan.get("parent_experiment")
    if not isinstance(parent, Mapping):
        raise SchemaError("Extension requires a parent experiment")
    for path_key, hash_key in (
        ("plan_path", "plan_sha256"),
        ("judge_v21_plan_path", "judge_v21_plan_sha256"),
    ):
        source = repo / str(parent[path_key])
        if _sha256_file(source) != parent[hash_key]:
            raise SchemaError(f"Frozen parent hash mismatch: {source}")

    scenarios = tuple(str(value) for value in plan.get("challenge_scenario_ids", []))
    if scenarios != SCENARIO_IDS:
        raise SchemaError("Extension must use the exact six Challenge scenarios")
    _load_packs(repo, plan)
    targets = plan.get("targets")
    if not isinstance(targets, list) or [value.get("id") for value in targets] != [TARGET_ID]:
        raise SchemaError("Extension must contain only Qwen3.8 Max")
    target = _validate_registered_reasoning(targets[0])
    if target.model != MODEL_ID or target.reasoning != "none":
        raise SchemaError("Qwen3.8 Max must use the frozen no-reasoning condition")
    judges = plan.get("judges")
    if not isinstance(judges, list) or tuple(str(value.get("id")) for value in judges) != JUDGE_IDS:
        raise SchemaError("Extension must retain the exact three fixed Judges")
    if any(_validate_registered_reasoning(value).reasoning != "low" for value in judges):
        raise SchemaError("All extension Judges must retain low reasoning")

    generation = plan.get("generation_policy") or {}
    if generation.get("use_balance") is not False or generation.get("automatic_balance_fallback") is not False:
        raise SchemaError("Extension must keep automatic balance fallback disabled")
    if int(generation.get("target_max_output_tokens", 0)) != 4096:
        raise SchemaError("Extension target output limit must remain 4096")
    judge_policy = plan.get("judge_policy") or {}
    if judge_policy.get("rubric_version") != "challenge-judge-audit-v2.1":
        raise SchemaError("Extension must use Judge rubric v2.1")
    if int(judge_policy.get("challenge_max_output_tokens", 0)) != 8192:
        raise SchemaError("Extension Judge output limit must remain 8192")

    design = plan.get("design") or {}
    expected = plan.get("expected_outputs") or {}
    if int(design.get("registered_blocks", 0)) != 10:
        raise SchemaError("Extension requires ten registered blocks")
    if (
        int(expected.get("registered_conversations", 0)) != 60
        or int(expected.get("registered_target_responses", 0)) != 270
        or int(expected.get("registered_judge_outputs", 0)) != 810
    ):
        raise SchemaError("Extension expected output counts have drifted")
    v21_path = repo / str(parent["judge_v21_plan_path"])
    rubric = resolve_v21_rubric(repo, _read_json(v21_path))
    if rubric.get("version") != judge_policy["rubric_version"]:
        raise SchemaError("Resolved Judge rubric version has drifted")
    return {
        "status": "valid",
        "experiment_id": plan["experiment_id"],
        "target": TARGET_ID,
        "blocks": 10,
        "conversations": 60,
        "target_responses": 270,
        "judge_outputs": 810,
        "rubric_version": rubric["version"],
        "plan_sha256": _sha256_file(plan_path),
    }


def build_schedule(repo: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    _, by_scenario = _load_packs(repo, plan)
    keys = [
        "|".join((TARGET_ID, by_scenario[scenario_id].id, scenario_id))
        for scenario_id in SCENARIO_IDS
    ]
    seed = int(plan["design"]["randomization"]["seed"])
    blocks = {
        f"block-{block:02d}": sorted(
            keys,
            key=lambda key: hashlib.sha256(f"{seed}|{block}|{key}".encode()).hexdigest(),
        )
        for block in range(11)
    }
    return {
        "schema_version": "1.0",
        "seed": seed,
        "algorithm": plan["design"]["randomization"]["algorithm"],
        "block_zero_is_protocol_pilot": True,
        "blocks": blocks,
        "schedule_sha256": _sha256_json(blocks),
    }


def prepare(repo: Path, plan_path: Path, output: Path, model_snapshot: Path) -> dict[str, Any]:
    plan = _load_plan(plan_path)
    validation = validate_plan(repo, plan_path, plan)
    snapshot = _read_json(model_snapshot)
    required = {MODEL_ID, *(str(value["model"]) for value in plan["judges"])}
    available = {str(value) for value in snapshot.get("model_ids", [])}
    missing = sorted(required - available)
    if missing:
        raise SchemaError(f"Extension models missing from current OpenCode snapshot: {missing}")
    schedule = build_schedule(repo, plan)
    fingerprint = _sha256_json({
        "plan_sha256": validation["plan_sha256"],
        "model_snapshot_sha256": _sha256_file(model_snapshot),
        "schedule_sha256": schedule["schedule_sha256"],
    })
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        manifest = _read_json(manifest_path)
        if manifest.get("experiment_fingerprint") != fingerprint:
            raise SchemaError("Existing extension output has a different fingerprint")
        return manifest
    if output.exists():
        unexpected = [
            path for path in output.iterdir() if path.resolve() != model_snapshot.resolve()
        ]
        if unexpected:
            raise SchemaError(f"Extension output must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "model-snapshot.json"
    if destination.resolve() != model_snapshot.resolve():
        shutil.copyfile(model_snapshot, destination)
    _write_json(output / "schedule.json", schedule)
    manifest = {
        "schema_version": "1.0",
        "experiment_id": plan["experiment_id"],
        "status": "prepared_pending_protocol_pilot",
        "prepared_at": _now(),
        "experiment_fingerprint": fingerprint,
        "plan": {"path": str(plan_path), "sha256": validation["plan_sha256"]},
        "model_snapshot": {"path": str(model_snapshot), "sha256": _sha256_file(model_snapshot)},
        "schedule_sha256": schedule["schedule_sha256"],
        "use_balance_confirmed_off": False,
        "blocks": {},
    }
    _write_json(manifest_path, manifest)
    return manifest


def _require_prepared(output: Path, plan_path: Path) -> dict[str, Any]:
    manifest = _read_json(output / "manifest.json")
    if manifest.get("plan", {}).get("sha256") != _sha256_file(plan_path):
        raise SchemaError("Prepared extension does not match the current plan")
    return manifest


def _runtime(
    repo: Path,
    plan: Mapping[str, Any],
    schedule: list[str],
) -> dict[str, Any]:
    config = _runtime_config(repo, plan, schedule, {"selected_reasoning": {}})
    parent = plan["parent_experiment"]
    v21_plan = _read_json(repo / str(parent["judge_v21_plan_path"]))
    config["evaluation"]["challenge_judge_rubric"] = resolve_v21_rubric(repo, v21_plan)
    config["notes"].append("Single-model Qwen3.8 Max extension; judgments use v2.1 directly.")
    return config


def _audit_extension(run_root: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    audit = audit_run(run_root, plan, {"selected_reasoning": {}})
    judgment_paths, _ = _judgment_artifact_paths(run_root)
    judgments = [item for path in judgment_paths for item in _read_jsonl(path)]
    rubric_versions = sorted({
        str(item.get("metadata", {}).get("rubric_version")) for item in judgments
    })
    audit["rubric_versions"] = rubric_versions
    audit["passed"] = audit["passed"] and rubric_versions == ["challenge-judge-audit-v2.1"]
    return audit


def _run(
    repo: Path,
    plan_path: Path,
    output: Path,
    block: int,
    workers: int,
    confirm_use_balance_off: bool,
) -> dict[str, Any]:
    if not confirm_use_balance_off:
        raise SchemaError("Paid extension calls require explicit confirmation that Use balance is OFF")
    plan = _load_plan(plan_path)
    validate_plan(repo, plan_path, plan)
    manifest = _require_prepared(output, plan_path)
    if block > 0:
        pilot = _read_json(output / "protocol-pilot" / "audit.json")
        if pilot.get("passed") is not True:
            raise SchemaError("A passing protocol pilot is required before registered blocks")
    block_id = f"block-{block:02d}"
    schedule = _read_json(output / "schedule.json")["blocks"][block_id]
    config = _runtime(repo, plan, schedule)
    config_path = output / "runtime-configs" / f"{block_id}.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    run_root = output / ("protocol-pilot/run" if block == 0 else f"blocks/{block_id}")
    try:
        run_benchmark(config_path, run_root, workers=workers)
    finally:
        if (run_root / "manifest.json").is_file():
            audit = _audit_extension(run_root, plan)
            audit_path = (
                output / "protocol-pilot" / "audit.json"
                if block == 0
                else run_root / "repeatability-audit.json"
            )
            _write_json(audit_path, audit)
            manifest = _read_json(output / "manifest.json")
            manifest["use_balance_confirmed_off"] = True
            if block == 0:
                manifest["protocol_pilot"] = {
                    "audit": str(audit_path),
                    "audit_sha256": _sha256_file(audit_path),
                }
                manifest["status"] = "protocol_pilot_complete" if audit["passed"] else "protocol_pilot_failed"
            else:
                manifest.setdefault("blocks", {})[block_id] = {
                    "status": "complete" if audit["passed"] else "incomplete",
                    "audit": str(audit_path),
                    "audit_sha256": _sha256_file(audit_path),
                }
                complete = sum(value["status"] == "complete" for value in manifest["blocks"].values())
                manifest["status"] = f"registered_blocks_{complete}_complete"
            _write_json(output / "manifest.json", manifest)
    audit = _read_json(
        output / "protocol-pilot" / "audit.json"
        if block == 0
        else run_root / "repeatability-audit.json"
    )
    if not audit["passed"]:
        raise SchemaError(f"Extension {block_id} is incomplete; resume with the same command")
    return audit


def verify(repo: Path, plan_path: Path, output: Path) -> dict[str, Any]:
    plan = _load_plan(plan_path)
    validate_plan(repo, plan_path, plan)
    manifest = _require_prepared(output, plan_path)
    audits = []
    for block in range(1, 11):
        path = output / "blocks" / f"block-{block:02d}" / "repeatability-audit.json"
        audits.append(_read_json(path) if path.is_file() else {"passed": False})
    result = {
        "schema_version": "1.0",
        "created_at": _now(),
        "passed": all(value.get("passed") is True for value in audits),
        "complete_blocks": sum(value.get("passed") is True for value in audits),
        "conversations": sum(int(value.get("conversations", 0)) for value in audits),
        "target_responses": sum(int(value.get("target_responses", 0)) for value in audits),
        "judge_outputs": sum(int(value.get("judge_outputs", 0)) for value in audits),
        "expected": plan["expected_outputs"],
    }
    result["passed"] = result["passed"] and (
        result["conversations"] == 60
        and result["target_responses"] == 270
        and result["judge_outputs"] == 810
    )
    _write_json(output / "completeness-report.json", result)
    manifest["completeness_report"] = {
        "path": str(output / "completeness-report.json"),
        "sha256": _sha256_file(output / "completeness-report.json"),
        "passed": result["passed"],
    }
    if result["passed"]:
        manifest["status"] = "registered_10_blocks_complete_pending_combined_analysis"
    _write_json(output / "manifest.json", manifest)
    return result


def run_single_judge(
    repo: Path,
    plan_path: Path,
    output: Path,
    block: int,
    judge_id: str,
    workers: int,
    confirm_use_balance_off: bool,
) -> dict[str, Any]:
    """Resume one fixed Judge independently without changing frozen conversations."""

    if not confirm_use_balance_off:
        raise SchemaError("Judge resume requires explicit confirmation that Use balance is OFF")
    plan = _load_plan(plan_path)
    validate_plan(repo, plan_path, plan)
    _require_prepared(output, plan_path)
    block_id = f"block-{block:02d}"
    config_path = output / "runtime-configs" / f"{block_id}.yaml"
    if not config_path.is_file():
        raise SchemaError(f"Runtime config is missing for {block_id}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    judges = {spec.id: spec for spec in _load_model_specs(config, "judges")}
    if judge_id not in judges:
        raise SchemaError(f"Unknown fixed Judge: {judge_id}")
    run_root = output / ("protocol-pilot/run" if block == 0 else f"blocks/{block_id}")
    run_manifest = _read_json(run_root / "manifest.json")
    run_fingerprint = str(run_manifest["run_fingerprint"])
    _, by_scenario = _load_packs(repo, plan)
    conversation_paths = sorted((run_root / "conversations" / TARGET_ID).glob("*.json"))
    if len(conversation_paths) != 6:
        raise SchemaError(f"Expected six frozen conversations for {block_id}")
    def judge_conversation(conversation_path: Path) -> None:
        conversation = Conversation.from_dict(_read_json(conversation_path))
        scenario = by_scenario[conversation.scenario_id].scenarios[conversation.scenario_id]
        role = by_scenario[conversation.scenario_id].roles[scenario.role_id]
        judgment_path = (
            run_root
            / "judgments"
            / TARGET_ID
            / conversation_path.with_suffix(".jsonl").name
        )
        _generate_judgments(
            judgment_path,
            role,
            scenario,
            conversation,
            [judges[judge_id]],
            int(config["evaluation"]["judge_max_output_tokens"]),
            run_fingerprint,
            audit_rubric=config["evaluation"]["challenge_judge_rubric"],
        )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(judge_conversation, path) for path in conversation_paths]
        for future in as_completed(futures):
            future.result()
    judgment_paths, _ = _judgment_artifact_paths(run_root)
    completed = sum(
        str(item.get("judge_id")) == judge_id
        for path in judgment_paths
        for item in _read_jsonl(path)
    )
    result = {
        "schema_version": "1.0",
        "updated_at": _now(),
        "block": block_id,
        "judge_id": judge_id,
        "completed": completed,
        "expected": 27,
        "passed": completed == 27,
        "rubric_version": "challenge-judge-audit-v2.1",
    }
    progress_path = output / ("protocol-pilot" if block == 0 else f"blocks/{block_id}") / f"{judge_id}-progress.json"
    _write_json(progress_path, result)
    if not result["passed"]:
        raise SchemaError(f"Judge {judge_id} is incomplete; resume with the same command")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=_repo_root())
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-plan")
    snapshot = sub.add_parser("snapshot-models")
    snapshot.add_argument("--output", type=Path, required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--model-snapshot", type=Path, required=True)
    pilot = sub.add_parser("run-pilot")
    pilot.add_argument("--output", type=Path, required=True)
    pilot.add_argument("--workers", type=int, default=1)
    pilot.add_argument("--confirm-use-balance-off", action="store_true")
    block = sub.add_parser("run-block")
    block.add_argument("--output", type=Path, required=True)
    block.add_argument("--block", type=int, required=True, choices=range(1, 11))
    block.add_argument("--workers", type=int, default=1)
    block.add_argument("--confirm-use-balance-off", action="store_true")
    check = sub.add_parser("verify")
    check.add_argument("--output", type=Path, required=True)
    judge = sub.add_parser("run-judge")
    judge.add_argument("--output", type=Path, required=True)
    judge.add_argument("--block", type=int, required=True, choices=range(0, 11))
    judge.add_argument("--judge", required=True, choices=JUDGE_IDS)
    judge.add_argument("--workers", type=int, default=2)
    judge.add_argument("--confirm-use-balance-off", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo = args.repo.resolve()
    plan_path = args.plan if args.plan.is_absolute() else repo / args.plan
    if args.command == "validate-plan":
        result = validate_plan(repo, plan_path, _load_plan(plan_path))
    elif args.command == "snapshot-models":
        result = snapshot_models(args.output.resolve())
    elif args.command == "prepare":
        result = prepare(repo, plan_path, args.output.resolve(), args.model_snapshot.resolve())
    elif args.command == "run-pilot":
        result = _run(repo, plan_path, args.output.resolve(), 0, args.workers, args.confirm_use_balance_off)
    elif args.command == "run-block":
        result = _run(repo, plan_path, args.output.resolve(), args.block, args.workers, args.confirm_use_balance_off)
    elif args.command == "run-judge":
        result = run_single_judge(
            repo,
            plan_path,
            args.output.resolve(),
            args.block,
            args.judge,
            args.workers,
            args.confirm_use_balance_off,
        )
    else:
        result = verify(repo, plan_path, args.output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
