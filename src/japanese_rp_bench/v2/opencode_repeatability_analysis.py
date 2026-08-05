"""Analyze the preregistered OpenCode Challenge repeatability artifacts."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist, mean, median, stdev, variance
from typing import Any, Iterable, Mapping, Sequence

from japanese_rp_bench.v2.opencode_repeatability import (
    JUDGE_IDS,
    SCENARIO_IDS,
    TARGET_IDS,
    _judgment_artifact_paths,
    _load_packs,
    _read_json,
    _read_jsonl,
    _sha256_file,
    _sha256_json,
    _write_json,
    validate_plan,
)
from japanese_rp_bench.v2.scoring import score_conversation
from japanese_rp_bench.v2.schemas import Conversation, JudgeEvaluation, SchemaError


ANALYSIS_SCHEMA_VERSION = "1.0"
CONTINUOUS_METRICS = (
    "role_fidelity_score",
    "conversation_quality_score",
    "persona_stability_score",
    "robustness_score",
    "recovery_score",
)
RATE_METRICS = ("major_violation_rate", "major_free_rate")
METRICS = (*CONTINUOUS_METRICS, *RATE_METRICS, "challenge_rp_summary")
ROBUSTNESS_SCENARIOS = (
    "wind_guide_baseline",
    "museum_curator_injection",
    "tea_room_twelve_turns",
    "nikechan_adversarial",
)
DISPLAY_NAMES = {
    "opencode-go-grok-4.5": "Grok 4.5",
    "opencode-go-hy3": "Hy3",
    "opencode-go-qwen3.7-max": "Qwen3.7 Max",
    "opencode-go-kimi-k3": "Kimi K3",
    "opencode-go-deepseek-v4-pro": "DeepSeek V4 Pro",
    "opencode-go-minimax-m3": "MiniMax M3",
    "opencode-go-glm-5.2": "GLM-5.2",
    "opencode-go-mimo-v2.5-pro": "MiMo V2.5 Pro",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("Cannot calculate a percentile of an empty sequence")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _interval(values: Sequence[float], confidence: float) -> list[float]:
    tail = (1.0 - confidence) / 2.0
    return [round(_percentile(values, tail), 6), round(_percentile(values, 1.0 - tail), 6)]


def _sample_standard_deviation(values: Sequence[float]) -> float:
    return 0.0 if len(values) < 2 else stdev(values)


def _normal_two_sided_p(point: float, bootstrap_values: Sequence[float]) -> float:
    standard_error = _sample_standard_deviation(bootstrap_values)
    if standard_error == 0.0:
        return 0.0 if point != 0.0 else 1.0
    return min(1.0, 2.0 * (1.0 - NormalDist().cdf(abs(point) / standard_error)))


def _normal_equivalence_p(
    point: float,
    bootstrap_values: Sequence[float],
    bound: float,
) -> float:
    """Return the larger p-value from two one-sided equivalence tests."""

    standard_error = _sample_standard_deviation(bootstrap_values)
    if standard_error == 0.0:
        return 0.0 if -bound < point < bound else 1.0
    normal = NormalDist()
    lower_p = 1.0 - normal.cdf((point + bound) / standard_error)
    upper_p = normal.cdf((point - bound) / standard_error)
    return min(1.0, max(lower_p, upper_p))


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    """Holm-adjust p-values while preserving their original order."""

    count = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    result = [1.0] * count
    previous = 0.0
    for rank, (index, raw) in enumerate(indexed):
        adjusted = min(1.0, (count - rank) * raw)
        previous = max(previous, adjusted)
        result[index] = previous
    return result


def _summary_metrics(summary: Mapping[str, Any]) -> dict[str, float | None]:
    metrics: dict[str, float | None] = {
        metric: None if summary.get(metric) is None else float(summary[metric])
        for metric in CONTINUOUS_METRICS
    }
    major_count = int(summary["major_violations"])
    # This incidence rate preserves the formal ranking's second key: it is the
    # number of Major findings per 100 conversations and may exceed 100.
    metrics["major_violation_rate"] = float(major_count * 100)
    metrics["major_free_rate"] = 100.0 if bool(summary["major_violation_free"]) else 0.0
    available = [metrics[metric] for metric in CONTINUOUS_METRICS if metrics[metric] is not None]
    metrics["challenge_rp_summary"] = mean(available) if available else None
    return metrics


def _macro_metric(records: Sequence[Mapping[str, Any]], metric: str) -> float:
    if metric == "challenge_rp_summary":
        component_values = [_macro_metric(records, component) for component in CONTINUOUS_METRICS]
        return mean(component_values)
    by_scenario: dict[str, list[float]] = defaultdict(list)
    for record in records:
        value = record["metrics"].get(metric)
        if value is not None:
            by_scenario[str(record["scenario_id"])].append(float(value))
    if not by_scenario:
        raise SchemaError(f"No values are available for {metric}")
    return mean(mean(values) for values in by_scenario.values())


def _metric_values_by_cell(
    records: Sequence[Mapping[str, Any]],
    metric: str,
) -> dict[tuple[str, str], list[float]]:
    values: dict[tuple[str, str], list[float]] = defaultdict(list)
    for record in records:
        value = record["metrics"].get(metric)
        if value is not None:
            values[(str(record["target_id"]), str(record["scenario_id"]))].append(float(value))
    return values


def _validate_analysis_source(output: Path, plan_path: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    validate_plan(plan)
    manifest_path = output / "manifest.json"
    completeness_path = output / "completeness-report.json"
    if not manifest_path.is_file() or not completeness_path.is_file():
        raise SchemaError("Analysis requires a prepared manifest and completeness report")
    manifest = _read_json(manifest_path)
    completeness = _read_json(completeness_path)
    if manifest.get("plan", {}).get("sha256") != _sha256_file(plan_path):
        raise SchemaError("Analysis source does not match the current preregistered plan")
    registered = manifest.get("completeness_report", {})
    if registered.get("sha256") != _sha256_file(completeness_path):
        raise SchemaError("Completeness report hash does not match the experiment manifest")
    expected = plan["expected_outputs"]
    exact_counts = all(
        int(completeness.get(key, -1)) == int(expected[expected_key])
        for key, expected_key in (
            ("conversations", "registered_conversations"),
            ("target_responses", "registered_target_responses"),
            ("judge_outputs", "registered_judge_outputs"),
        )
    )
    if completeness.get("passed") is not True or int(completeness.get("complete_blocks", 0)) != 10:
        raise SchemaError("Analysis requires a passing 10-block completeness report")
    if not exact_counts:
        raise SchemaError("Completeness report does not contain the preregistered exact counts")
    return {
        "experiment_fingerprint": str(manifest["experiment_fingerprint"]),
        "plan_sha256": _sha256_file(plan_path),
        "completeness_report_sha256": _sha256_file(completeness_path),
        "complete_blocks": 10,
        "conversations": int(completeness["conversations"]),
        "target_responses": int(completeness["target_responses"]),
        "judge_outputs": int(completeness["judge_outputs"]),
    }


def _load_records(
    repo: Path,
    output: Path,
    plan: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _, by_scenario = _load_packs(repo, plan)
    records: list[dict[str, Any]] = []
    disagreement_rules: Counter[str] = Counter()
    disagreement_targets: Counter[str] = Counter()
    conversation_disagreements: Counter[str] = Counter()
    judge_pairs: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"opportunities": 0, "exact_agreements": 0, "absolute_score_difference": 0, "major_fail_disagreements": 0}
    )
    final_judgment_count = 0

    for block in range(1, 11):
        block_id = f"block-{block:02d}"
        run_root = output / "blocks" / block_id
        audit_path = run_root / "repeatability-audit.json"
        root_manifest = _read_json(output / "manifest.json")
        registered_block = root_manifest.get("blocks", {}).get(block_id, {})
        if (
            not audit_path.is_file()
            or registered_block.get("audit_sha256") != _sha256_file(audit_path)
            or _read_json(audit_path).get("passed") is not True
        ):
            raise SchemaError(f"Analysis source block is not audit-complete: {block_id}")
        run_manifest = _read_json(run_root / "manifest.json")
        if run_manifest.get("status") != "complete":
            raise SchemaError(f"Analysis source run is not complete: {block_id}")
        run_fingerprint = str(run_manifest["run_fingerprint"])
        report_paths = sorted((run_root / "reports").glob("**/*.json"))
        judgment_paths, _ = _judgment_artifact_paths(run_root)
        if len(report_paths) != 48 or len(judgment_paths) != 48:
            raise SchemaError(f"Analysis source block has an unexpected artifact count: {block_id}")

        for report_path in report_paths:
            relative = report_path.relative_to(run_root / "reports")
            conversation_path = run_root / "conversations" / relative
            judgment_path = run_root / "judgments" / relative.with_suffix(".jsonl")
            report = _read_json(report_path)
            conversation = Conversation.from_dict(_read_json(conversation_path))
            scenario_id = str(report["scenario_id"])
            target_id = str(report["target_model"])
            if (
                report.get("run_fingerprint") != run_fingerprint
                or conversation.metadata.get("run_fingerprint") != run_fingerprint
                or conversation.scenario_id != scenario_id
                or conversation.target_model != target_id
            ):
                raise SchemaError(f"Artifact fingerprint or identity mismatch: {report_path}")
            role_pack = by_scenario[scenario_id]
            role = role_pack.roles[conversation.role_id]
            evaluations = [JudgeEvaluation.from_dict(value, role) for value in _read_jsonl(judgment_path)]
            final_judgment_count += len(evaluations)
            expected_evaluations = len(conversation.turns) * len(JUDGE_IDS)
            if len(evaluations) != expected_evaluations:
                raise SchemaError(f"Unexpected final Judge count: {judgment_path}")
            for turn in conversation.turns:
                turn_judges = {
                    evaluation.judge_id for evaluation in evaluations if evaluation.turn == turn.index
                }
                if turn_judges != set(JUDGE_IDS):
                    raise SchemaError(f"Missing registered Judge at turn {turn.index}: {judgment_path}")

            rescored = score_conversation(role_pack, conversation, evaluations, minimum_judges=3)
            if _summary_metrics(rescored["summary"]) != _summary_metrics(report["summary"]):
                raise SchemaError(f"Stored report does not reproduce from final judgments: {report_path}")
            judge_specific: dict[str, dict[str, float | None]] = {}
            leave_one_out: dict[str, dict[str, float | None]] = {}
            for judge_id in JUDGE_IDS:
                selected = [evaluation for evaluation in evaluations if evaluation.judge_id == judge_id]
                judge_specific[judge_id] = _summary_metrics(
                    score_conversation(role_pack, conversation, selected, minimum_judges=1)["summary"]
                )
                selected = [evaluation for evaluation in evaluations if evaluation.judge_id != judge_id]
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
                    disagreement_targets[target_id] += 1
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
                conversation_disagreements[target_id] += 1

            records.append(
                {
                    "block": block,
                    "target_id": target_id,
                    "scenario_id": scenario_id,
                    "metrics": _summary_metrics(report["summary"]),
                    "judge_specific": judge_specific,
                    "leave_one_out": leave_one_out,
                    "judge_disagreements": severe_count,
                }
            )

    cells = Counter((record["target_id"], record["scenario_id"]) for record in records)
    if (
        len(records) != 480
        or set(cells) != set(itertools.product(TARGET_IDS, SCENARIO_IDS))
        or set(cells.values()) != {10}
        or final_judgment_count != 6480
    ):
        raise SchemaError("Analysis records do not form the complete preregistered 8x6x10 design")
    pair_summary = []
    for (left, right), raw in sorted(judge_pairs.items()):
        opportunities = int(raw["opportunities"])
        pair_summary.append(
            {
                "judge_a": left,
                "judge_b": right,
                "rule_opportunities": opportunities,
                "exact_verdict_agreement_rate": round(raw["exact_agreements"] / opportunities * 100.0, 6),
                "mean_absolute_verdict_score_difference": round(raw["absolute_score_difference"] / opportunities, 6),
                "major_fail_classification_disagreements": int(raw["major_fail_disagreements"]),
            }
        )
    disagreement = {
        "severe_disagreement_definition": "within-conversation pass/fail spread of at least 0.75; not-applicable excluded",
        "severe_disagreements": sum(disagreement_rules.values()),
        "conversations_with_severe_disagreement": sum(conversation_disagreements.values()),
        "by_target": dict(sorted(disagreement_targets.items())),
        "conversations_by_target": dict(sorted(conversation_disagreements.items())),
        "by_rule": dict(disagreement_rules.most_common()),
        "judge_pairs": pair_summary,
    }
    return sorted(records, key=lambda item: (item["block"], item["target_id"], item["scenario_id"])), disagreement


def _variant_records(
    records: Sequence[Mapping[str, Any]],
    field: str,
    variant_id: str,
) -> list[dict[str, Any]]:
    return [
        {
            "block": record["block"],
            "target_id": record["target_id"],
            "scenario_id": record["scenario_id"],
            "metrics": record[field][variant_id],
        }
        for record in records
    ]


def _point_estimates(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, float]]:
    return {
        target: {
            metric: round(
                _macro_metric([record for record in records if record["target_id"] == target], metric),
                6,
            )
            for metric in METRICS
        }
        for target in TARGET_IDS
    }


def _bootstrap_estimates(
    records: Sequence[Mapping[str, Any]],
    replicates: int,
    seed: int,
) -> dict[str, dict[str, list[float]]]:
    cube = {
        (int(record["block"]), str(record["target_id"]), str(record["scenario_id"])): record["metrics"]
        for record in records
    }
    result = {target: {metric: [] for metric in METRICS} for target in TARGET_IDS}
    rng = random.Random(seed)
    for _ in range(replicates):
        sampled_blocks = [rng.randrange(1, 11) for _ in range(10)]
        sampled_scenarios = [SCENARIO_IDS[rng.randrange(len(SCENARIO_IDS))] for _ in SCENARIO_IDS]
        while not set(sampled_scenarios).intersection(ROBUSTNESS_SCENARIOS):
            sampled_scenarios = [SCENARIO_IDS[rng.randrange(len(SCENARIO_IDS))] for _ in SCENARIO_IDS]
        for target in TARGET_IDS:
            values: dict[str, float] = {}
            for metric in (*CONTINUOUS_METRICS, *RATE_METRICS):
                scenario_means = []
                for scenario in sampled_scenarios:
                    sampled_values = [
                        cube[(block, target, scenario)].get(metric) for block in sampled_blocks
                    ]
                    numeric = [float(value) for value in sampled_values if value is not None]
                    if numeric:
                        scenario_means.append(mean(numeric))
                values[metric] = mean(scenario_means)
                result[target][metric].append(values[metric])
            result[target]["challenge_rp_summary"].append(
                mean(values[metric] for metric in CONTINUOUS_METRICS)
            )
    return result


def _cell_statistics(
    records: Sequence[Mapping[str, Any]],
    replicates: int,
    seed: int,
) -> list[dict[str, Any]]:
    by_metric = {metric: _metric_values_by_cell(records, metric) for metric in METRICS}
    results = []
    for target, scenario in itertools.product(TARGET_IDS, SCENARIO_IDS):
        metrics = {}
        for metric in METRICS:
            values = by_metric[metric].get((target, scenario), [])
            if not values:
                metrics[metric] = None
                continue
            cell_seed = int.from_bytes(
                hashlib.sha256(f"{seed}|{target}|{scenario}|{metric}".encode()).digest()[:8],
                "big",
            )
            rng = random.Random(cell_seed)
            bootstrap_means = [
                mean(values[rng.randrange(len(values))] for _ in values) for _ in range(replicates)
            ]
            metrics[metric] = {
                "n_conversations": len(values),
                "mean": round(mean(values), 6),
                "median": round(median(values), 6),
                "sample_standard_deviation": round(_sample_standard_deviation(values), 6),
                "confidence_interval_95": _interval(bootstrap_means, 0.95),
            }
        results.append({"target_id": target, "scenario_id": scenario, "metrics": metrics})
    return results


def _pairwise_comparisons(
    points: Mapping[str, Mapping[str, float]],
    bootstrap: Mapping[str, Mapping[str, Sequence[float]]],
    plan: Mapping[str, Any],
) -> list[dict[str, Any]]:
    alpha = float(plan["analysis"]["multiple_comparisons"]["alpha"])
    continuous_bound = float(plan["analysis"]["minimum_practical_difference"]["continuous_score_points"])
    rate_bound = float(plan["analysis"]["minimum_practical_difference"]["rate_percentage_points"])
    results: list[dict[str, Any]] = []
    for metric in METRICS:
        metric_results = []
        for model_a, model_b in itertools.combinations(TARGET_IDS, 2):
            point = float(points[model_a][metric]) - float(points[model_b][metric])
            differences = [
                float(left) - float(right)
                for left, right in zip(bootstrap[model_a][metric], bootstrap[model_b][metric])
            ]
            bound = rate_bound if metric in RATE_METRICS else continuous_bound
            metric_results.append(
                {
                    "metric": metric,
                    "model_a": model_a,
                    "model_b": model_b,
                    "difference_a_minus_b": round(point, 6),
                    "confidence_interval_95": _interval(differences, 0.95),
                    "confidence_interval_90": _interval(differences, 0.90),
                    "minimum_practical_difference": bound,
                    "raw_two_sided_p_value": _normal_two_sided_p(point, differences),
                    "raw_equivalence_p_value": _normal_equivalence_p(point, differences, bound),
                }
            )
        adjusted_difference = holm_adjust([row["raw_two_sided_p_value"] for row in metric_results])
        adjusted_equivalence = holm_adjust([row["raw_equivalence_p_value"] for row in metric_results])
        lower_is_better = metric == "major_violation_rate"
        for row, difference_p, equivalence_p in zip(
            metric_results, adjusted_difference, adjusted_equivalence
        ):
            row["holm_adjusted_two_sided_p_value"] = round(difference_p, 12)
            row["holm_adjusted_equivalence_p_value"] = round(equivalence_p, 12)
            ci95 = row["confidence_interval_95"]
            ci90 = row["confidence_interval_90"]
            point = row["difference_a_minus_b"]
            practical = abs(point) >= row["minimum_practical_difference"]
            statistically_different = (ci95[0] > 0.0 or ci95[1] < 0.0) and difference_p < alpha
            superior = practical and statistically_different
            equivalent = (
                ci90[0] > -row["minimum_practical_difference"]
                and ci90[1] < row["minimum_practical_difference"]
                and equivalence_p < alpha
            )
            if superior:
                a_better = point < 0.0 if lower_is_better else point > 0.0
                conclusion = "model_a_superior" if a_better else "model_b_superior"
            elif equivalent:
                conclusion = "equivalent_within_registered_bounds"
            else:
                conclusion = "indeterminate"
            row.update(
                {
                    "statistically_different_after_holm": statistically_different,
                    "meets_minimum_practical_difference": practical,
                    "conclusion": conclusion,
                }
            )
            results.append(row)
    return results


def _rank_analysis(
    points: Mapping[str, Mapping[str, float]],
    bootstrap: Mapping[str, Mapping[str, Sequence[float]]],
) -> dict[str, Any]:
    rank_counts = {target: [0.0] * len(TARGET_IDS) for target in TARGET_IDS}
    replicates = len(bootstrap[TARGET_IDS[0]]["challenge_rp_summary"])
    for index in range(replicates):
        keyed: dict[tuple[float, float, float], list[str]] = defaultdict(list)
        for target in TARGET_IDS:
            key = (
                -bootstrap[target]["major_free_rate"][index],
                bootstrap[target]["major_violation_rate"][index],
                -bootstrap[target]["challenge_rp_summary"][index],
            )
            keyed[key].append(target)
        position = 0
        for key in sorted(keyed):
            tied = sorted(keyed[key])
            occupied = range(position, position + len(tied))
            share = 1.0 / len(tied)
            for target in tied:
                for rank_index in occupied:
                    rank_counts[target][rank_index] += share
            position += len(tied)
    point_order = sorted(
        TARGET_IDS,
        key=lambda target: (
            -points[target]["major_free_rate"],
            points[target]["major_violation_rate"],
            -points[target]["challenge_rp_summary"],
            target,
        ),
    )
    return {
        "tie_policy": "tied models split probability equally across the integer ranks occupied by the tie",
        "point_order": point_order,
        "models": {
            target: {
                "point_rank": point_order.index(target) + 1,
                "rank_probabilities": {
                    str(rank): round(rank_counts[target][rank - 1] / replicates, 6)
                    for rank in range(1, len(TARGET_IDS) + 1)
                },
            }
            for target in TARGET_IDS
        },
    }


def _variance_components(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for target in TARGET_IDS:
        target_records = [record for record in records if record["target_id"] == target]
        target_result = {}
        for metric in (*CONTINUOUS_METRICS, *RATE_METRICS):
            observed_between_variances = []
            within_judge_variances = []
            estimated_generation_variances = []
            for scenario in SCENARIO_IDS:
                conversation_judge_means = []
                conversation_judge_variances = []
                for record in target_records:
                    if record["scenario_id"] != scenario:
                        continue
                    judge_values = [
                        record["judge_specific"][judge][metric]
                        for judge in JUDGE_IDS
                        if record["judge_specific"][judge].get(metric) is not None
                    ]
                    if judge_values:
                        conversation_judge_means.append(mean(float(value) for value in judge_values))
                    if len(judge_values) > 1:
                        conversation_judge_variances.append(
                            variance(float(value) for value in judge_values)
                        )
                if len(conversation_judge_means) > 1:
                    observed_between = variance(conversation_judge_means)
                    within_judge = (
                        mean(conversation_judge_variances) if conversation_judge_variances else 0.0
                    )
                    observed_between_variances.append(observed_between)
                    within_judge_variances.append(within_judge)
                    estimated_generation_variances.append(
                        max(0.0, observed_between - within_judge / len(JUDGE_IDS))
                    )
            pooled_ensemble_values = [
                float(record["metrics"][metric])
                for scenario in SCENARIO_IDS
                for record in target_records
                if record["scenario_id"] == scenario and record["metrics"].get(metric) is not None
            ]
            target_result[metric] = {
                "method": "random_effects_method_of_moments_on_judge_specific_conversation_scores",
                "observed_between_conversation_variance_points_squared": None
                if not observed_between_variances
                else round(mean(observed_between_variances), 6),
                "within_conversation_between_judge_variance_points_squared": None
                if not within_judge_variances
                else round(mean(within_judge_variances), 6),
                "estimated_generation_variance_points_squared": None
                if not estimated_generation_variances
                else round(mean(estimated_generation_variances), 6),
                "ensemble_conversation_values": len(pooled_ensemble_values),
            }
        results[target] = target_result
    return results


def _judge_analysis(records: Sequence[Mapping[str, Any]], disagreements: Mapping[str, Any]) -> dict[str, Any]:
    def with_order(points: Mapping[str, Mapping[str, float]]) -> dict[str, Any]:
        order = sorted(
            TARGET_IDS,
            key=lambda target: (
                -points[target]["major_free_rate"],
                points[target]["major_violation_rate"],
                -points[target]["challenge_rp_summary"],
                target,
            ),
        )
        return {"point_order": order, "model_results": points}

    judge_specific = {}
    leave_one_out = {}
    for judge in JUDGE_IDS:
        judge_specific[judge] = with_order(
            _point_estimates(_variant_records(records, "judge_specific", judge))
        )
        leave_one_out[judge] = with_order(
            _point_estimates(_variant_records(records, "leave_one_out", judge))
        )
    return {
        "ensemble_is_ground_truth": False,
        "judge_specific_model_results": judge_specific,
        "leave_one_judge_out_model_results": leave_one_out,
        "variance_components": _variance_components(records),
        "disagreements": disagreements,
    }


def sample_extension_decision(
    points: Mapping[str, Mapping[str, float]],
    pairwise: Sequence[Mapping[str, Any]],
    rank_analysis: Mapping[str, Any],
) -> dict[str, Any]:
    best_summary = max(values["challenge_rp_summary"] for values in points.values())
    top_set = sorted(
        target
        for target in TARGET_IDS
        if rank_analysis["models"][target]["rank_probabilities"]["1"] >= 0.20
        or points[target]["challenge_rp_summary"] >= best_summary - 3.0
    )
    relevant_pairs = {frozenset(pair) for pair in itertools.combinations(top_set, 2)}
    triggers = []
    for comparison in pairwise:
        metric = comparison["metric"]
        if metric not in {"challenge_rp_summary", "major_free_rate"}:
            continue
        if frozenset((comparison["model_a"], comparison["model_b"])) not in relevant_pairs:
            continue
        lower, upper = comparison["confidence_interval_95"]
        bound = 3.0 if metric == "challenge_rp_summary" else 10.0
        if lower <= 0.0 <= upper and (lower < -bound or upper > bound):
            triggers.append(
                {
                    "metric": metric,
                    "model_a": comparison["model_a"],
                    "model_b": comparison["model_b"],
                    "confidence_interval_95": comparison["confidence_interval_95"],
                    "registered_bound": bound,
                }
            )
    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "evaluated_after_complete_blocks": 10,
        "top_decision_set": top_set,
        "triggered_pairs": triggers,
        "extend": len(top_set) >= 2 and bool(triggers),
        "extension_if_authorized": "all 8 targets x all 6 scenarios through block 20; no selective extension",
        "api_calls_started": False,
    }


def _model_results(
    records: Sequence[Mapping[str, Any]],
    points: Mapping[str, Mapping[str, float]],
    bootstrap: Mapping[str, Mapping[str, Sequence[float]]],
    ranks: Mapping[str, Any],
) -> dict[str, Any]:
    results = {}
    for target in TARGET_IDS:
        target_records = [record for record in records if record["target_id"] == target]
        metrics = {}
        for metric in METRICS:
            raw_values = [
                float(record["metrics"][metric])
                for record in target_records
                if record["metrics"].get(metric) is not None
            ]
            metrics[metric] = {
                "scenario_macro_mean": round(points[target][metric], 6),
                "conversation_median": round(median(raw_values), 6),
                "pooled_within_scenario_standard_deviation": round(
                    math.sqrt(
                        mean(
                            variance(
                                float(record["metrics"][metric])
                                for record in target_records
                                if record["scenario_id"] == scenario
                                and record["metrics"].get(metric) is not None
                            )
                            for scenario in SCENARIO_IDS
                            if sum(
                                record["scenario_id"] == scenario
                                and record["metrics"].get(metric) is not None
                                for record in target_records
                            )
                            > 1
                        )
                    ),
                    6,
                ),
                "confidence_interval_95": _interval(bootstrap[target][metric], 0.95),
            }
        results[target] = {
            "display_name": DISPLAY_NAMES[target],
            "n_conversations": len(target_records),
            "metrics": metrics,
            **ranks["models"][target],
        }
    return results


def _markdown_report(analysis: Mapping[str, Any], decision: Mapping[str, Any]) -> str:
    rows = []
    for target in analysis["rank_analysis"]["point_order"]:
        result = analysis["model_results"][target]
        metric = result["metrics"]
        rows.append(
            "| {rank} | {name} | {major_free:.1f} | {major_rate:.1f} | {summary:.2f} "
            "[{summary_low:.2f}, {summary_high:.2f}] | {rank_one:.1f}% |".format(
                rank=result["point_rank"],
                name=result["display_name"],
                major_free=metric["major_free_rate"]["scenario_macro_mean"],
                major_rate=metric["major_violation_rate"]["scenario_macro_mean"],
                summary=metric["challenge_rp_summary"]["scenario_macro_mean"],
                summary_low=metric["challenge_rp_summary"]["confidence_interval_95"][0],
                summary_high=metric["challenge_rp_summary"]["confidence_interval_95"][1],
                rank_one=result["rank_probabilities"]["1"] * 100.0,
            )
        )
    pairwise = analysis["pairwise_comparisons"]
    conclusions = Counter(row["conclusion"] for row in pairwise)
    judge = analysis["judge_analysis"]["disagreements"]
    leave_one_out = analysis["judge_analysis"]["leave_one_judge_out_model_results"]
    leave_one_out_lines = [
        f"- `{judge_id}`を除外: {DISPLAY_NAMES[value['point_order'][0]]}が点順位1位"
        for judge_id, value in leave_one_out.items()
    ]
    extension_text = (
        "事前登録条件が発火しました。追加する場合は全8モデル・全6シナリオを同時に20生成へ増やします。"
        if decision["extend"]
        else "事前登録した10→20生成の追加条件は発火しませんでした。"
    )
    return f"""# OpenCode Go Challenge反復評価 解析結果（2026-07-28）

