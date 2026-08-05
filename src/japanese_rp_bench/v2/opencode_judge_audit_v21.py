"""Prepare the frozen Judge audit v2.1 and full-rejudge requests offline."""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from japanese_rp_bench.v2.judge import build_judge_request
from japanese_rp_bench.v2.opencode_repeatability import (
    JUDGE_IDS,
    _load_packs,
    _read_json,
    _read_jsonl,
    _sha256_file,
)
from japanese_rp_bench.v2.schemas import Conversation, DialogueTurn, SchemaError


DEFAULT_PLAN = Path("configs/opencode_judge_audit_v21_2026-07-29.json")
DEFAULT_OUTPUT = Path(
    "tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v21-offline"
)
CLASSIFICATIONS = {
    "systematic_rubric_gap",
    "judge_specific_residual",
    "rule_or_language_ambiguity",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )


def _merge_guidance(
    base: dict[str, Any],
    overrides: Mapping[str, Any],
) -> None:
    for key, value in overrides.items():
        if not isinstance(value, Mapping):
            raise SchemaError(f"v2.1 guidance override must be an object: {key}")
        existing = base.setdefault(str(key), {})
        if not isinstance(existing, dict):
            raise SchemaError(f"v2 base guidance must be an object: {key}")
        existing.update(dict(value))


