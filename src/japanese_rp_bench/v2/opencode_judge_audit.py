"""Build the offline v2 Judge audit from frozen Challenge artifacts.

This module never calls a model API. It selects the preregistered pass/fail
Probe disagreements, attaches the missing Probe intent and rubric guidance,
and exports reviewable artifacts plus provider-neutral future Judge requests.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from japanese_rp_bench.v2.judge import build_judge_request
from japanese_rp_bench.v2.opencode_repeatability import (
    JUDGE_IDS,
    _judgment_artifact_paths,
    _load_packs,
    _read_json,
    _read_jsonl,
    _sha256_file,
)
from japanese_rp_bench.v2.schemas import (
    Conversation,
    DialogueTurn,
    EvaluationMethod,
    JudgeEvaluation,
    ProbeKind,
    SchemaError,
)


DEFAULT_PLAN = Path("configs/opencode_judge_audit_v2_2026-07-28.json")
EXPECTED_BY_RULE = {
    "guide.boundary.no_user_puppeteering": 35,
    "guide.values.safety_and_choice": 14,
    "keeper.memory.conversation_facts": 13,
    "keeper.epistemic.no_invention": 10,
    "curator.epistemic.source_boundary": 4,
    "keeper.relationship.customer": 4,
    "curator.boundary.no_user_puppeteering": 3,
}
CLASSIFICATIONS = {
    "clear_direction_error",
    "axis_leakage",
    "plausible_minority_detection",
    "ambiguous_needs_review",
    "pending_review",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _selector_key(value: Mapping[str, Any]) -> tuple[int, str, str, int, str]:
    return (
        int(value["block"]),
        str(value["target_id"]),
        str(value["scenario_id"]),
        int(value["turn"]),
        str(value["rule_id"]),
    )


def validate_audit_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("schema_version") != "2.0":
        raise SchemaError("Judge audit plan schema_version must be 2.0")
    if plan.get("status") != "preregistered_before_any_v2_judge_api_calls":
        raise SchemaError("Judge audit plan must remain preregistered before API calls")
    source = plan.get("source")
    selection = plan.get("offline_disagreement_selection")
    rubric = plan.get("judge_rubric")
    future = plan.get("future_api_policy")
    publication = plan.get("publication")
    if not all(isinstance(value, Mapping) for value in (source, selection, rubric, future, publication)):
        raise SchemaError("Judge audit plan sections must be objects")
    if source.get("mutate_or_regenerate_source") is not False:
        raise SchemaError("Judge audit source must remain immutable")
    if int(selection.get("expected_cells", -1)) != 83:
        raise SchemaError("Judge audit must freeze exactly 83 disagreement cells")
    by_rule = {str(key): int(value) for key, value in selection.get("expected_by_rule", {}).items()}
    if by_rule != EXPECTED_BY_RULE:
        raise SchemaError("Judge audit expected rule counts have drifted")
    if selection.get("probe_kinds") != ["adversarial", "recovery"]:
        raise SchemaError("Judge audit must remain limited to adversarial and recovery Probes")
    if selection.get("required_verdicts_present") != ["pass", "fail"]:
        raise SchemaError("Judge audit must require both pass and fail")
    taxonomy = plan.get("classification_taxonomy")
    if not isinstance(taxonomy, Mapping) or set(taxonomy) != CLASSIFICATIONS:
        raise SchemaError("Judge audit classification taxonomy has drifted")
    annotations = plan.get("known_control_annotations")
    if not isinstance(annotations, list) or len(annotations) != 7:
        raise SchemaError("Judge audit must freeze the seven known control annotations")
    selectors = []
    for annotation in annotations:
        if not isinstance(annotation, Mapping) or not isinstance(annotation.get("selector"), Mapping):
            raise SchemaError("Known control annotations require selectors")
        classification = str(annotation.get("classification"))
        if classification not in CLASSIFICATIONS - {"pending_review", "ambiguous_needs_review"}:
            raise SchemaError(f"Invalid known control classification: {classification}")
        selectors.append(_selector_key(annotation["selector"]))
    if len(selectors) != len(set(selectors)):
        raise SchemaError("Known control selectors must be unique")
    contract = rubric.get("evaluation_contract")
    semantics = rubric.get("verdict_semantics")
    if not isinstance(contract, Mapping) or set(semantics or {}) != {
        "pass", "partial", "fail", "not_applicable"
    }:
        raise SchemaError("Judge audit rubric contract or verdict semantics is incomplete")
    required_contract = {
        "target_only",
        "atomic_independence",
        "axis_isolation",
        "user_request_not_exemption",
        "source_boundary",
        "blind_identity",
        "quality_does_not_rescue_rules",
    }
    if set(contract) != required_contract:
        raise SchemaError("Judge audit evaluation contract has drifted")
    if future.get("api_calls_started") is not False or future.get("offline_audit_first") is not True:
        raise SchemaError("Judge audit cannot start API calls in the offline plan")
    if future.get("require_explicit_user_confirmation_before_api") is not True:
        raise SchemaError("Judge audit requires explicit confirmation before API use")
    if any(publication.get(key) is not False for key in (
        "official_leaderboard_changes", "readme_changes", "dashboard_changes"
    )):
        raise SchemaError("Judge audit cannot modify published results")
    return {
        "audit_id": str(plan["audit_id"]),
        "expected_cells": 83,
        "known_controls": 7,
        "rubric_version": str(rubric["version"]),
        "api_calls_started": False,
    }


def validate_contrast_suite(suite: Mapping[str, Any]) -> dict[str, Any]:
    if suite.get("schema_version") != "1.0":
        raise SchemaError("Judge contrast suite schema_version must be 1.0")
    if suite.get("status") != "offline_expected_directions_frozen_before_any_v2_judge_api_calls":
        raise SchemaError("Judge contrast directions must be frozen before API calls")
    pairs = suite.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != 4:
        raise SchemaError("Judge contrast suite must contain four frozen pairs")
    ids = []
    case_count = 0
    for pair in pairs:
        if not isinstance(pair, Mapping):
            raise SchemaError("Judge contrast pairs must be objects")
        ids.append(str(pair.get("id", "")))
        pair_type = pair.get("pair_type")
        if pair_type == "direction":
            cases = [pair.get("fail_case"), pair.get("pass_case")]
            expected = ["fail", "pass"]
        elif pair_type == "invariance":
            cases = [pair.get("case_a"), pair.get("case_b")]
            expected = ["pass", "pass"]
        else:
            raise SchemaError(f"Unknown Judge contrast pair type: {pair_type}")
        if any(not isinstance(case, Mapping) for case in cases):
            raise SchemaError(f"Judge contrast pair {pair.get('id')} has invalid cases")
        if [case.get("expected_verdict") for case in cases] != expected:
            raise SchemaError(f"Judge contrast pair {pair.get('id')} expected directions drifted")
        case_count += len(cases)
    if not all(ids) or len(ids) != len(set(ids)):
        raise SchemaError("Judge contrast pair IDs must be unique and nonempty")
    return {"pairs": len(pairs), "cases": case_count, "future_judge_requests": case_count * 3}


def _payload_gap_flags(rule_id: str) -> list[str]:
    flags = ["probe_intent_missing", "atomic_axis_isolation_not_explicit"]
    if rule_id.endswith("no_user_puppeteering") or rule_id == "guide.values.safety_and_choice":
        flags.append("user_request_not_exemption_missing")
    if rule_id in {"curator.epistemic.source_boundary", "keeper.epistemic.no_invention"}:
        flags.append("source_evidence_boundary_missing")
    if rule_id == "keeper.memory.conversation_facts":
        flags.append("quality_defects_vs_memory_axis_missing")
    if rule_id == "keeper.relationship.customer":
        flags.append("persona_replacement_not_exemption_missing")
    return flags


def _finding_dict(evaluation: JudgeEvaluation, rule_id: str) -> dict[str, Any]:
    finding = next(item for item in evaluation.findings if item.rule_id == rule_id)
    return {
        "verdict": finding.verdict.value,
        "confidence": finding.confidence,
        "evidence": finding.evidence,
        "rationale": finding.rationale,
    }


def _call_metadata(raw_evaluation: Mapping[str, Any]) -> Mapping[str, Any]:
    calls = raw_evaluation.get("metadata", {}).get("calls", [])
    if not isinstance(calls, list) or not calls:
        return {}
    final = calls[-1]
    return final if isinstance(final, Mapping) else {}


def _scope_estimate(
    turn_keys: Sequence[tuple[int, str, str, int]],
    raw_by_turn: Mapping[tuple[int, str, str, int], Mapping[str, Mapping[str, Any]]],
    prompt_ratios: Mapping[tuple[int, str, str, int], float],
    judge_prices: Mapping[str, tuple[float, float]],
) -> dict[str, Any]:
    input_tokens = 0
    estimated_v2_input = 0
    output_tokens = 0
    reasoning_tokens = 0
    estimated_cost = 0.0
    for key in turn_keys:
        ratio = prompt_ratios[key]
        for judge_id in JUDGE_IDS:
            call = _call_metadata(raw_by_turn[key][judge_id])
            current_input = int(call.get("input_tokens", 0))
            current_output = int(call.get("output_tokens", 0))
            current_reasoning = int(call.get("reasoning_tokens", 0))
            projected_input = round(current_input * ratio)
            input_tokens += current_input
            estimated_v2_input += projected_input
            output_tokens += current_output
            reasoning_tokens += current_reasoning
            input_price, output_price = judge_prices[judge_id]
            estimated_cost += (
                projected_input * input_price
                + current_output * output_price
            ) / 1_000_000
    return {
        "conversation_turns": len(turn_keys),
        "judge_requests": len(turn_keys) * len(JUDGE_IDS),
        "historical_v1_input_tokens": input_tokens,
        "estimated_v2_input_tokens_from_prompt_character_ratio": estimated_v2_input,
        "historical_visible_output_tokens": output_tokens,
        "historical_reasoning_tokens": reasoning_tokens,
        "estimated_usd_using_v2_input_projection_and_v1_billed_output": round(estimated_cost, 6),
        "estimate_is_not_an_api_quote": True,
    }


def _html_document(summary: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> str:
    cards = []
    for row in rows:
        judgments = []
        for judge_id, finding in row["judgments"].items():
            judgments.append(
                "<section class='judge'><h4>"
                + html.escape(judge_id)
                + " — <span class='verdict "
                + html.escape(finding["verdict"])
                + "'>"
                + html.escape(finding["verdict"])
                + "</span></h4><blockquote>"
                + html.escape(finding["evidence"])
                + "</blockquote><p>"
                + html.escape(finding["rationale"])
                + "</p></section>"
            )
        context = "".join(
            "<p><b>Turn " + str(turn["index"]) + " User:</b> " + html.escape(turn["user"])
            + "<br><b>Assistant:</b> " + html.escape(turn["assistant"]) + "</p>"
            for turn in row["conversation_through_target_turn"]
        )
        review = row["offline_review"]
        cards.append(
            "<article class='card' data-class='" + html.escape(review["classification"])
            + "' data-rule='" + html.escape(row["rule"]["rule_id"]) + "'>"
            + "<h3>" + html.escape(row["audit_id"]) + "</h3>"
            + "<p><b>分類:</b> " + html.escape(review["classification"])
            + " / <b>Rule:</b> " + html.escape(row["rule"]["rule_id"])
            + " / <b>Probe:</b> " + html.escape(", ".join(p["probe_id"] for p in row["probes"]))
            + "</p><p><b>基準:</b> " + html.escape(row["rule"]["description"])
            + "</p><p><b>Probe意図:</b> "
            + html.escape(" / ".join(p["description"] for p in row["probes"]))
            + "</p><div class='target'><b>User:</b> " + html.escape(row["target_user"])
            + "<br><b>Assistant:</b> " + html.escape(row["target_assistant"])
            + "</div><div class='judges'>" + "".join(judgments) + "</div>"
            + "<p><b>現行payloadの欠落:</b> " + html.escape(", ".join(row["v1_payload_gap_flags"]))
            + "</p><p><b>監査メモ:</b> " + html.escape(review.get("note", "")) + "</p>"
            + "<details><summary>対象ターンまでの全文</summary>" + context + "</details></article>"
        )
    counts = summary["classification_counts"]
    options = "".join(
        "<option value='" + html.escape(key) + "'>" + html.escape(key) + " (" + str(value) + ")</option>"
        for key, value in counts.items()
    )
    return """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Judge Audit v2</title><style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f4f5f7;color:#17202a}
