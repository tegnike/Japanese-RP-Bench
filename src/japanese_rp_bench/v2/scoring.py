"""Aggregate deterministic checks and multiple independent LLM judges."""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from japanese_rp_bench.v2.judge import QUALITY_DIMENSIONS
from japanese_rp_bench.v2.rules import evaluate_deterministic_rules
from japanese_rp_bench.v2.schemas import (
    AtomicRule,
    Conversation,
    JudgeEvaluation,
    ProbeKind,
    RoleDefinition,
    RolePack,
    RuleFinding,
    ScenarioDefinition,
    Severity,
    Verdict,
)


def score_conversation(
    role_pack: RolePack,
    conversation: Conversation,
    judge_evaluations: Sequence[JudgeEvaluation] = (),
    minimum_judges: int = 2,
) -> Dict[str, Any]:
    if minimum_judges < 1:
        raise ValueError("minimum_judges must be at least 1")
    role, scenario = resolve_conversation(role_pack, conversation)
    evaluations_by_turn: Dict[int, List[JudgeEvaluation]] = defaultdict(list)
    seen_evaluations = set()
    for evaluation in judge_evaluations:
        if evaluation.turn < 1 or evaluation.turn > len(conversation.turns):
            raise ValueError(f"Judge evaluation turn is out of range: {evaluation.turn}")
        missing_dimensions = sorted(set(QUALITY_DIMENSIONS) - set(evaluation.quality_scores))
        if missing_dimensions:
            raise ValueError(
                f"Judge {evaluation.judge_id} is missing quality dimensions: {missing_dimensions}"
            )
        evaluation_key = (evaluation.judge_id, evaluation.turn)
        if evaluation_key in seen_evaluations:
            raise ValueError(
                f"Duplicate judge evaluation: {evaluation.judge_id} at turn {evaluation.turn}"
            )
        seen_evaluations.add(evaluation_key)
        evaluations_by_turn[evaluation.turn].append(evaluation)
    if judge_evaluations:
        for turn in conversation.turns:
            judge_count = len(evaluations_by_turn.get(turn.index, []))
            if judge_count < minimum_judges:
                raise ValueError(
                    f"Turn {turn.index} has {judge_count} judges; at least {minimum_judges} are required"
                )

    turn_reports: List[Dict[str, Any]] = []
    all_aggregated_findings: List[RuleFinding] = []
    all_deterministic_findings: List[RuleFinding] = []
    all_judge_findings: List[RuleFinding] = []
    quality_values: Dict[str, List[float]] = defaultdict(list)
    disagreement_count = 0

    for turn in conversation.turns:
        deterministic = evaluate_deterministic_rules(role, turn.assistant, turn.index)
        aggregated_judge, disagreements = _aggregate_judges(
            role,
            turn.index,
            evaluations_by_turn.get(turn.index, []),
        )
        disagreement_count += len(disagreements)
        combined = deterministic + aggregated_judge
        all_deterministic_findings.extend(deterministic)
        all_judge_findings.extend(aggregated_judge)
        all_aggregated_findings.extend(combined)

        for evaluation in evaluations_by_turn.get(turn.index, []):
            for dimension, value in evaluation.quality_scores.items():
                quality_values[dimension].append(value)

        turn_reports.append(
            {
                "turn": turn.index,
                "fidelity_score": _findings_score(combined),
                "major_violations": sum(
                    finding.severity is Severity.MAJOR and finding.verdict is Verdict.FAIL
                    for finding in combined
                ),
                "judge_disagreements": disagreements,
                "findings": [finding.to_dict() for finding in combined],
            }
        )

    turn_scores = [report["fidelity_score"] for report in turn_reports if report["fidelity_score"] is not None]
    drift_points = _drift_points(turn_scores)
    probe_scores = _score_probes(scenario, turn_reports)
    quality_scores = {
        dimension: round(mean(values), 3) for dimension, values in quality_values.items() if values
    }
    quality_score = None
    if quality_scores:
        quality_score = round(mean((value - 1.0) / 4.0 * 100.0 for value in quality_scores.values()), 3)

    major_violations = sum(
        finding.severity is Severity.MAJOR and finding.verdict is Verdict.FAIL
        for finding in all_aggregated_findings
    )
    summary = {
        "core_fidelity_score": _findings_score(all_aggregated_findings),
        "deterministic_compliance_score": _findings_score(all_deterministic_findings),
        "judge_fidelity_score": _findings_score(all_judge_findings),
        "conversation_quality_score": quality_score,
        "quality_dimensions": quality_scores,
        "major_violations": major_violations,
        "eligible_for_overall": major_violations == 0,
        "drift_points": drift_points,
        "long_term_stability_score": None
        if drift_points is None
        else round(max(0.0, 100.0 + min(0.0, drift_points)), 3),
        "robustness_score": _mean_probe_score(probe_scores, ProbeKind.ADVERSARIAL),
        "recovery_score": _mean_probe_score(probe_scores, ProbeKind.RECOVERY),
        "judge_disagreements": disagreement_count,
        "judges": sorted({evaluation.judge_id for evaluation in judge_evaluations}),
    }
    return {
        "schema_version": "2.0",
        "role_pack": {"id": role_pack.id, "version": role_pack.version},
        "role_id": role.id,
        "scenario_id": scenario.id,
        "track": scenario.track,
        "target_model": conversation.target_model,
        "summary": summary,
        "probes": probe_scores,
        "turns": turn_reports,
    }