> **最初に読む注意:** これは固定したChallenge 6シナリオだけの反復評価です。日本語ロールプレイ
> 全般の総合ランキングではなく、現行の正式Leaderboard、Base 30設定、将来のBase結果とは
> 混ぜません。また、3 Judgeの平均を人間の正解とは扱っていません。

## 結論

登録済みの480会話を独立標本として、10,000回の階層bootstrap、Judge別解析、Major率、
順位確率、8モデル全28ペアの指標別Holm補正を完了しました。ターンや同じ回答への3 Judge判定を
独立標本として水増ししていません。

{extension_text} この解析からAPI呼び出しは開始していません。

## Challenge限定の点推定と不確実性

`Major率`は100会話あたりのMajor判定数で、複数Majorがある会話では100を超え得ます。
`Major-free`はMajorが一つもない会話の割合です。順位はMajor-free、Major率、Challenge RP Summaryの
順で決め、順位確率では同順位の確率を公平に分けています。

| 点順位 | モデル | Major-free (%) | Major率 (/100会話) | Challenge RP Summary (95% CI) | 1位確率 |
|---:|---|---:|---:|---:|---:|
{chr(10).join(rows)}

## 比較判定

連続スコア3点、率10ポイントを最小実用差とし、統計差のHolm補正後p値、95%区間、実用差を
すべて満たした場合だけ「優位」としました。同等は90%区間が実用差の範囲へ完全に入り、
Holm補正後の同等性検定も通った場合だけです。