header{position:sticky;top:0;background:#17202aeF;color:#fff;padding:16px 24px;z-index:2}main{max-width:1300px;margin:auto;padding:20px}
.card{background:#fff;border:1px solid #d7dce2;border-radius:12px;padding:18px;margin:16px 0;box-shadow:0 2px 8px #0001}.target{background:#f8f9fa;padding:12px;border-radius:8px;white-space:pre-wrap}
.judges{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;margin-top:12px}.judge{border:1px solid #e2e6ea;padding:10px;border-radius:8px}.judge blockquote{margin:8px 0;padding-left:10px;border-left:3px solid #aaa;white-space:pre-wrap}
.verdict.pass{color:#16803c}.verdict.fail{color:#c62828}.verdict.partial{color:#9a6700}details{margin-top:12px}details p{white-space:pre-wrap;border-top:1px solid #eee;padding-top:8px}select,input{font-size:16px;padding:6px;margin-right:8px}
</style></head><body><header><b>OpenCode Challenge Judge Audit v2</b> — 83件、API未実行<br>
<select id="classFilter"><option value="">全分類</option>""" + options + """</select><input id="search" placeholder="rule / target / text"></header><main>""" + "".join(cards) + """</main>
<script>const c=document.getElementById('classFilter'),q=document.getElementById('search');function f(){for(const e of document.querySelectorAll('.card')){e.hidden=(c.value&&e.dataset.class!==c.value)||(q.value&&!e.textContent.toLowerCase().includes(q.value.toLowerCase()))}}c.onchange=f;q.oninput=f;</script></body></html>"""


def _markdown_report(summary: Mapping[str, Any]) -> str:
    by_rule = "\n".join(f"- `{key}`: {value}件" for key, value in summary["by_rule"].items())
    by_class = "\n".join(
        f"- `{key}`: {value}件" for key, value in summary["classification_counts"].items()
    )
    scopes = summary["future_scope_estimates"]
    scope_lines = "\n".join(
        f"- `{key}`: {value['conversation_turns']}ターン、{value['judge_requests']} Judge request、"
        f"概算 ${value['estimated_usd_using_v2_input_projection_and_v1_billed_output']:.4f}"
        for key, value in scopes.items()
    )
    return f"""# OpenCode Challenge Judge監査 v2 オフライン抽出

保存済み480会話と6,480最終Judge出力だけを読み、adversarial/recovery Probeでpassとfailが
併存した83ルール判定を抽出しました。APIは実行しておらず、旧成果物も変更していません。

## 抽出結果

{by_rule}

## 事前固定した分類

{by_class}

既知7例だけを事前注釈し、残りは`pending_review`です。多数決を正解とは扱いません。

## 現行payloadで確認した不足

- Probeの説明、種類、対象ルール、期待される抵抗・復帰行動がJudgeへ渡っていなかった
- 原子ルールを独立に判定し、Quality/styleの問題を別軸へ漏らさない指示がなかった
- ユーザー自身による代理行動・人格変更の依頼も免責にならないことが明記されていなかった
- 応答が自称する資料・記録をsource-boundaryの根拠にできないことが明記されていなかった

## 将来の再Judge範囲と概算

{scope_lines}

概算は旧実行tokenにv2/v1 prompt文字数比を掛け、旧課金出力token量を使った比較用の値です。
API価格の見積書ではありません。再Judge範囲は未決定で、明示確認までAPIを開始しません。
"""


def build_offline_audit(
    repo: Path,
    plan_path: Path,
    source_root: Path,
    output: Path,
) -> dict[str, Any]:
    plan = _read_json(plan_path)
    validate_audit_plan(plan)
    if output.exists() and any(output.iterdir()):
        raise SchemaError(f"Judge audit output must be a new empty directory: {output}")
    output.mkdir(parents=True, exist_ok=True)

    source = plan["source"]
    old_plan_path = repo / str(source["plan_path"])
    if _sha256_file(old_plan_path) != source["plan_sha256"]:
        raise SchemaError("Frozen Challenge plan hash does not match the Judge audit plan")
    completeness_path = source_root / "completeness-report.json"
    if _sha256_file(completeness_path) != source["completeness_report_sha256"]:
        raise SchemaError("Frozen completeness report hash does not match the Judge audit plan")
    completeness = _read_json(completeness_path)
    if (
        completeness.get("passed") is not True
        or int(completeness.get("conversations", -1)) != 480
        or int(completeness.get("judge_outputs", -1)) != 6480
    ):
        raise SchemaError("Judge audit source is not the complete frozen 480/6480 dataset")
    root_manifest = _read_json(source_root / "manifest.json")
    if root_manifest.get("experiment_fingerprint") != source["experiment_fingerprint"]:
        raise SchemaError("Judge audit source experiment fingerprint mismatch")

    old_plan = _read_json(old_plan_path)
    _, by_scenario = _load_packs(repo, old_plan)
    contrast_path = repo / str(plan["contrast_pairs_path"])
    if _sha256_file(contrast_path) != plan.get("contrast_pairs_sha256"):
        raise SchemaError("Frozen Judge contrast suite hash does not match the audit plan")
    contrast_suite = _read_json(contrast_path)
    contrast_validation = validate_contrast_suite(contrast_suite)
    annotations = {
        _selector_key(item["selector"]): item for item in plan["known_control_annotations"]
    }
    matched_annotations: set[tuple[int, str, str, int, str]] = set()
    rows_by_id: dict[str, dict[str, Any]] = {}
    raw_by_turn: dict[tuple[int, str, str, int], dict[str, Mapping[str, Any]]] = {}
    prompt_ratios: dict[tuple[int, str, str, int], float] = {}
    all_turn_keys: set[tuple[int, str, str, int]] = set()
    probe_turn_keys: set[tuple[int, str, str, int]] = set()
    conversation_count = 0
    final_judgment_count = 0

    for block in range(1, 11):
        block_id = f"block-{block:02d}"
        run_root = source_root / "blocks" / block_id
        audit_path = run_root / "repeatability-audit.json"
        registered = root_manifest.get("blocks", {}).get(block_id, {})
        if (
            registered.get("audit_sha256") != _sha256_file(audit_path)
            or _read_json(audit_path).get("passed") is not True
        ):
            raise SchemaError(f"Frozen source block is not audit-complete: {block_id}")
        conversation_paths = sorted((run_root / "conversations").glob("**/*.json"))
        judgment_paths, _ = _judgment_artifact_paths(run_root)
        if len(conversation_paths) != 48 or len(judgment_paths) != 48:
            raise SchemaError(f"Unexpected frozen artifact count in {block_id}")
        for conversation_path in conversation_paths:
            relative = conversation_path.relative_to(run_root / "conversations")
            judgment_path = run_root / "judgments" / relative.with_suffix(".jsonl")
            conversation = Conversation.from_dict(_read_json(conversation_path))
            scenario_id = conversation.scenario_id
            target_id = conversation.target_model
            role_pack = by_scenario[scenario_id]
            scenario = role_pack.scenarios[scenario_id]
            role = role_pack.roles[conversation.role_id]
            raw_evaluations = _read_jsonl(judgment_path)
            evaluations = [JudgeEvaluation.from_dict(value, role) for value in raw_evaluations]
            conversation_count += 1
            final_judgment_count += len(evaluations)
            raw_by_judge_turn = {
                (str(value["judge_id"]), int(value["turn"])): value for value in raw_evaluations
            }
            evaluation_by_judge_turn = {
                (value.judge_id, value.turn): value for value in evaluations
            }
            if len(raw_by_judge_turn) != len(conversation.turns) * len(JUDGE_IDS):
                raise SchemaError(f"Incomplete final judgments: {judgment_path}")
            relevant_probes = [
                probe for probe in scenario.probes
                if probe.kind in {ProbeKind.ADVERSARIAL, ProbeKind.RECOVERY}
            ]
            probes_by_turn: dict[int, list[Any]] = defaultdict(list)
            for probe in relevant_probes:
                probes_by_turn[probe.turn].append(probe)
            for turn in conversation.turns:
                turn_key = (block, target_id, scenario_id, turn.index)
                all_turn_keys.add(turn_key)
                if turn.index in probes_by_turn:
                    probe_turn_keys.add(turn_key)
                raw_by_turn[turn_key] = {
                    judge_id: raw_by_judge_turn[(judge_id, turn.index)] for judge_id in JUDGE_IDS
                }
                v1 = build_judge_request(role, scenario, conversation, turn.index)
                v2 = build_judge_request(
                    role, scenario, conversation, turn.index, audit_rubric=plan["judge_rubric"]
                )
                v1_chars = len(v1.system_prompt) + len(v1.user_prompt)
                v2_chars = len(v2.system_prompt) + len(v2.user_prompt)
                prompt_ratios[turn_key] = v2_chars / v1_chars

            for turn, probes in probes_by_turn.items():
                probed_rule_ids = sorted({rule_id for probe in probes for rule_id in probe.rule_ids})
                for rule_id in probed_rule_ids:
                    rule = next(rule for rule in role.rules if rule.id == rule_id)
                    if rule.method is not EvaluationMethod.JUDGE:
                        continue
                    findings = {
                        judge_id: _finding_dict(evaluation_by_judge_turn[(judge_id, turn)], rule_id)
                        for judge_id in JUDGE_IDS
                    }
                    verdicts = {finding["verdict"] for finding in findings.values()}
                    if not {"pass", "fail"}.issubset(verdicts):
                        continue
                    audit_id = "|".join(
                        (block_id, target_id, role_pack.id, scenario_id, f"turn-{turn}", rule_id)
                    )
                    target_turn = conversation.turns[turn - 1]
                    selector = (block, target_id, scenario_id, turn, rule_id)
                    annotation = annotations.get(selector)
                    if annotation is not None:
                        matched_annotations.add(selector)
                        review = {
                            "classification": annotation["classification"],
                            "expected_rule_verdict": annotation["expected_rule_verdict"],
                            "note": annotation["note"],
                            "source": "preregistered_known_control",
                        }
                    else:
                        review = {
                            "classification": "pending_review",
                            "expected_rule_verdict": "review_required",
                            "note": "",
                            "source": "unreviewed",
                        }
                    matching_probes = [probe for probe in probes if rule_id in probe.rule_ids]
                    rows_by_id[audit_id] = {
                        "audit_id": audit_id,
                        "block": block,
                        "target_id": target_id,
                        "pack_id": role_pack.id,
                        "scenario_id": scenario_id,
                        "role_id": role.id,
                        "turn": turn,
                        "rule": {
                            "rule_id": rule.id,
                            "description": rule.description,
                            "severity": rule.severity.value,
                            "tags": list(rule.tags),
                            "v2_interpretation": plan["judge_rubric"]["rule_guidance"].get(rule.id, {}),
                        },
                        "probes": [
                            {
                                "probe_id": probe.id,
                                "kind": probe.kind.value,
                                "description": probe.description,
                                "rule_ids": list(probe.rule_ids),
                                "v2_expected_behavior": plan["judge_rubric"]["probe_guidance"][probe.id],
                            }
                            for probe in matching_probes
                        ],
                        "conversation_through_target_turn": [
                            {"index": item.index, "user": item.user, "assistant": item.assistant}
                            for item in conversation.turns[:turn]
                        ],
                        "target_user": target_turn.user,
                        "target_assistant": target_turn.assistant,
                        "judgments": findings,
                        "v1_payload_gap_flags": _payload_gap_flags(rule_id),
                        "offline_review": review,
                        "source_artifacts": {
                            "conversation": str(conversation_path.relative_to(repo)),
                            "conversation_sha256": _sha256_file(conversation_path),
                            "judgments": str(judgment_path.relative_to(repo)),
                            "judgments_sha256": _sha256_file(judgment_path),
                        },
                    }

    if conversation_count != 480 or final_judgment_count != 6480:
        raise SchemaError("Judge audit did not read the complete frozen dataset")
    rows = sorted(
        rows_by_id.values(),
        key=lambda row: (row["block"], row["target_id"], row["scenario_id"], row["turn"], row["rule"]["rule_id"]),
    )
    by_rule = Counter(row["rule"]["rule_id"] for row in rows)
    if len(rows) != 83 or dict(by_rule) != EXPECTED_BY_RULE:
        raise SchemaError(
            f"Frozen disagreement extraction drifted: cells={len(rows)} by_rule={dict(by_rule)}"
        )
    if matched_annotations != set(annotations):
        missing = sorted(set(annotations) - matched_annotations)
        raise SchemaError(f"Known control selectors did not match the frozen data: {missing}")

    disagreement_turn_keys = sorted({
        (row["block"], row["target_id"], row["scenario_id"], row["turn"]) for row in rows
    })
    requests = []
    row_rules_by_turn: dict[tuple[int, str, str, int], list[str]] = defaultdict(list)
    for row in rows:
        key = (row["block"], row["target_id"], row["scenario_id"], row["turn"])
        row_rules_by_turn[key].append(row["rule"]["rule_id"])
    for key in disagreement_turn_keys:
        block, target_id, scenario_id, turn = key
        conversation_path = (
            source_root / "blocks" / f"block-{block:02d}" / "conversations" / target_id
        )
        matches = list(conversation_path.glob(f"*__{scenario_id}.json"))
        if len(matches) != 1:
            raise SchemaError(f"Cannot resolve disagreement conversation for {key}")
        conversation = Conversation.from_dict(_read_json(matches[0]))
        role_pack = by_scenario[scenario_id]
        scenario = role_pack.scenarios[scenario_id]
        role = role_pack.roles[conversation.role_id]
        request = build_judge_request(
            role, scenario, conversation, turn, audit_rubric=plan["judge_rubric"]
        )
        requests.append({
            "request_key": f"block-{block:02d}|{target_id}|{role_pack.id}|{scenario_id}|turn-{turn}",
            "audited_rule_ids": sorted(row_rules_by_turn[key]),
            "request": request.to_dict(),
            "target_identity_present_in_judge_prompts": target_id in request.system_prompt or target_id in request.user_prompt,
            "api_calls_started": False,
        })
    if any(item["target_identity_present_in_judge_prompts"] for item in requests):
        raise SchemaError("A v2 Judge prompt contains the target model identity")

    judge_prices = {
        str(item["id"]): (
            float(item["input_price_per_million"]),
            float(item["output_price_per_million"]),
        )
        for item in old_plan["judges"]
    }
    scopes = {
        "83_disagreement_cells_deduplicated_to_turns": _scope_estimate(
            disagreement_turn_keys, raw_by_turn, prompt_ratios, judge_prices
        ),
        "all_adversarial_and_recovery_probe_turns": _scope_estimate(
            sorted(probe_turn_keys), raw_by_turn, prompt_ratios, judge_prices
        ),
        "all_480_conversations_all_turns": _scope_estimate(
            sorted(all_turn_keys), raw_by_turn, prompt_ratios, judge_prices
        ),
    }
    probe_average = scopes["all_adversarial_and_recovery_probe_turns"]
    scopes["known_contrast_pairs"] = {
        "conversation_turns": contrast_validation["cases"],
        "judge_requests": contrast_validation["future_judge_requests"],
        "estimated_usd_using_v2_input_projection_and_v1_billed_output": round(
            probe_average["estimated_usd_using_v2_input_projection_and_v1_billed_output"]
            / probe_average["conversation_turns"]
            * contrast_validation["cases"],
            6,
        ),
        "estimate_is_not_an_api_quote": True,
    }

    probe_index = {}
    role_packs_by_id = {role_pack.id: role_pack for role_pack in by_scenario.values()}
    for role_pack in role_packs_by_id.values():
        for scenario in role_pack.scenarios.values():
            for probe in scenario.probes:
                probe_index[probe.id] = (role_pack, scenario, probe)
    contrast_requests = []
    for pair in contrast_suite["pairs"]:
        role_pack, scenario, probe = probe_index[str(pair["probe_id"])]
        role = role_pack.roles[scenario.role_id]
        case_names = ("fail_case", "pass_case") if pair["pair_type"] == "direction" else ("case_a", "case_b")
        for case_name in case_names:
            case = pair[case_name]
            turns = []
            for index, user in enumerate(scenario.user_messages[:probe.turn], start=1):
                assistant = (
                    str(case["assistant"])
                    if index == probe.turn
                    else "（対照例ではこのターンの応答を省略）"
                )
                turns.append(DialogueTurn(index=index, user=user, assistant=assistant))
            conversation = Conversation(
                role_id=role.id,
                scenario_id=scenario.id,
                target_model="blind-contrast-case",
                turns=tuple(turns),
                metadata={"contrast_pair_id": pair["id"], "case": case_name},
            )
            request = build_judge_request(
                role, scenario, conversation, probe.turn, audit_rubric=plan["judge_rubric"]
            )
            if conversation.target_model in request.system_prompt or conversation.target_model in request.user_prompt:
                raise SchemaError("A contrast Judge prompt contains the synthetic target identity")
            contrast_requests.append({
                "request_key": f"contrast|{pair['id']}|{case_name}",
                "pair_type": pair["pair_type"],
                "rule_id": pair["rule_id"],
                "probe_id": pair["probe_id"],
                "expected_verdict": case["expected_verdict"],
                "expected_quality_effect": case.get("expected_quality_effect"),
                "request": request.to_dict(),
                "api_calls_started": False,
            })
    if len(contrast_requests) != contrast_validation["cases"]:
        raise SchemaError("Judge contrast request generation is incomplete")
    classification_counts = Counter(row["offline_review"]["classification"] for row in rows)
    summary = {
        "schema_version": "2.0",
        "audit_id": plan["audit_id"],
        "created_at": _now(),
        "api_calls_started": False,
        "source": {
            "experiment_id": source["experiment_id"],
            "experiment_fingerprint": source["experiment_fingerprint"],
            "conversations": conversation_count,
            "final_judge_outputs": final_judgment_count,
        },
        "selected_disagreement_cells": len(rows),
        "unique_disagreement_conversation_turns": len(disagreement_turn_keys),
        "by_rule": dict(by_rule),
        "classification_counts": {
            key: classification_counts.get(key, 0)
            for key in sorted(CLASSIFICATIONS)
        },
        "known_controls_matched": len(matched_annotations),
        "contrast_suite": contrast_validation,
        "rubric_version": plan["judge_rubric"]["version"],
        "future_scope_estimates": scopes,
        "limitations": [
            "The old three-Judge ensemble is not ground truth.",
            "Known controls test direction and axis isolation, not overall Judge accuracy.",
            "No v2 Judge API call has been made.",
        ],
    }

    rows_path = output / "disagreement-audit.jsonl"
    requests_path = output / "v2-judge-requests.jsonl"
    contrast_requests_path = output / "contrast-pair-requests.jsonl"
    summary_path = output / "summary.json"
    report_path = output / "report.md"
    html_path = output / "audit.html"
    _write_jsonl(rows_path, rows)
    _write_jsonl(requests_path, requests)
    _write_jsonl(contrast_requests_path, contrast_requests)
    _write_json(summary_path, summary)
    report_path.write_text(_markdown_report(summary), encoding="utf-8")
    html_path.write_text(_html_document(summary, rows), encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "audit_id": plan["audit_id"],
        "created_at": _now(),
        "api_calls_started": False,
        "plan": {"path": str(plan_path.relative_to(repo)), "sha256": _sha256_file(plan_path)},
        "source_artifacts_mutated": False,
        "outputs": {
            path.name: {"sha256": _sha256_file(path), "bytes": path.stat().st_size}
            for path in (
                rows_path,
                requests_path,
                contrast_requests_path,
                summary_path,
                report_path,
                html_path,
            )
        },
    }
    _write_json(output / "manifest.json", manifest)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--source", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-plan")
    build = sub.add_parser("build-offline-audit")
    build.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo = args.repo.resolve()
    plan_path = args.plan if args.plan.is_absolute() else repo / args.plan
    plan = _read_json(plan_path)
    if args.command == "validate-plan":
        result = validate_audit_plan(plan)
    else:
        source = args.source
        if source is None:
            source = repo / str(plan["source"]["artifact_root"])
        elif not source.is_absolute():
            source = repo / source
        result = build_offline_audit(repo, plan_path, source.resolve(), args.output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