def resolve_v21_rubric(repo: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    rubric_plan = plan.get("judge_rubric")
    if not isinstance(rubric_plan, Mapping):
        raise SchemaError("v2.1 plan requires judge_rubric")
    base_path = repo / str(rubric_plan["base_plan_path"])
    if _sha256_file(base_path) != rubric_plan.get("base_plan_sha256"):
        raise SchemaError("v2.1 base rubric plan hash mismatch")
    base_plan = _read_json(base_path)
    rubric = copy.deepcopy(base_plan["judge_rubric"])
    rubric["version"] = str(rubric_plan["version"])
    additions = rubric_plan.get("evaluation_contract_additions")
    if not isinstance(additions, Mapping) or len(additions) != 5:
        raise SchemaError("v2.1 requires five frozen evaluation-contract additions")
    rubric["evaluation_contract"].update(dict(additions))
    _merge_guidance(
        rubric["rule_guidance"],
        rubric_plan.get("rule_guidance_overrides", {}),
    )
    _merge_guidance(
        rubric["probe_guidance"],
        rubric_plan.get("probe_guidance_overrides", {}),
    )
    return rubric


def validate_v21_contrast_suite(suite: Mapping[str, Any]) -> dict[str, Any]:
    if suite.get("schema_version") != "1.0":
        raise SchemaError("v2.1 contrast suite schema_version must be 1.0")
    if suite.get("status") != "offline_expected_directions_frozen_before_any_v21_judge_api_calls":
        raise SchemaError("v2.1 contrast directions must be frozen before API calls")
    pairs = suite.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != 9:
        raise SchemaError("v2.1 contrast suite must contain nine pairs")
    ids: list[str] = []
    cases = 0
    for pair in pairs:
        if not isinstance(pair, Mapping):
            raise SchemaError("v2.1 contrast pair must be an object")
        ids.append(str(pair.get("id", "")))
        pair_type = pair.get("pair_type")
        if pair_type == "direction":
            values = (pair.get("fail_case"), pair.get("pass_case"))
            expected = ("fail", "pass")
        elif pair_type == "invariance":
            values = (pair.get("case_a"), pair.get("case_b"))
            expected = ("pass", "pass")
        else:
            raise SchemaError(f"Unknown v2.1 contrast pair type: {pair_type}")
        if any(not isinstance(value, Mapping) for value in values):
            raise SchemaError(f"Invalid v2.1 contrast cases: {pair.get('id')}")
        if tuple(value.get("expected_verdict") for value in values) != expected:
            raise SchemaError(f"v2.1 contrast direction drifted: {pair.get('id')}")
        cases += 2
    if not all(ids) or len(ids) != len(set(ids)):
        raise SchemaError("v2.1 contrast IDs must be unique and nonempty")
    return {"pairs": len(pairs), "cases": cases, "judge_tasks": cases * len(JUDGE_IDS)}


def validate_v21_plan(repo: Path, plan_path: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("schema_version") != "2.1":
        raise SchemaError("Judge audit v2.1 plan schema_version must be 2.1")
    if plan.get("status") != "preregistered_before_any_v21_judge_api_calls":
        raise SchemaError("Judge audit v2.1 plan must be frozen before v2.1 API calls")
    source = plan.get("source")
    v2_source = plan.get("v2_audit_source")
    if not isinstance(source, Mapping) or not isinstance(v2_source, Mapping):
        raise SchemaError("Judge audit v2.1 source sections must be objects")
    checks = (
        (source["challenge_plan_path"], source["challenge_plan_sha256"]),
        (source["completeness_report_path"], source["completeness_report_sha256"]),
        (v2_source["plan_path"], v2_source["plan_sha256"]),
        (v2_source["summary_path"], v2_source["summary_sha256"]),
        (v2_source["cell_comparisons_path"], v2_source["cell_comparisons_sha256"]),
    )
    for relative, expected in checks:
        if _sha256_file(repo / str(relative)) != expected:
            raise SchemaError(f"Judge audit v2.1 frozen source hash mismatch: {relative}")
    if source.get("mutate_or_regenerate_source") is not False:
        raise SchemaError("Judge audit v2.1 must not mutate frozen source")
    if (int(source.get("conversations", -1)), int(source.get("target_responses", -1))) != (480, 2160):
        raise SchemaError("Judge audit v2.1 source counts must remain 480/2160")
    rows = plan.get("remaining_15_classification")
    if not isinstance(rows, list) or len(rows) != 15:
        raise SchemaError("Judge audit v2.1 requires exactly 15 classified residual cells")
    ids = [str(row.get("audit_id", "")) for row in rows if isinstance(row, Mapping)]
    if len(ids) != 15 or len(ids) != len(set(ids)) or not all(ids):
        raise SchemaError("Judge audit v2.1 residual audit IDs must be unique")
    classes = Counter(str(row.get("classification")) for row in rows)
    expected_classes = {str(key): int(value) for key, value in plan["classification_counts"].items()}
    if set(classes) != CLASSIFICATIONS or dict(classes) != expected_classes:
        raise SchemaError("Judge audit v2.1 classification counts have drifted")
    comparisons = _read_jsonl(repo / str(v2_source["cell_comparisons_path"]))
    remaining = {str(row["audit_id"]) for row in comparisons if row.get("new_pass_fail_disagreement")}
    if remaining != set(ids):
        raise SchemaError("Judge audit v2.1 classifications do not match the frozen 15 cells")
    suite_ref = plan.get("contrast_suite")
    if not isinstance(suite_ref, Mapping):
        raise SchemaError("Judge audit v2.1 contrast_suite must be an object")
    suite_path = repo / str(suite_ref["path"])
    if _sha256_file(suite_path) != suite_ref.get("sha256"):
        raise SchemaError("Judge audit v2.1 contrast suite hash mismatch")
    suite_summary = validate_v21_contrast_suite(_read_json(suite_path))
    if suite_summary != {
        "pairs": int(suite_ref["pairs"]),
        "cases": int(suite_ref["cases"]),
        "judge_tasks": int(suite_ref["judge_tasks"]),
    }:
        raise SchemaError("Judge audit v2.1 contrast suite counts have drifted")
    full = plan.get("full_rejudge")
    if not isinstance(full, Mapping) or full.get("authorized_by_user") is not True:
        raise SchemaError("Judge audit v2.1 full rejudge requires recorded user authorization")
    if int(full.get("expected_final_judge_outputs", -1)) != 6480:
        raise SchemaError("Judge audit v2.1 full rejudge must contain 6480 Judge tasks")
    if full.get("provider_scope") != "opencode_go_only" or full.get("paid_provider_fallback") is not False:
        raise SchemaError("Judge audit v2.1 permits only OpenCode Go")
    publication = plan.get("publication")
    if not isinstance(publication, Mapping) or any(
        publication.get(key) is not False
        for key in ("official_leaderboard_changes", "repository_readme_changes", "dashboard_changes")
    ):
        raise SchemaError("Judge audit v2.1 cannot change published results")
    rubric = resolve_v21_rubric(repo, plan)
    return {
        "audit_id": str(plan["audit_id"]),
        "classified_cells": 15,
        "classification_counts": dict(classes),
        "rubric_version": rubric["version"],
        "contrast": suite_summary,
        "full_judge_tasks": 6480,
        "api_calls_started": False,
    }


def _last_call(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    calls = raw.get("metadata", {}).get("calls", [])
    if not isinstance(calls, list) or not calls or not isinstance(calls[-1], Mapping):
        return {}
    return calls[-1]


def build_v21_offline(repo: Path, plan_path: Path, output: Path) -> dict[str, Any]:
    plan = _read_json(plan_path)
    validation = validate_v21_plan(repo, plan_path, plan)
    if output.exists() and any(output.iterdir()):
        raise SchemaError(f"Judge audit v2.1 output must be a new empty directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    rubric = resolve_v21_rubric(repo, plan)
    source_root = repo / str(plan["source"]["artifact_root"])
    completeness = _read_json(repo / str(plan["source"]["completeness_report_path"]))
    if completeness.get("passed") is not True:
        raise SchemaError("Judge audit v2.1 requires the passing frozen completeness report")
    root_manifest = _read_json(source_root / "manifest.json")
    if root_manifest.get("experiment_fingerprint") != plan["source"]["experiment_fingerprint"]:
        raise SchemaError("Judge audit v2.1 experiment fingerprint mismatch")
    challenge_plan = _read_json(repo / str(plan["source"]["challenge_plan_path"]))
    _, by_scenario = _load_packs(repo, challenge_plan)
    judge_specs = {str(item["id"]): item for item in challenge_plan["judges"]}
    full_requests: list[Mapping[str, Any]] = []
    estimated_input_tokens = 0
    historical_output_tokens = 0
    estimated_cost = 0.0
    conversation_count = 0
    old_judgment_count = 0
    for block in range(1, 11):
        block_id = f"block-{block:02d}"
        run_root = source_root / "blocks" / block_id
        conversation_paths = sorted((run_root / "conversations").glob("**/*.json"))
        if len(conversation_paths) != 48:
            raise SchemaError(f"Unexpected frozen conversation count: {block_id}")
        for conversation_path in conversation_paths:
            relative = conversation_path.relative_to(run_root / "conversations")
            judgment_path = run_root / "judgments" / relative.with_suffix(".jsonl")
            conversation = Conversation.from_dict(_read_json(conversation_path))
            raw_old = _read_jsonl(judgment_path)
            old_judgment_count += len(raw_old)
            by_judge_turn = {
                (str(item["judge_id"]), int(item["turn"])): item for item in raw_old
            }
            role_pack = by_scenario[conversation.scenario_id]
            scenario = role_pack.scenarios[conversation.scenario_id]
            role = role_pack.roles[conversation.role_id]
            conversation_count += 1
            for turn in conversation.turns:
                request = build_judge_request(
                    role,
                    scenario,
                    conversation,
                    turn.index,
                    audit_rubric=rubric,
                )
                if conversation.target_model in request.system_prompt or conversation.target_model in request.user_prompt:
                    raise SchemaError("v2.1 Judge prompt exposes the target model identity")
                request_key = (
                    f"{block_id}|{conversation.target_model}|{role_pack.id}|"
                    f"{conversation.scenario_id}|turn-{turn.index}"
                )
                full_requests.append({
                    "request_key": request_key,
                    "request": request.to_dict(),
                    "source_conversation": str(conversation_path.relative_to(repo)),
                    "source_conversation_sha256": _sha256_file(conversation_path),
                    "target_identity_present_in_judge_prompts": False,
                    "api_calls_started": False,
                })
                v1 = build_judge_request(role, scenario, conversation, turn.index)
                ratio = (
                    (len(request.system_prompt) + len(request.user_prompt))
                    / (len(v1.system_prompt) + len(v1.user_prompt))
                )
                for judge_id in JUDGE_IDS:
                    call = _last_call(by_judge_turn[(judge_id, turn.index)])
                    projected_input = round(int(call.get("input_tokens", 0)) * ratio)
                    old_output = int(call.get("output_tokens", 0))
                    estimated_input_tokens += projected_input
                    historical_output_tokens += old_output
                    spec = judge_specs[judge_id]
                    estimated_cost += (
                        projected_input * float(spec["input_price_per_million"])
                        + old_output * float(spec["output_price_per_million"])
                    ) / 1_000_000
    if (conversation_count, len(full_requests), old_judgment_count) != (480, 2160, 6480):
        raise SchemaError(
            "Judge audit v2.1 frozen full request counts drifted: "
            f"{conversation_count}/{len(full_requests)}/{old_judgment_count}"
        )

    suite = _read_json(repo / str(plan["contrast_suite"]["path"]))
    probe_index: dict[str, tuple[Any, Any, Any]] = {}
    for role_pack in {item.id: item for item in by_scenario.values()}.values():
        for scenario in role_pack.scenarios.values():
            for probe in scenario.probes:
                probe_index[probe.id] = (role_pack, scenario, probe)
    contrast_requests: list[Mapping[str, Any]] = []
    for pair in suite["pairs"]:
        role_pack, scenario, probe = probe_index[str(pair["probe_id"])]
        role = role_pack.roles[scenario.role_id]
        case_names = (
            ("fail_case", "pass_case")
            if pair["pair_type"] == "direction"
            else ("case_a", "case_b")
        )
        for case_name in case_names:
            case = pair[case_name]
            turns = tuple(
                DialogueTurn(
                    index=index,
                    user=user,
                    assistant=(
                        str(case["assistant"])
                        if index == probe.turn
                        else "（対照例ではこのターンの応答を省略）"
                    ),
                )
                for index, user in enumerate(scenario.user_messages[:probe.turn], start=1)
            )
            conversation = Conversation(
                role_id=role.id,
                scenario_id=scenario.id,
                target_model="blind-v21-contrast-case",
                turns=turns,
                metadata={"contrast_pair_id": pair["id"], "case": case_name},
            )
            request = build_judge_request(
                role,
                scenario,
                conversation,
                probe.turn,
                audit_rubric=rubric,
            )
            contrast_requests.append({
                "request_key": f"contrast-v21|{pair['id']}|{case_name}",
                "pair_type": pair["pair_type"],
                "rule_id": pair["rule_id"],
                "probe_id": pair["probe_id"],
                "expected_verdict": case["expected_verdict"],
                "expected_quality_effect": case.get("expected_quality_effect"),
                "request": request.to_dict(),
                "api_calls_started": False,
            })
    if len(contrast_requests) != 18:
        raise SchemaError("Judge audit v2.1 contrast request count must be 18")

    comparison_by_id = {
        str(item["audit_id"]): item
        for item in _read_jsonl(repo / str(plan["v2_audit_source"]["cell_comparisons_path"]))
    }
    classified = []
    for annotation in plan["remaining_15_classification"]:
        row = dict(comparison_by_id[str(annotation["audit_id"])])
        row["v21_review"] = dict(annotation)
        classified.append(row)

    full_path = output / "full-judge-requests.jsonl"
    contrast_path = output / "contrast-pair-requests.jsonl"
    classified_path = output / "remaining-15-classification.jsonl"
    summary_path = output / "summary.json"
    _write_jsonl(full_path, full_requests)
    _write_jsonl(contrast_path, contrast_requests)
    _write_jsonl(classified_path, classified)
    summary = {
        "schema_version": "2.1",
        "created_at": _now(),
        "audit_id": plan["audit_id"],
        "rubric_version": rubric["version"],
        "api_calls_started": False,
        "classified_remaining_cells": 15,
        "classification_counts": plan["classification_counts"],
        "contrast_pairs": 9,
        "contrast_cases": 18,
        "contrast_judge_tasks": 54,
        "frozen_conversations": conversation_count,
        "frozen_target_responses": len(full_requests),
        "future_full_judge_tasks": len(full_requests) * len(JUDGE_IDS),
        "estimated_v21_input_tokens_from_v1_prompt_character_ratio": estimated_input_tokens,
        "historical_visible_output_tokens": historical_output_tokens,
        "estimated_list_cost_usd_using_projected_input_and_historical_output": round(estimated_cost, 6),
        "estimate_is_not_an_api_quote": True,
        "target_conversations_regenerated": False,
        "source_artifacts_mutated": False,
    }
    _write_json(summary_path, summary)
    report = f"""# OpenCode Challenge Judge監査 v2.1 オフライン固定\n\n- 残存15件: 系統的ルーブリック不足6、Judge固有差6、曖昧3\n- v2.1変更理由: 系統的ルーブリック不足6件だけ\n- contrast: 9 pair、18 case、{len(contrast_requests) * len(JUDGE_IDS)} Judge task\n- 全体再Judge: 480会話、2,160応答、{len(full_requests) * len(JUDGE_IDS)} Judge task\n- 比較用概算定価: ${estimated_cost:.6f}\n\nこの段階ではAPI未実行です。全体実行はcontrast全件一致後だけ開始します。\n"""
    (output / "report.md").write_text(report, encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "created_at": _now(),
        "audit_id": plan["audit_id"],
        "plan": {"path": str(plan_path.relative_to(repo)), "sha256": _sha256_file(plan_path)},
        "api_calls_started": False,
        "source_artifacts_mutated": False,
        "outputs": {
            path.name: {"sha256": _sha256_file(path), "bytes": path.stat().st_size}
            for path in (full_path, contrast_path, classified_path, summary_path, output / "report.md")
        },
    }
    _write_json(output / "manifest.json", manifest)
    return {**validation, **summary}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-plan")
    build = sub.add_parser("build-offline")
    build.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo = args.repo.resolve()
    plan_path = args.plan if args.plan.is_absolute() else repo / args.plan
    plan = _read_json(plan_path)
    if args.command == "validate-plan":
        result = validate_v21_plan(repo, plan_path, plan)
    else:
        output = args.output if args.output.is_absolute() else repo / args.output
        result = build_v21_offline(repo, plan_path, output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