- 優位: {conclusions['model_a_superior'] + conclusions['model_b_superior']} / {len(pairwise)} 指標別ペア
- 登録範囲内で同等: {conclusions['equivalent_within_registered_bounds']} / {len(pairwise)} 指標別ペア
- 判定困難: {conclusions['indeterminate']} / {len(pairwise)} 指標別ペア

指標別の全比較は解析成果物`pairwise-comparisons.jsonl`に保存しています。

## Judge差

- 大きな不一致（passとfailが混在）: {judge['severe_disagreements']}ルール判定
- 大きな不一致を含む会話: {judge['conversations_with_severe_disagreement']} / 480
- Judge単独集計、全対象共通のleave-one-judge-out、Judgeペア別一致率を`judge-analysis.json`へ保存

{chr(10).join(leave_one_out_lines)}

Judge差は「どのJudgeが正しいか」の判定ではありません。3 Judgeを一つずつ外したときに、
全モデルの値や順位解釈がどの程度変わるかを確認する感度解析です。

## 方法

- 独立標本: 会話（8モデル × 6シナリオ × 10生成）
- 階層bootstrap: blockとシナリオを同じ抽出で全モデルへ適用するpaired bootstrap、10,000回
- Role Fidelity、Quality、Persona Stability、Major/Major-free: 6シナリオのマクロ平均
- Robustness、Recovery: Probeを持つ4シナリオだけのマクロ平均
- Challenge RP Summary: 上記5連続指標のモデル単位マクロ平均
- 多重比較: 各指標の28モデルペアを一つのfamilyとしてHolm補正
- 分散分解: Judge単独スコアのランダム効果法で、会話間分散からJudge分散/3を差し引く
- 同等性: 登録範囲に対する90%区間と、bootstrap標準誤差によるTOSTのHolm補正