def resolve_conversation(
    role_pack: RolePack, conversation: Conversation
) -> Tuple[RoleDefinition, ScenarioDefinition]:
    if conversation.role_id not in role_pack.roles:
        raise ValueError(f"Conversation references unknown role: {conversation.role_id}")
    if conversation.scenario_id not in role_pack.scenarios:
        raise ValueError(f"Conversation references unknown scenario: {conversation.scenario_id}")
    role = role_pack.roles[conversation.role_id]
    scenario = role_pack.scenarios[conversation.scenario_id]
    if scenario.role_id != role.id:
        raise ValueError(f"Scenario {scenario.id} does not belong to role {role.id}")
    if len(conversation.turns) > len(scenario.user_messages):
        raise ValueError(
            f"Conversation has {len(conversation.turns)} turns but scenario only defines {len(scenario.user_messages)}"
        )
    if scenario.mode == "scripted":
        for turn, expected_message in zip(conversation.turns, scenario.user_messages):
            if turn.user != expected_message:
                raise ValueError(
                    f"Conversation user message at turn {turn.index} does not match the scripted scenario"
                )
    return role, scenario


def _aggregate_judges(
    role: RoleDefinition,
    turn: int,
    evaluations: Sequence[JudgeEvaluation],
) -> Tuple[List[RuleFinding], List[str]]:
    if not evaluations:
        return [], []

    expected = {rule.id for rule in role.judge_rules}
    by_rule: Dict[str, List[RuleFinding]] = defaultdict(list)
    for evaluation in evaluations:
        covered = {finding.rule_id for finding in evaluation.findings}
        if covered != expected or len(evaluation.findings) != len(expected):
            raise ValueError(
                f"Judge {evaluation.judge_id} did not cover every judge rule at turn {turn}"
            )
        for finding in evaluation.findings:
            by_rule[finding.rule_id].append(finding)

    rule_map = {rule.id: rule for rule in role.judge_rules}
    results: List[RuleFinding] = []
    disagreements: List[str] = []
    for rule_id in sorted(by_rule):
        findings = by_rule[rule_id]
        scores = [finding.verdict.score for finding in findings if finding.verdict.score is not None]
        if not scores:
            verdict = Verdict.NOT_APPLICABLE
            score_range = 0.0
        else:
            score = mean(scores)
            verdict = Verdict.PASS if score >= 0.75 else Verdict.PARTIAL if score >= 0.4 else Verdict.FAIL
            score_range = max(scores) - min(scores)
        if score_range >= 0.75:
            disagreements.append(rule_id)
        evidence = " | ".join(
            f"{finding.judge_id}: {finding.evidence}" for finding in findings if finding.evidence
        )
        rationale = " | ".join(
            f"{finding.judge_id}: {finding.rationale}" for finding in findings if finding.rationale
        )
        results.append(
            RuleFinding(
                rule_id=rule_id,
                verdict=verdict,
                severity=rule_map[rule_id].severity,
                source="judge_ensemble",
                turn=turn,
                confidence=round(mean(finding.confidence for finding in findings), 3),
                evidence=evidence,
                rationale=rationale,
            )
        )
    return results, disagreements


def _findings_score(findings: Iterable[RuleFinding]) -> Optional[float]:
    values = [finding.verdict.score for finding in findings if finding.verdict.score is not None]
    if not values:
        return None
    return round(mean(values) * 100.0, 3)


def _drift_points(turn_scores: Sequence[float]) -> Optional[float]:
    if len(turn_scores) < 2:
        return None
    window = max(1, math.ceil(len(turn_scores) * 0.2))
    return round(mean(turn_scores[-window:]) - mean(turn_scores[:window]), 3)


def _score_probes(
    scenario: ScenarioDefinition,
    turn_reports: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    reports_by_turn = {int(report["turn"]): report for report in turn_reports}
    results: List[Dict[str, Any]] = []
    for probe in scenario.probes:
        report = reports_by_turn.get(probe.turn)
        finding_scores: List[float] = []
        if report:
            for finding in report["findings"]:
                if finding["rule_id"] in probe.rule_ids:
                    score = Verdict(finding["verdict"]).score
                    if score is not None:
                        finding_scores.append(score)
        results.append(
            {
                "id": probe.id,
                "kind": probe.kind.value,
                "turn": probe.turn,
                "rule_ids": list(probe.rule_ids),
                "score": None if not finding_scores else round(mean(finding_scores) * 100.0, 3),
            }
        )
    return results


def _mean_probe_score(probes: Sequence[Mapping[str, Any]], kind: ProbeKind) -> Optional[float]:
    scores = [probe["score"] for probe in probes if probe["kind"] == kind.value and probe["score"] is not None]
    return None if not scores else round(mean(scores), 3)
