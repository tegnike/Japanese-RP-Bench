"""Analyze the complete frozen 480-conversation Judge v2.1 re-evaluation."""

from __future__ import annotations

import argparse
import itertools
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from japanese_rp_bench.v2.opencode_judge_audit_v21 import validate_v21_plan
from japanese_rp_bench.v2.opencode_repeatability import (
    JUDGE_IDS,
    SCENARIO_IDS,
    TARGET_IDS,
    _load_packs,
    _read_json,
    _read_jsonl,
    _sha256_file,
    _sha256_json,
    _write_json,
)
from japanese_rp_bench.v2.opencode_repeatability_analysis import (
    CONTINUOUS_METRICS,
    METRICS,
    _bootstrap_estimates,
    _cell_statistics,
    _judge_analysis,
    _model_results,
    _pairwise_comparisons,
    _point_estimates,
    _rank_analysis,
    _summary_metrics,
    sample_extension_decision,
)
from japanese_rp_bench.v2.scoring import score_conversation
from japanese_rp_bench.v2.schemas import Conversation, JudgeEvaluation, SchemaError


DEFAULT_PLAN = Path("configs/opencode_judge_audit_v21_2026-07-29.json")
DEFAULT_API_OUTPUT = Path(
    "tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v21-api-v1"
)
DEFAULT_OFFLINE = Path(
    "tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v21-offline"
)
DEFAULT_ANALYSIS = Path(
    "tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v21-api-v1/analysis-full2160"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_jsonl(path: Path, values: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )


def _finding(artifact: Mapping[str, Any], rule_id: str) -> Mapping[str, Any]:
    for finding in artifact["evaluation"]["findings"]:
        if finding.get("rule_id") == rule_id:
            return finding
    raise SchemaError(f"v2.1 artifact is missing rule finding: {rule_id}")


def _load_artifacts(
    api_output: Path,
    expected_plan_sha256: str,
) -> tuple[dict[tuple[str, str], Mapping[str, Any]], dict[str, Any]]:
    manifest_path = api_output / "manifest.json"
    summary_path = api_output / "full2160" / "summary.json"
    if not manifest_path.is_file() or not summary_path.is_file():
        raise SchemaError("v2.1 full analysis requires manifest and full2160 summary")
    manifest = _read_json(manifest_path)
    summary = _read_json(summary_path)
    if manifest.get("plan_sha256") != expected_plan_sha256:
        raise SchemaError("v2.1 API manifest plan hash mismatch")
    if (
        summary.get("complete") is not True
        or int(summary.get("expected_tasks", -1)) != 6480
        or int(summary.get("complete_tasks", -1)) != 6480
        or int(summary.get("failed_tasks", -1)) != 0
    ):
        raise SchemaError("v2.1 full Judge scope is not exactly complete")
    paths = sorted((api_output / "full2160" / "final").glob("*.json"))
    if len(paths) != 6480:
        raise SchemaError(f"v2.1 final artifact count must be 6480, got {len(paths)}")
    artifacts = [_read_json(path) for path in paths]
    if any(
        item.get("status") != "complete"
        or item.get("metadata", {}).get("rubric_version") != "challenge-judge-audit-v2.1"
        or item.get("metadata", {}).get("api_key_recorded") is not False
        for item in artifacts
    ):
        raise SchemaError("v2.1 final artifact integrity check failed")
    keyed = {
        (str(item["request_key"]), str(item["judge_id"])): item for item in artifacts
    }
    if len(keyed) != 6480:
        raise SchemaError("v2.1 final artifact keys are not unique")
    return keyed, {"manifest": manifest, "summary": summary, "artifact_paths": paths}


def _load_records(
    repo: Path,
    plan: Mapping[str, Any],
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_root = repo / str(plan["source"]["artifact_root"])
    challenge_plan = _read_json(repo / str(plan["source"]["challenge_plan_path"]))
    _, by_scenario = _load_packs(repo, challenge_plan)
    records: list[dict[str, Any]] = []
    disagreement_rules: Counter[str] = Counter()
    disagreement_targets: Counter[str] = Counter()
    conversation_disagreements: Counter[str] = Counter()
    judge_pairs: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {
            "opportunities": 0,
            "exact_agreements": 0,
            "absolute_score_difference": 0,
            "major_fail_disagreements": 0,
        }
    )
    evaluation_count = 0
    for block in range(1, 11):
        block_id = f"block-{block:02d}"
        run_root = source_root / "blocks" / block_id
        for conversation_path in sorted((run_root / "conversations").glob("**/*.json")):
            conversation = Conversation.from_dict(_read_json(conversation_path))
            role_pack = by_scenario[conversation.scenario_id]
            role = role_pack.roles[conversation.role_id]
            evaluations: list[JudgeEvaluation] = []
            for turn in conversation.turns:
                request_key = (
                    f"{block_id}|{conversation.target_model}|{role_pack.id}|"
                    f"{conversation.scenario_id}|turn-{turn.index}"
                )
                for judge_id in JUDGE_IDS:
                    artifact = artifacts.get((request_key, judge_id))
                    if artifact is None:
                        raise SchemaError(f"Missing v2.1 artifact: {request_key}/{judge_id}")
                    evaluations.append(JudgeEvaluation.from_dict(artifact["evaluation"], role))
            evaluation_count += len(evaluations)
            ensemble = score_conversation(role_pack, conversation, evaluations, minimum_judges=3)
            judge_specific: dict[str, dict[str, float | None]] = {}
            leave_one_out: dict[str, dict[str, float | None]] = {}
            for judge_id in JUDGE_IDS:
                selected = [item for item in evaluations if item.judge_id == judge_id]
                judge_specific[judge_id] = _summary_metrics(
                    score_conversation(role_pack, conversation, selected, minimum_judges=1)["summary"]
                )
                selected = [item for item in evaluations if item.judge_id != judge_id]
                leave_one_out[judge_id] = _summary_metrics(
                    score_conversation(role_pack, conversation, selected, minimum_judges=2)["summary"]
                )

            severe_count = 0
            grouped: dict[tuple[int, str], dict[str, tuple[float | None, str]]] = defaultdict(dict)
            for evaluation in evaluations:
                for finding in evaluation.findings:
                    grouped[(evaluation.turn, finding.rule_id)][evaluation.judge_id] = (
                        finding.verdict.score,
                        finding.severity.value,
                    )
            for (_, rule_id), verdicts in grouped.items():
                numeric = [value[0] for value in verdicts.values() if value[0] is not None]
                if numeric and max(numeric) - min(numeric) >= 0.75:
                    severe_count += 1
                    disagreement_rules[rule_id] += 1
                    disagreement_targets[conversation.target_model] += 1
                for left, right in itertools.combinations(JUDGE_IDS, 2):
                    left_value, severity = verdicts[left]
                    right_value, _ = verdicts[right]
                    if left_value is None or right_value is None:
                        continue
                    pair = judge_pairs[(left, right)]
                    pair["opportunities"] += 1
                    pair["exact_agreements"] += left_value == right_value
                    pair["absolute_score_difference"] += abs(left_value - right_value)
                    if severity == "major":
                        pair["major_fail_disagreements"] += (left_value == 0.0) != (right_value == 0.0)
            if severe_count:
                conversation_disagreements[conversation.target_model] += 1
            records.append({
                "block": block,
                "target_id": conversation.target_model,
                "scenario_id": conversation.scenario_id,
                "metrics": _summary_metrics(ensemble["summary"]),
                "judge_specific": judge_specific,
                "leave_one_out": leave_one_out,
                "judge_disagreements": severe_count,
            })
    cells = Counter((record["target_id"], record["scenario_id"]) for record in records)
    if (
        len(records) != 480
        or set(cells) != set(itertools.product(TARGET_IDS, SCENARIO_IDS))
        or set(cells.values()) != {10}
        or evaluation_count != 6480
    ):
        raise SchemaError("v2.1 records do not form the complete 8x6x10 design")
    pair_summary = []
    for (left, right), raw in sorted(judge_pairs.items()):
        opportunities = int(raw["opportunities"])
        pair_summary.append({
            "judge_a": left,
            "judge_b": right,
            "rule_opportunities": opportunities,
            "exact_verdict_agreement_rate": round(raw["exact_agreements"] / opportunities * 100, 6),
            "mean_absolute_verdict_score_difference": round(
                raw["absolute_score_difference"] / opportunities, 6
            ),
            "major_fail_classification_disagreements": int(raw["major_fail_disagreements"]),
        })
    disagreements = {
        "severe_disagreement_definition": "within-conversation pass/fail spread of at least 0.75; not-applicable excluded",
        "severe_disagreements": sum(disagreement_rules.values()),
        "conversations_with_severe_disagreement": sum(conversation_disagreements.values()),
        "by_target": dict(sorted(disagreement_targets.items())),
        "conversations_by_target": dict(sorted(conversation_disagreements.items())),
        "by_rule": dict(disagreement_rules.most_common()),
        "judge_pairs": pair_summary,
    }
    return sorted(records, key=lambda item: (item["block"], item["target_id"], item["scenario_id"])), disagreements


def _residual_audit(
    offline: Path,
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
    analysis_output: Path,
) -> dict[str, Any]:
    rows = _read_jsonl(offline / "remaining-15-classification.jsonl")
    if len(rows) != 15:
        raise SchemaError("v2.1 residual audit requires exactly 15 rows")
    class_counts: dict[str, Counter[str]] = defaultdict(Counter)
    patterns: Counter[str] = Counter()
    details = []
    for row in rows:
        audit_id = str(row["audit_id"])
        request_key = "|".join(audit_id.split("|")[:-1])
        rule_id = str(row["rule_id"])
        annotation = row["v21_review"]
        expected = str(annotation["expected_rule_verdict"])
        verdicts = []
        judgments = {}
        for judge_id in JUDGE_IDS:
            finding = _finding(artifacts[(request_key, judge_id)], rule_id)
            verdict = str(finding["verdict"])
            verdicts.append(verdict)
            judgments[judge_id] = {
                "verdict": verdict,
                "evidence": finding.get("evidence", ""),
                "rationale": finding.get("rationale", ""),
            }
            if expected in {"pass", "fail"}:
                class_counts[str(annotation["classification"])]["opportunities"] += 1
                class_counts[str(annotation["classification"])]["exact"] += verdict == expected
                class_counts[str(annotation["classification"])]["opposite"] += verdict == (
                    "pass" if expected == "fail" else "fail"
                )
        pattern = "/".join(verdicts)
        patterns[pattern] += 1
        details.append({
            "audit_id": audit_id,
            "classification": annotation["classification"],
            "expected_rule_verdict": expected,
            "v21_judgments": judgments,
            "pass_fail_disagreement": {"pass", "fail"}.issubset(set(verdicts)),
        })
    _write_jsonl(
        analysis_output / "remaining-15-results.jsonl",
        details,
    )
    return {
        "cells": 15,
        "pass_fail_disagreements": sum(item["pass_fail_disagreement"] for item in details),
        "verdict_patterns_in_judge_order": {
            "judge_order": list(JUDGE_IDS),
            "patterns": dict(patterns),
        },
        "known_direction_by_classification": {
            key: dict(value) for key, value in sorted(class_counts.items())
        },
        "ambiguous_cells_not_scored_as_truth": sum(
            item["expected_rule_verdict"] == "review_required" for item in details
        ),
    }


def _original_83_audit(
    repo: Path,
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
    analysis_output: Path,
) -> dict[str, Any]:
    source = (
        repo
        / "tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v2-offline/disagreement-audit.jsonl"
    )
    rows = _read_jsonl(source)
    if len(rows) != 83:
        raise SchemaError("v2.1 comparison requires the frozen original 83 cells")
    details = []
    by_rule: Counter[str] = Counter()
    patterns: Counter[str] = Counter()
    known = Counter()
    for row in rows:
        audit_id = str(row["audit_id"])
        request_key = "|".join(audit_id.split("|")[:-1])
        rule_id = str(row["rule"]["rule_id"])
        expected = str(row["offline_review"]["expected_rule_verdict"])
        verdicts = []
        judgments = {}
        for judge_id in JUDGE_IDS:
            finding = _finding(artifacts[(request_key, judge_id)], rule_id)
            verdict = str(finding["verdict"])
            verdicts.append(verdict)
            judgments[judge_id] = {
                "verdict": verdict,
                "evidence": finding.get("evidence", ""),
                "rationale": finding.get("rationale", ""),
            }
            if expected in {"pass", "fail"}:
                known["opportunities"] += 1
                known["exact"] += verdict == expected
                known["opposite"] += verdict == ("pass" if expected == "fail" else "fail")
        severe = {"pass", "fail"}.issubset(set(verdicts))
        if severe:
            by_rule[rule_id] += 1
        patterns["/".join(verdicts)] += 1
        details.append({
            "audit_id": audit_id,
            "rule_id": rule_id,
            "preregistered_expected_rule_verdict": expected,
            "v21_judgments": judgments,
            "pass_fail_disagreement": severe,
        })
    _write_jsonl(analysis_output / "original-83-results.jsonl", details)
    return {
        "cells": 83,
        "pass_fail_disagreements": sum(item["pass_fail_disagreement"] for item in details),
        "by_rule": dict(by_rule),
        "verdict_patterns_in_judge_order": {
            "judge_order": list(JUDGE_IDS),
            "patterns": dict(patterns),
        },
        "known_control_directions": dict(known),
        "known_controls_are_not_overall_accuracy_sample": True,
    }


def _compare_old(
    repo: Path,
    model_results: Mapping[str, Any],
    ranks: Mapping[str, Any],
    disagreements: Mapping[str, Any],
) -> dict[str, Any]:
    old_path = (
        repo
        / "tmp/opencode-challenge-repeatability-20260727-v1/analysis-10-blocks/analysis.json"
    )
    old = _read_json(old_path)
    models = {}
    for target in TARGET_IDS:
        old_result = old["model_results"][target]
        new_result = model_results[target]
        metrics = {}
        for metric in METRICS:
            old_value = float(old_result["metrics"][metric]["scenario_macro_mean"])
            new_value = float(new_result["metrics"][metric]["scenario_macro_mean"])
            metrics[metric] = {
                "old": old_value,
                "v21": new_value,
                "delta_v21_minus_old": round(new_value - old_value, 6),
            }
        models[target] = {
            "old_point_rank": int(old_result["point_rank"]),
            "v21_point_rank": int(new_result["point_rank"]),
            "rank_change": int(old_result["point_rank"]) - int(new_result["point_rank"]),
            "metrics": metrics,
        }
    old_disagreements = old["judge_analysis"]["disagreements"]
    return {
        "old_analysis_path": str(old_path.relative_to(repo)),
        "old_analysis_sha256": _sha256_file(old_path),
        "models": models,
        "point_order": {
            "old": old["rank_analysis"]["point_order"],
            "v21": ranks["point_order"],
        },
        "judge_disagreements": {
            "old_severe": int(old_disagreements["severe_disagreements"]),
            "v21_severe": int(disagreements["severe_disagreements"]),
            "delta": int(disagreements["severe_disagreements"])
            - int(old_disagreements["severe_disagreements"]),
            "old_conversations": int(old_disagreements["conversations_with_severe_disagreement"]),
            "v21_conversations": int(disagreements["conversations_with_severe_disagreement"]),
        },
    }


def analyze_v21(
    repo: Path,
    plan_path: Path,
    offline: Path,
    api_output: Path,
    analysis_output: Path,
) -> dict[str, Any]:
    plan = _read_json(plan_path)
    validate_v21_plan(repo, plan_path, plan)
    plan_sha256 = _sha256_file(plan_path)
    artifacts, integrity_raw = _load_artifacts(api_output, plan_sha256)
    records, disagreements = _load_records(repo, plan, artifacts)
    challenge_plan = _read_json(repo / str(plan["source"]["challenge_plan_path"]))
    analysis_config = challenge_plan["analysis"]
    replicates = int(analysis_config["bootstrap"]["replicates"])
    seed = int(analysis_config["bootstrap"]["seed"])
    points = _point_estimates(records)
    bootstrap = _bootstrap_estimates(records, replicates, seed)
    pairwise = _pairwise_comparisons(points, bootstrap, challenge_plan)
    ranks = _rank_analysis(points, bootstrap)
    judge_analysis = _judge_analysis(records, disagreements)
    model_results = _model_results(records, points, bootstrap, ranks)
    decision = sample_extension_decision(points, pairwise, ranks)
    cell_statistics = _cell_statistics(records, replicates, seed)
    analysis_output.mkdir(parents=True, exist_ok=True)
    residual = _residual_audit(offline, artifacts, analysis_output)
    original_83 = _original_83_audit(repo, artifacts, analysis_output)
    old_comparison = _compare_old(repo, model_results, ranks, disagreements)
    integrity = {
        "plan_sha256": plan_sha256,
        "offline_manifest_sha256": _sha256_file(offline / "manifest.json"),
        "api_manifest_sha256": _sha256_file(api_output / "manifest.json"),
        "full_summary_sha256": _sha256_file(api_output / "full2160" / "summary.json"),
        "final_judge_outputs": len(integrity_raw["artifact_paths"]),
        "frozen_conversations": 480,
        "frozen_target_responses": 2160,
        "source_artifacts_mutated": False,
    }
    analysis_fingerprint = _sha256_json({
        "audit_id": plan["audit_id"],
        "rubric_version": "challenge-judge-audit-v2.1",
        "integrity": integrity,
        "analysis": analysis_config,
    })
    result = {
        "schema_version": "2.1",
        "created_at": _now(),
        "analysis_fingerprint": analysis_fingerprint,
        "scope": "challenge_repeatability_v21_separate_track_only",
        "ensemble_is_ground_truth": False,
        "integrity": integrity,
        "definitions": {
            "independent_sample_unit": "conversation",
            "bootstrap": analysis_config["bootstrap"],
            "minimum_practical_difference": analysis_config["minimum_practical_difference"],
            "multiple_comparisons": analysis_config["multiple_comparisons"],
        },
        "model_results": model_results,
        "rank_analysis": ranks,
        "pairwise_comparisons": pairwise,
        "judge_analysis": judge_analysis,
        "remaining_15_audit": residual,
        "original_83_audit": original_83,
        "old_vs_v21": old_comparison,
        "sample_extension_decision_not_authorized_to_generate": decision,
    }
    _write_json(analysis_output / "analysis.json", result)
    _write_jsonl(analysis_output / "conversation-metrics.jsonl", records)
    _write_json(analysis_output / "model-scenario-statistics.json", cell_statistics)
    _write_jsonl(analysis_output / "pairwise-comparisons.jsonl", pairwise)
    _write_json(analysis_output / "judge-analysis.json", judge_analysis)
    _write_json(analysis_output / "old-vs-v21.json", old_comparison)
    _write_json(analysis_output / "remaining-15-summary.json", residual)
    _write_json(analysis_output / "original-83-summary.json", original_83)
    conclusions = Counter(item["conclusion"] for item in pairwise)
    report_lines = []
    for target in ranks["point_order"]:
        item = model_results[target]
        metrics = item["metrics"]
        report_lines.append(
            f"| {item['point_rank']} | {item['display_name']} | "
            f"{metrics['major_free_rate']['scenario_macro_mean']:.1f} | "
            f"{metrics['major_violation_rate']['scenario_macro_mean']:.1f} | "
            f"{metrics['challenge_rp_summary']['scenario_macro_mean']:.2f} | "
            f"{item['rank_probabilities']['1'] * 100:.1f}% |"
        )
    report = f"""# OpenCode Challenge Judge v2.1 全体再評価\n\n> 保存済み480会話・2,160応答だけを再Judgeした別トラックです。人間の真値や正式Leaderboardではありません。\n\n- Judge出力: 6,480 / 6,480\n- 大きなJudge不一致: {disagreements['severe_disagreements']}件\n- 元の83セルのpass/fail不一致: {original_83['pass_fail_disagreements']}件\n- v2で残った15セルのpass/fail不一致: {residual['pass_fail_disagreements']}件\n- 指標別ペア: 優位 {conclusions['model_a_superior'] + conclusions['model_b_superior']}、同等 {conclusions['equivalent_within_registered_bounds']}、保留 {conclusions['indeterminate']}\n\n| 順位 | モデル | Major-free (%) | Major率 | RP Summary | 1位確率 |\n|---:|---|---:|---:|---:|---:|\n{chr(10).join(report_lines)}\n\n旧結果との詳細差分は`old-vs-v21.json`、全比較は`pairwise-comparisons.jsonl`を参照してください。\n"""
    (analysis_output / "report.md").write_text(report, encoding="utf-8")
    artifact_paths = sorted(
        path for path in analysis_output.iterdir() if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "schema_version": "2.1",
        "created_at": _now(),
        "analysis_fingerprint": analysis_fingerprint,
        "source_integrity": integrity,
        "artifacts": {
            path.name: {"sha256": _sha256_file(path), "bytes": path.stat().st_size}
            for path in artifact_paths
        },
    }
    _write_json(analysis_output / "manifest.json", manifest)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--offline", type=Path, default=DEFAULT_OFFLINE)
    parser.add_argument("--api-output", type=Path, default=DEFAULT_API_OUTPUT)
    parser.add_argument("--analysis-output", type=Path, default=DEFAULT_ANALYSIS)
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo = args.repo.resolve()
    plan = args.plan if args.plan.is_absolute() else repo / args.plan
    offline = args.offline if args.offline.is_absolute() else repo / args.offline
    api_output = args.api_output if args.api_output.is_absolute() else repo / args.api_output
    analysis_output = (
        args.analysis_output if args.analysis_output.is_absolute() else repo / args.analysis_output
    )
    result = analyze_v21(repo, plan, offline.resolve(), api_output.resolve(), analysis_output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