完全な機械可読結果、会話単位の整理表、シナリオ別10生成統計、Judge差、追加標本判定は
`tmp/opencode-challenge-repeatability-20260727-v1/analysis-10-blocks/`にあります。
"""


def analyze(
    repo: Path,
    plan_path: Path,
    output: Path,
    analysis_output: Path,
    document_path: Path | None = None,
) -> dict[str, Any]:
    plan = _read_json(plan_path)
    integrity = _validate_analysis_source(output, plan_path, plan)
    records, disagreements = _load_records(repo, output, plan)
    analysis_config = plan["analysis"]
    replicates = int(analysis_config["bootstrap"]["replicates"])
    seed = int(analysis_config["bootstrap"]["seed"])
    points = _point_estimates(records)
    bootstrap = _bootstrap_estimates(records, replicates, seed)
    pairwise = _pairwise_comparisons(points, bootstrap, plan)
    ranks = _rank_analysis(points, bootstrap)
    judge_analysis = _judge_analysis(records, disagreements)
    model_results = _model_results(records, points, bootstrap, ranks)
    decision = sample_extension_decision(points, pairwise, ranks)
    cell_statistics = _cell_statistics(records, replicates, seed)
    analysis_fingerprint = _sha256_json(
        {
            "experiment_fingerprint": integrity["experiment_fingerprint"],
            "plan_sha256": integrity["plan_sha256"],
            "completeness_report_sha256": integrity["completeness_report_sha256"],
            "analysis": analysis_config,
        }
    )
    result = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "created_at": _now(),
        "analysis_fingerprint": analysis_fingerprint,
        "scope": "challenge_repeatability_track_only",
        "ensemble_is_ground_truth": False,
        "integrity": integrity,
        "definitions": {
            "independent_sample_unit": "conversation",
            "major_violation_rate": "Major findings per 100 conversations; may exceed 100",
            "major_free_rate": "percentage of conversations with zero Major findings",
            "bootstrap": analysis_config["bootstrap"],
            "minimum_practical_difference": analysis_config["minimum_practical_difference"],
            "multiple_comparisons": analysis_config["multiple_comparisons"],
        },
        "model_results": model_results,
        "rank_analysis": ranks,
        "pairwise_comparisons": pairwise,
        "judge_analysis": judge_analysis,
        "sample_extension_decision": decision,
    }
    analysis_output.mkdir(parents=True, exist_ok=True)
    _write_json(analysis_output / "analysis.json", result)
    _write_jsonl(analysis_output / "conversation-metrics.jsonl", records)
    _write_json(analysis_output / "model-scenario-statistics.json", cell_statistics)
    _write_jsonl(analysis_output / "pairwise-comparisons.jsonl", pairwise)
    _write_json(analysis_output / "judge-analysis.json", judge_analysis)
    _write_json(analysis_output / "sample-extension-decision.json", decision)
    report = _markdown_report(result, decision)
    (analysis_output / "report.md").write_text(report, encoding="utf-8")
    if document_path is not None:
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(report, encoding="utf-8")
    artifact_paths = sorted(
        path
        for path in analysis_output.iterdir()
        if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "created_at": _now(),
        "analysis_fingerprint": analysis_fingerprint,
        "source_integrity": integrity,
        "artifacts": {
            path.name: {"sha256": _sha256_file(path), "bytes": path.stat().st_size}
            for path in artifact_paths
        },
        "document": None
        if document_path is None
        else {"path": str(document_path), "sha256": _sha256_file(document_path)},
    }
    _write_json(analysis_output / "manifest.json", manifest)
    return result
