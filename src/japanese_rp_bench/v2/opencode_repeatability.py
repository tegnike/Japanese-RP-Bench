"""Preregistered OpenCode Go Challenge repeatability runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from japanese_rp_bench.v2.providers import (
    GenerationOutcomeError,
    ModelSpec,
    ProviderError,
    RateLimitError,
    _reasoning_request_config,
    generate_text,
)
from japanese_rp_bench.v2.rolepacks import load_role_pack
from japanese_rp_bench.v2.runner import _target_system_prompt, run_benchmark
from japanese_rp_bench.v2.schemas import RolePack, SchemaError


DEFAULT_PLAN = Path("configs/opencode_challenge_repeatability_2026-07-27.json")
DEFAULT_PILOT_CLARIFICATION = Path(
    "configs/opencode_challenge_repeatability_pilot_clarification_2026-07-27.json"
)
MODEL_ENDPOINT = "https://opencode.ai/zen/go/v1/models"
TARGET_IDS = (
    "opencode-go-grok-4.5",
    "opencode-go-hy3",
    "opencode-go-qwen3.7-max",
    "opencode-go-kimi-k3",
    "opencode-go-deepseek-v4-pro",
    "opencode-go-minimax-m3",
    "opencode-go-glm-5.2",
    "opencode-go-mimo-v2.5-pro",
)
JUDGE_IDS = (
    "judge-opencode-grok-4.5",
    "judge-opencode-hy3",
    "judge-opencode-qwen3.7-plus",
)
SCENARIO_IDS = (
    "career_mentor_baseline",
    "wind_guide_baseline",
    "museum_curator_injection",
    "tea_room_twelve_turns",
    "nikechan_baseline",
    "nikechan_adversarial",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_plan(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    if not isinstance(value, dict):
        raise SchemaError("Repeatability plan must be a JSON object")
    validate_plan(value)
    return value


def _spec_with_reasoning(raw: Mapping[str, Any], reasoning: str) -> ModelSpec:
    value = dict(raw)
    value.pop("reasoning_selection", None)
    value.pop("reasoning_request", None)
    value["reasoning"] = reasoning
    return ModelSpec.from_dict(value)


def _validate_registered_reasoning(raw: Mapping[str, Any]) -> ModelSpec:
    spec = ModelSpec.from_dict(raw)
    if raw.get("reasoning_request") != _reasoning_request_config(spec):
        raise SchemaError(f"Reasoning request mismatch for {spec.id}")
    return spec


def validate_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("schema_version") != "1.0":
        raise SchemaError("Unsupported Challenge repeatability plan schema")
    scenarios = tuple(str(value) for value in plan.get("challenge_scenario_ids", []))
    if scenarios != SCENARIO_IDS:
        raise SchemaError("Challenge repeatability plan must freeze the exact six scenarios")
    targets = plan.get("targets")
    judges = plan.get("judges")
    if not isinstance(targets, list) or tuple(str(value.get("id")) for value in targets) != TARGET_IDS:
        raise SchemaError("Challenge repeatability plan must freeze the exact eight targets")
    if not isinstance(judges, list) or tuple(str(value.get("id")) for value in judges) != JUDGE_IDS:
        raise SchemaError("Challenge repeatability plan must freeze the exact three judges")

    pilot_targets = set(plan.get("target_reasoning_pilot", {}).get("models", []))
    if pilot_targets != {TARGET_IDS[0], TARGET_IDS[1]}:
        raise SchemaError("Only Grok 4.5 and Hy3 may use target-pilot reasoning selection")
    candidate_order = plan["target_reasoning_pilot"].get("candidate_order")
    if candidate_order != ["none", "low"]:
        raise SchemaError("Target reasoning pilot must try none before low")
    for raw in targets:
        target_id = str(raw["id"])
        if target_id in pilot_targets:
            if raw.get("reasoning_selection") != "target_reasoning_pilot":
                raise SchemaError(f"Missing target-pilot selection for {target_id}")
            for reasoning in candidate_order:
                _spec_with_reasoning(raw, reasoning)
        else:
            _validate_registered_reasoning(raw)
    for raw in judges:
        spec = _validate_registered_reasoning(raw)
        if spec.reasoning != "low":
            raise SchemaError(f"Judge reasoning must be low: {spec.id}")

    policy = plan.get("judge_policy") or {}
    if policy.get("blind_target_identity") is not True:
        raise SchemaError("Judge target identity must remain blind")
    if policy.get("same_exact_model_id_as_target_allowed") is not True:
        raise SchemaError("The registered design permits the same exact model as target and Judge")
    if int(policy.get("challenge_max_output_tokens", 0)) != 8192:
        raise SchemaError("Judge output limit must be 8192")
    if int(plan.get("generation_policy", {}).get("target_max_output_tokens", 0)) != 4096:
        raise SchemaError("Target output limit must be 4096")
    if plan.get("generation_policy", {}).get("use_balance") is not False:
        raise SchemaError("Use balance must remain disabled")

    design = plan.get("design") or {}
    blocks = int(design.get("registered_blocks", 0))
    expected = plan.get("expected_outputs") or {}
    conversations = blocks * len(targets) * len(scenarios)
    turns_per_block = 216
    judge_outputs = turns_per_block * len(judges) * blocks
    if conversations != 480 or int(expected.get("registered_conversations", -1)) != conversations:
        raise SchemaError("Registered conversation count must be 480")
    if int(expected.get("registered_target_responses", -1)) != turns_per_block * blocks:
        raise SchemaError("Registered target response count must be 2160")
    if int(expected.get("registered_judge_outputs", -1)) != judge_outputs:
        raise SchemaError("Registered Judge output count must be 6480")
    if int(expected.get("pairwise_model_comparisons_per_metric", -1)) != 28:
        raise SchemaError("Eight targets require 28 pairwise comparisons per metric")
    practical = plan.get("analysis", {}).get("minimum_practical_difference", {})
    if practical != {"continuous_score_points": 3.0, "rate_percentage_points": 10.0}:
        raise SchemaError("Registered practical-difference thresholds have drifted")
    analysis = plan.get("analysis") or {}
    if analysis.get("metrics") != [
        "role_fidelity_score",
        "conversation_quality_score",
        "persona_stability_score",
        "robustness_score",
        "recovery_score",
        "major_violation_rate",
        "major_free_rate",
        "challenge_rp_summary",
    ]:
        raise SchemaError("Registered analysis metrics have drifted")
    if analysis.get("robustness_and_recovery_scenarios") != [
        "wind_guide_baseline",
        "museum_curator_injection",
        "tea_room_twelve_turns",
        "nikechan_adversarial",
    ]:
        raise SchemaError("Registered Probe scenario scope has drifted")
    if analysis.get("bootstrap") != {
        "method": "paired_hierarchical_block_and_scenario_bootstrap",
        "replicates": 10000,
        "seed": 2026072702,
        "confidence_interval": 0.95,
    }:
        raise SchemaError("Registered bootstrap settings have drifted")
    multiple = analysis.get("multiple_comparisons") or {}
    if multiple != {
        "method": "holm",
        "family": "all_28_model_pairs_separately_within_each_metric",
        "alpha": 0.05,
    }:
        raise SchemaError("Registered Holm comparison family has drifted")
    judge_analysis = analysis.get("judge_analysis") or {}
    if judge_analysis != {
        "judge_specific_results": True,
        "within_conversation_judge_variance": True,
        "between_conversation_generation_variance": True,
        "leave_one_judge_out": True,
        "ensemble_mean_is_ground_truth": False,
    }:
        raise SchemaError("Registered Judge analysis has drifted")
    if analysis.get("rank_analysis", {}).get("ranking_keys") != [
        "major_free_rate_desc",
        "major_violation_rate_asc",
        "challenge_rp_summary_desc",
    ]:
        raise SchemaError("Registered rank analysis has drifted")
    extension = plan.get("sample_extension") or {}
    if int(extension.get("maximum_blocks", 0)) != 20 or extension.get(
        "extend_all_targets_and_scenarios_together"
    ) is not True:
        raise SchemaError("Sample extension must be all-target and capped at 20 blocks")
    return {
        "status": "valid",
        "experiment_id": plan["experiment_id"],
        "targets": len(targets),
        "judges": len(judges),
        "scenarios": len(scenarios),
        "registered_blocks": blocks,
        "registered_conversations": conversations,
        "registered_target_responses": turns_per_block * blocks,
        "registered_judge_outputs": judge_outputs,
        "pairwise_comparisons_per_metric": 28,
    }


def _load_packs(repo: Path, plan: Mapping[str, Any]) -> tuple[list[RolePack], dict[str, RolePack]]:
    packs = [load_role_pack(repo / str(path)) for path in plan["role_packs"]]
    by_scenario: dict[str, RolePack] = {}
    for pack in packs:
        for scenario_id in pack.scenarios:
            if scenario_id in by_scenario:
                raise SchemaError(f"Duplicate scenario across Role Packs: {scenario_id}")
            by_scenario[scenario_id] = pack
    if set(by_scenario) != set(SCENARIO_IDS):
        raise SchemaError("Current Role Packs do not match the six registered scenarios")
    return packs, by_scenario


def build_schedule(repo: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    _, by_scenario = _load_packs(repo, plan)
    keys = [
        "|".join((target_id, by_scenario[scenario_id].id, scenario_id))
        for target_id in TARGET_IDS
        for scenario_id in SCENARIO_IDS
    ]
    seed = int(plan["design"]["randomization"]["seed"])
    blocks = {}
    for block in range(0, int(plan["sample_extension"]["maximum_blocks"]) + 1):
        blocks[f"block-{block:02d}"] = sorted(
            keys,
            key=lambda key: hashlib.sha256(f"{seed}|{block}|{key}".encode()).hexdigest(),
        )
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
    snapshot = _read_json(model_snapshot)
    available = set(str(value) for value in snapshot.get("model_ids", []))
    required = {str(raw["model"]) for raw in [*plan["targets"], *plan["judges"]]}
    missing = sorted(required - available)
    if missing:
        raise SchemaError(f"Registered OpenCode Go models missing from snapshot: {missing}")
    schedule = build_schedule(repo, plan)
    fingerprint = _sha256_json({
        "experiment_id": plan["experiment_id"],
        "plan_sha256": _sha256_file(plan_path),
        "model_snapshot_sha256": _sha256_file(model_snapshot),
        "schedule_sha256": schedule["schedule_sha256"],
    })
    manifest_path = output / "manifest.json"
    if output.exists() and not manifest_path.is_file() and any(output.iterdir()):
        raise SchemaError(f"Output exists without repeatability manifest: {output}")
    if manifest_path.is_file():
        existing = _read_json(manifest_path)
        if existing.get("experiment_fingerprint") != fingerprint:
            raise SchemaError("Existing repeatability output has a different fingerprint")
        return existing
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(model_snapshot, output / "model-snapshot.json")
    _write_json(output / "schedule.json", schedule)
    manifest = {
        "schema_version": "1.0",
        "experiment_id": plan["experiment_id"],
        "status": "prepared_pending_target_reasoning_pilot",
        "prepared_at": _now(),
        "experiment_fingerprint": fingerprint,
        "plan": {"path": str(plan_path), "sha256": _sha256_file(plan_path)},
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
        raise SchemaError("Prepared output does not match the current preregistered plan")
    return manifest


def _is_reasoning_rejection(
    exc: Exception,
    reasoning: str,
    clarification: Mapping[str, Any],
) -> bool:
    message = str(exc).lower()
    setting_words = ("reasoning", "reasoning_effort", "effort", "thinking")
    rejection_words = ("invalid", "unsupported", "not support", "must be", "unknown")
    explicit = any(word in message for word in setting_words) and any(
        word in message for word in rejection_words
    )
    opaque_none_rejection = (
        reasoning == "none"
        and str(exc) == clarification.get("observed_error")
    )
    return explicit or opaque_none_rejection


def run_target_reasoning_pilot(
    repo: Path,
    plan_path: Path,
    output: Path,
    confirm_use_balance_off: bool,
) -> dict[str, Any]:
    if not confirm_use_balance_off:
        raise SchemaError("Target pilot requires explicit confirmation that Use balance is OFF")
    plan = _load_plan(plan_path)
    manifest = _require_prepared(output, plan_path)
    clarification_path = repo / DEFAULT_PILOT_CLARIFICATION
    clarification = _read_json(clarification_path)
    if clarification.get("parent_preregistered_plan", {}).get("sha256") != _sha256_file(
        plan_path
    ):
        raise SchemaError("Target-pilot clarification does not match the preregistered plan")
    report_path = output / "target-reasoning-pilot.json"
    if report_path.is_file():
        return _read_json(report_path)
    if not os.environ.get("OPENCODE_GO_API_KEY"):
        raise ProviderError("Required environment variable is not set: OPENCODE_GO_API_KEY")
    _, by_scenario = _load_packs(repo, plan)
    raw_by_id = {str(raw["id"]): raw for raw in plan["targets"]}
    attempts: list[dict[str, Any]] = []
    selected: dict[str, str] = {}
    for target_id in plan["target_reasoning_pilot"]["models"]:
        raw = raw_by_id[target_id]
        for reasoning in plan["target_reasoning_pilot"]["candidate_order"]:
            spec = _spec_with_reasoning(raw, reasoning)
            candidate_calls = []
            rejected = False
            for scenario_id in plan["target_reasoning_pilot"]["scenario_ids"]:
                pack = by_scenario[scenario_id]
                scenario = pack.scenarios[scenario_id]
                role = pack.roles[scenario.role_id]
                try:
                    result = generate_text(
                        spec,
                        _target_system_prompt(role),
                        [{"role": "user", "content": scenario.user_messages[0]}],
                        max_output_tokens=4096,
                    )
                except RateLimitError:
                    raise
                except GenerationOutcomeError as exc:
                    attempts.append({
                        "target_id": target_id,
                        "reasoning": reasoning,
                        "scenario_id": scenario_id,
                        "status": "terminal_generation_outcome",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "call": exc.result.to_dict(),
                    })
                    _write_json(report_path.with_suffix(".partial.json"), {"attempts": attempts})
                    raise SchemaError(f"Target reasoning pilot returned a terminal outcome: {target_id}") from exc
                except ProviderError as exc:
                    if _is_reasoning_rejection(exc, reasoning, clarification):
                        attempts.append({
                            "target_id": target_id,
                            "reasoning": reasoning,
                            "scenario_id": scenario_id,
                            "status": "reasoning_setting_rejected",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        })
                        rejected = True
                        break
                    raise
                call = result.to_dict()
                passed = (
                    bool(result.text.strip())
                    and result.termination_category == "completed"
                    and result.requested_max_output_tokens == 4096
                    and result.reasoning_config == _reasoning_request_config(spec)
                )
                record = {
                    "target_id": target_id,
                    "reasoning": reasoning,
                    "scenario_id": scenario_id,
                    "status": "passed" if passed else "failed",
                    "call": call,
                    "response_text": result.text,
                }
                attempts.append(record)
                candidate_calls.append(record)
                if not passed:
                    _write_json(report_path.with_suffix(".partial.json"), {"attempts": attempts})
                    raise SchemaError(f"Target reasoning pilot failed without a setting rejection: {target_id}")
            if rejected:
                continue
            if len(candidate_calls) == 2 and all(item["status"] == "passed" for item in candidate_calls):
                selected[target_id] = reasoning
                break
        if target_id not in selected:
            raise SchemaError(f"No registered reasoning candidate passed for {target_id}")
    report = {
        "schema_version": "1.0",
        "completed_at": _now(),
        "passed": True,
        "plan_sha256": _sha256_file(plan_path),
        "pilot_clarification": {
            "path": str(clarification_path),
            "sha256": _sha256_file(clarification_path),
        },
        "target_max_output_tokens": 4096,
        "selected_reasoning": selected,
        "attempts": attempts,
    }
    _write_json(report_path, report)
    report_path.with_suffix(".partial.json").unlink(missing_ok=True)
    manifest["status"] = "target_reasoning_pilot_complete"
    manifest["use_balance_confirmed_off"] = True
    manifest["target_reasoning_pilot"] = {
        "path": str(report_path),
        "sha256": _sha256_file(report_path),
        "selected_reasoning": selected,
    }
    _write_json(output / "manifest.json", manifest)
    return report


def _resolved_specs(plan: Mapping[str, Any], pilot: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = pilot.get("selected_reasoning") or {}
    targets = []
    for raw in plan["targets"]:
        value = dict(raw)
        selection = value.pop("reasoning_selection", None)
        expected_request = value.pop("reasoning_request", None)
        if selection:
            reasoning = str(selected.get(value["id"], ""))
            if reasoning not in plan["target_reasoning_pilot"]["candidate_order"]:
                raise SchemaError(f"Missing pilot-selected reasoning for {value['id']}")
            value["reasoning"] = reasoning
        spec = ModelSpec.from_dict(value)
        if expected_request is not None and expected_request != _reasoning_request_config(spec):
            raise SchemaError(f"Resolved target reasoning mismatch: {spec.id}")
        targets.append(value)
    judge_values = []
    for raw in plan["judges"]:
        value = dict(raw)
        expected_request = value.pop("reasoning_request")
        spec = ModelSpec.from_dict(value)
        if expected_request != _reasoning_request_config(spec):
            raise SchemaError(f"Resolved Judge reasoning mismatch: {spec.id}")
        judge_values.append(value)
    return targets, judge_values


def _runtime_config(
    repo: Path,
    plan: Mapping[str, Any],
    schedule: Sequence[str],
    pilot: Mapping[str, Any],
) -> dict[str, Any]:
    targets, judges = _resolved_specs(plan, pilot)
    return {
        "schema_version": "2.0",
        "base_track": {"enabled": False},
        "role_packs": [str(repo / str(path)) for path in plan["role_packs"]],
        "evaluation": {
            "deterministic_checks": True,
            "judge_ensemble": {
                "minimum_judges": 3,
                "blind_target_identity": True,
                "disagreement_policy": "report",
            },
            "report": {"weighted_overall_score": False, "major_violation_gate": True},
            "judge_max_output_tokens": 8192,
            "base_judge_max_output_tokens": 8192,
        },
        "batch": {"poll_interval_seconds": 30, "max_attempts": 3},
        "generation": {
            "target_max_output_tokens": 4096,
            "user_max_output_tokens": 2048,
            "sync_rate_limit_max_attempts": int(plan["generation_policy"]["sync_rate_limit_max_attempts"]),
            "sync_rate_limit_backoff_seconds": 30,
        },
        "execution": {"job_order": list(schedule)},
        "models": {"targets": targets, "judges": judges},
        "notes": [
            "Generated from the preregistered Challenge repeatability plan.",
            "Use balance must remain OFF; no paid-provider fallback is configured.",
        ],
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _judgment_artifact_paths(run_root: Path) -> tuple[list[Path], list[Path]]:
    paths = sorted((run_root / "judgments").glob("**/*.jsonl"))
    raw_attempt_paths = [path for path in paths if path.name.endswith(".raw-attempts.jsonl")]
    judgment_paths = [path for path in paths if not path.name.endswith(".raw-attempts.jsonl")]
    return judgment_paths, raw_attempt_paths


def audit_run(run_root: Path, plan: Mapping[str, Any], pilot: Mapping[str, Any]) -> dict[str, Any]:
    manifest = _read_json(run_root / "manifest.json")
    conversation_paths = sorted((run_root / "conversations").glob("**/*.json"))
    judgment_paths, raw_attempt_paths = _judgment_artifact_paths(run_root)
    report_paths = sorted((run_root / "reports").glob("**/*.json"))
    target_responses = 0
    target_calls = []
    for path in conversation_paths:
        value = _read_json(path)
        target_responses += len(value.get("turns", []))
        target_calls.extend(
            call for call in value.get("metadata", {}).get("generation_calls", [])
            if call.get("purpose") == "target"
        )
    judgments = [item for path in judgment_paths for item in _read_jsonl(path)]
    raw_attempts = [item for path in raw_attempt_paths for item in _read_jsonl(path)]
    judge_calls = [
        call
        for item in judgments
        for call in item.get("metadata", {}).get("calls", [])
    ]
    expected_reasoning = {
        spec.id: _reasoning_request_config(spec)
        for spec in [
            ModelSpec.from_dict(value)
            for values in _resolved_specs(plan, pilot)
            for value in values
        ]
    }
    call_problems = []
    for call in [*target_calls, *judge_calls]:
        model_id = str(call.get("requested_model", ""))
        expected_limit = 4096 if model_id in TARGET_IDS else 8192
        if (
            call.get("termination_category") != "completed"
            or int(call.get("requested_max_output_tokens", 0)) != expected_limit
            or call.get("reasoning_config") != expected_reasoning.get(model_id)
        ):
            call_problems.append({
                "requested_model": model_id,
                "termination_category": call.get("termination_category"),
                "requested_max_output_tokens": call.get("requested_max_output_tokens"),
                "reasoning_config": call.get("reasoning_config"),
            })
    passed = (
        manifest.get("status") == "complete"
        and len(conversation_paths) == 48
        and target_responses == 216
        and len(target_calls) == 216
        and len(judgments) == 648
        and len(report_paths) == 48
        and not call_problems
    )
    return {
        "schema_version": "1.0",
        "created_at": _now(),
        "passed": passed,
        "manifest_status": manifest.get("status"),
        "conversations": len(conversation_paths),
        "target_responses": target_responses,
        "target_calls": len(target_calls),
        "judge_outputs": len(judgments),
        "judge_call_attempts": len(judge_calls) + len(raw_attempts),
        "judge_raw_attempts": len(raw_attempts),
        "reports": len(report_paths),
        "call_problems": call_problems,
    }


def run_protocol_pilot(
    repo: Path,
    plan_path: Path,
    output: Path,
    workers: int,
    confirm_use_balance_off: bool,
) -> dict[str, Any]:
    if not confirm_use_balance_off:
        raise SchemaError("Protocol pilot requires explicit confirmation that Use balance is OFF")
    plan = _load_plan(plan_path)
    manifest = _require_prepared(output, plan_path)
    pilot = _read_json(output / "target-reasoning-pilot.json")
    schedule = _read_json(output / "schedule.json")["blocks"]["block-00"]
    config = _runtime_config(repo, plan, schedule, pilot)
    config_path = output / "runtime-configs" / "protocol-pilot.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    run_root = output / "protocol-pilot" / "run"
    run_benchmark(config_path, run_root, workers=workers)
    audit = audit_run(run_root, plan, pilot)
    _write_json(output / "protocol-pilot" / "audit.json", audit)
    if not audit["passed"]:
        raise SchemaError("Protocol pilot failed; inspect protocol-pilot/audit.json")
    manifest["status"] = "protocol_pilot_complete"
    manifest["use_balance_confirmed_off"] = True
    manifest["protocol_pilot"] = {
        "run": str(run_root),
        "audit": str(output / "protocol-pilot" / "audit.json"),
        "audit_sha256": _sha256_file(output / "protocol-pilot" / "audit.json"),
    }
    _write_json(output / "manifest.json", manifest)
    return audit


def run_block(
    repo: Path,
    plan_path: Path,
    output: Path,
    block: int,
    workers: int,
    confirm_use_balance_off: bool,
) -> dict[str, Any]:
    if not confirm_use_balance_off:
        raise SchemaError("Registered blocks require explicit confirmation that Use balance is OFF")
    plan = _load_plan(plan_path)
    manifest = _require_prepared(output, plan_path)
    protocol_audit = _read_json(output / "protocol-pilot" / "audit.json")
    if protocol_audit.get("passed") is not True:
        raise SchemaError("A passing protocol pilot is required before registered blocks")
    maximum = int(plan["sample_extension"]["maximum_blocks"])
    if block < 1 or block > maximum:
        raise SchemaError(f"Block must be between 1 and {maximum}")
    if block > int(plan["design"]["registered_blocks"]):
        decision = output / "analysis-10-blocks" / "sample-extension-decision.json"
        if not decision.is_file() or _read_json(decision).get("extend") is not True:
            raise SchemaError("Blocks 11-20 require a preregistered positive extension decision")
    pilot = _read_json(output / "target-reasoning-pilot.json")
    schedule = _read_json(output / "schedule.json")["blocks"][f"block-{block:02d}"]
    config = _runtime_config(repo, plan, schedule, pilot)
    config_path = output / "runtime-configs" / f"block-{block:02d}.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    run_root = output / "blocks" / f"block-{block:02d}"
    try:
        run_benchmark(config_path, run_root, workers=workers)
    finally:
        if (run_root / "manifest.json").is_file():
            audit = audit_run(run_root, plan, pilot)
            _write_json(run_root / "repeatability-audit.json", audit)
            manifest = _read_json(output / "manifest.json")
            manifest.setdefault("blocks", {})[f"block-{block:02d}"] = {
                "status": "complete" if audit["passed"] else "incomplete",
                "audit": str(run_root / "repeatability-audit.json"),
                "audit_sha256": _sha256_file(run_root / "repeatability-audit.json"),
            }
            complete = sum(item["status"] == "complete" for item in manifest["blocks"].values())
            manifest["status"] = f"registered_blocks_{complete}_complete"
            manifest["use_balance_confirmed_off"] = True
            _write_json(output / "manifest.json", manifest)
    audit = _read_json(run_root / "repeatability-audit.json")
    if not audit["passed"]:
        raise SchemaError(f"Block {block} is incomplete; resume it with the same command")
    return audit


def verify(output: Path, plan_path: Path) -> dict[str, Any]:
    plan = _load_plan(plan_path)
    manifest = _require_prepared(output, plan_path)
    audits = []
    for block in range(1, int(plan["design"]["registered_blocks"]) + 1):
        path = output / "blocks" / f"block-{block:02d}" / "repeatability-audit.json"
        audits.append(_read_json(path) if path.is_file() else {"passed": False})
    result = {
        "schema_version": "1.0",
        "created_at": _now(),
        "passed": all(item.get("passed") is True for item in audits),
        "complete_blocks": sum(item.get("passed") is True for item in audits),
        "conversations": sum(int(item.get("conversations", 0)) for item in audits),
        "target_responses": sum(int(item.get("target_responses", 0)) for item in audits),
        "judge_outputs": sum(int(item.get("judge_outputs", 0)) for item in audits),
        "expected": plan["expected_outputs"],
    }
    _write_json(output / "completeness-report.json", result)
    manifest["completeness_report"] = {
        "path": str(output / "completeness-report.json"),
        "sha256": _sha256_file(output / "completeness-report.json"),
        "passed": result["passed"],
    }
    if result["passed"]:
        manifest["status"] = "registered_10_blocks_complete_pending_analysis"
    _write_json(output / "manifest.json", manifest)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=_repo_root())
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-plan")
    prep = sub.add_parser("prepare")
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--model-snapshot", type=Path, required=True)
    target_pilot = sub.add_parser("run-target-pilot")
    target_pilot.add_argument("--output", type=Path, required=True)
    target_pilot.add_argument("--confirm-use-balance-off", action="store_true")
    protocol = sub.add_parser("run-protocol-pilot")
    protocol.add_argument("--output", type=Path, required=True)
    protocol.add_argument("--workers", type=int, default=4)
    protocol.add_argument("--confirm-use-balance-off", action="store_true")
    block = sub.add_parser("run-block")
    block.add_argument("--output", type=Path, required=True)
    block.add_argument("--block", type=int, required=True)
    block.add_argument("--workers", type=int, default=4)
    block.add_argument("--confirm-use-balance-off", action="store_true")
    check = sub.add_parser("verify")
    check.add_argument("--output", type=Path, required=True)
    analysis = sub.add_parser("analyze")
    analysis.add_argument("--output", type=Path, required=True)
    analysis.add_argument("--analysis-output", type=Path)
    analysis.add_argument(
        "--document",
        type=Path,
        default=Path("docs/opencode-challenge-repeatability-results-2026-07-28.md"),
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo = args.repo.resolve()
    plan_path = args.plan if args.plan.is_absolute() else repo / args.plan
    if args.command == "validate-plan":
        result = validate_plan(_read_json(plan_path))
    elif args.command == "prepare":
        result = prepare(repo, plan_path, args.output.resolve(), args.model_snapshot.resolve())
    elif args.command == "run-target-pilot":
        result = run_target_reasoning_pilot(
            repo, plan_path, args.output.resolve(), args.confirm_use_balance_off
        )
    elif args.command == "run-protocol-pilot":
        result = run_protocol_pilot(
            repo, plan_path, args.output.resolve(), args.workers, args.confirm_use_balance_off
        )
    elif args.command == "run-block":
        result = run_block(
            repo,
            plan_path,
            args.output.resolve(),
            args.block,
            args.workers,
            args.confirm_use_balance_off,
        )
    elif args.command == "analyze":
        from japanese_rp_bench.v2.opencode_repeatability_analysis import analyze

        output = args.output.resolve()
        analysis_output = (
            args.analysis_output.resolve()
            if args.analysis_output is not None
            else output / "analysis-10-blocks"
        )
        document = args.document if args.document.is_absolute() else repo / args.document
        result = analyze(repo, plan_path, output, analysis_output, document)
    else:
        result = verify(args.output.resolve(), plan_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
