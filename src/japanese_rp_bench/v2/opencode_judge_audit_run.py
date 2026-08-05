"""Execute and analyze the preregistered OpenCode Judge audit v2.

The runner consumes frozen, provider-neutral offline requests. It never
generates new target conversations, never falls back to paid providers, and
stores each Judge task independently so an interrupted run can resume safely.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from japanese_rp_bench.v2.judge import build_judge_request, parse_judge_response
from japanese_rp_bench.v2.opencode_judge_audit import validate_audit_plan
from japanese_rp_bench.v2.opencode_judge_audit_v21 import (
    resolve_v21_rubric,
    validate_v21_plan,
)
from japanese_rp_bench.v2.opencode_repeatability import (
    JUDGE_IDS,
    _load_packs,
    _read_json,
    _read_jsonl,
    _sha256_file,
)
from japanese_rp_bench.v2.providers import (
    GenerationOutcomeError,
    ModelSpec,
    ProviderError,
    RateLimitError,
    generate_text,
)
from japanese_rp_bench.v2.runner import _judge_json_schema, _uses_anthropic_judge_schema
from japanese_rp_bench.v2.schemas import Conversation, DialogueTurn, SchemaError


DEFAULT_PLAN = Path("configs/opencode_judge_audit_v2_2026-07-28.json")
DEFAULT_OFFLINE = Path(
    "tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v2-offline"
)
DEFAULT_API_OUTPUT = Path(
    "tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v2-api-v1"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_jsonl(path: Path, values: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )


def _request_payload(user_prompt: str) -> Mapping[str, Any]:
    try:
        encoded = user_prompt.split("PAYLOAD_JSON\n", 1)[1].split("\nEND_PAYLOAD_JSON", 1)[0]
        value = json.loads(encoded)
    except (IndexError, json.JSONDecodeError) as exc:
        raise SchemaError("Offline Judge request does not contain a valid payload") from exc
    if not isinstance(value, Mapping):
        raise SchemaError("Offline Judge request payload must be an object")
    return value


def _request_context(
    record: Mapping[str, Any],
    by_scenario: Mapping[str, Any],
) -> tuple[Any, Any, Conversation, int]:
    request = record.get("request")
    if not isinstance(request, Mapping):
        raise SchemaError("Offline Judge request record is missing request")
    payload = _request_payload(str(request["user_prompt"]))
    scenario_id = str(payload["scenario"]["id"])
    role_id = str(payload["role"]["id"])
    target_turn = int(payload["target_turn"])
    role_pack = by_scenario[scenario_id]
    scenario = role_pack.scenarios[scenario_id]
    role = role_pack.roles[role_id]
    history = payload.get("conversation_through_target_turn")
    if not isinstance(history, list):
        raise SchemaError("Offline Judge request is missing conversation history")
    conversation = Conversation(
        role_id=role_id,
        scenario_id=scenario_id,
        target_model="blind-audit-target",
        turns=tuple(
            DialogueTurn(
                index=int(item["turn"]),
                user=str(item["user"]),
                assistant=str(item["assistant"]),
            )
            for item in history
        ),
        metadata={"request_key": str(record["request_key"])},
    )
    if target_turn != len(conversation.turns):
        raise SchemaError("Offline Judge target turn must end the supplied history")
    return role, scenario, conversation, target_turn


def _task_id(scope: str, request_key: str, judge_id: str) -> str:
    return f"{scope}|{request_key}|{judge_id}"


def _task_path(output: Path, scope: str, task_id: str) -> Path:
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
    return output / scope / "final" / f"{digest}.json"


def _attempt_path(output: Path, scope: str, task_id: str, attempt: int) -> Path:
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
    return output / scope / "attempts" / digest / f"attempt-{attempt:03d}.json"


def _load_inputs(
    repo: Path,
    plan_path: Path,
    offline: Path,
) -> tuple[
    Mapping[str, Any],
    Mapping[str, Any],
    Mapping[str, Any],
    list[ModelSpec],
    Mapping[str, Any],
]:
    plan = _read_json(plan_path)
    schema_version = str(plan.get("schema_version"))
    if schema_version == "2.0":
        validate_audit_plan(plan)
        old_plan_path = repo / str(plan["source"]["plan_path"])
        rubric = plan["judge_rubric"]
    elif schema_version == "2.1":
        validate_v21_plan(repo, plan_path, plan)
        old_plan_path = repo / str(plan["source"]["challenge_plan_path"])
        rubric = resolve_v21_rubric(repo, plan)
    else:
        raise SchemaError(f"Unsupported Judge audit plan schema: {schema_version}")
    offline_manifest = _read_json(offline / "manifest.json")
    if offline_manifest.get("plan", {}).get("sha256") != _sha256_file(plan_path):
        raise SchemaError("Offline Judge requests do not match the current v2 plan")
    if offline_manifest.get("api_calls_started") is not False:
        raise SchemaError("Offline Judge request manifest is not API-clean")
    old_plan = _read_json(old_plan_path)
    _, by_scenario = _load_packs(repo, old_plan)
    judges = [ModelSpec.from_dict(value) for value in old_plan["judges"]]
    if [judge.id for judge in judges] != list(JUDGE_IDS):
        raise SchemaError("Judge audit runner requires the frozen three Judge IDs")
    if any(judge.provider != "opencode_go" for judge in judges):
        raise SchemaError("Judge audit runner permits OpenCode Go Judges only")
    return plan, old_plan, by_scenario, judges, rubric


def _raw_attempt(
    task_id: str,
    request_key: str,
    judge_id: str,
    attempt: int,
    *,
    result: Any = None,
    error: Exception | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "created_at": _now(),
        "task_id": task_id,
        "request_key": request_key,
        "judge_id": judge_id,
        "attempt": attempt,
        "result": None if result is None else result.to_dict(),
        "error_type": "" if error is None else type(error).__name__,
        "error": "" if error is None else str(error),
        "api_key_recorded": False,
    }


def _run_task(
    output: Path,
    scope: str,
    record: Mapping[str, Any],
    judge: ModelSpec,
    role: Any,
    scenario: Any,
    conversation: Conversation,
    target_turn: int,
    rubric: Mapping[str, Any],
    schema_attempts: int,
    transport_attempts: int,
) -> dict[str, Any]:
    request_key = str(record["request_key"])
    task_id = _task_id(scope, request_key, judge.id)
    final_path = _task_path(output, scope, task_id)
    if final_path.is_file():
        existing = _read_json(final_path)
        if existing.get("status") == "complete" and existing.get("task_id") == task_id:
            return existing
        if existing.get("status") != "failed" or existing.get("task_id") != task_id:
            raise SchemaError(f"Existing Judge task artifact is invalid: {final_path}")
    keyed = _uses_anthropic_judge_schema(judge)
    request = build_judge_request(
        role,
        scenario,
        conversation,
        target_turn,
        keyed_findings=keyed,
        audit_rubric=rubric,
    )
    if conversation.target_model in request.system_prompt or conversation.target_model in request.user_prompt:
        raise SchemaError("Judge request exposes the target identity")
    attempt_directory = _attempt_path(output, scope, task_id, 1).parent
    attempt = len(list(attempt_directory.glob("attempt-*.json"))) if attempt_directory.is_dir() else 0
    calls = []
    last_error: Exception | None = None
    for schema_attempt in range(1, schema_attempts + 1):
        result = None
        for transport_attempt in range(1, transport_attempts + 1):
            attempt += 1
            try:
                result = generate_text(
                    judge,
                    request.system_prompt,
                    [{"role": "user", "content": request.user_prompt}],
                    max_output_tokens=8192,
                    json_mode=True,
                    json_schema=_judge_json_schema(
                        role,
                        string_scores=keyed,
                        fixed_rule_keys=keyed,
                    ),
                )
                calls.append(result.to_dict())
                break
            except RateLimitError as exc:
                last_error = exc
                _write_json_atomic(
                    _attempt_path(output, scope, task_id, attempt),
                    _raw_attempt(task_id, request_key, judge.id, attempt, error=exc),
                )
                time.sleep(min(30, max(2, transport_attempt * 2)))
            except (ProviderError, GenerationOutcomeError) as exc:
                last_error = exc
                failed_result = getattr(exc, "result", None)
                _write_json_atomic(
                    _attempt_path(output, scope, task_id, attempt),
                    _raw_attempt(
                        task_id,
                        request_key,
                        judge.id,
                        attempt,
                        result=failed_result,
                        error=exc,
                    ),
                )
                time.sleep(min(15, transport_attempt * 2))
        if result is None:
            continue
        try:
            evaluation = parse_judge_response(result.text, judge.id, target_turn, role)
        except (KeyError, TypeError, ValueError, SchemaError) as exc:
            last_error = exc
            _write_json_atomic(
                _attempt_path(output, scope, task_id, attempt),
                _raw_attempt(
                    task_id,
                    request_key,
                    judge.id,
                    attempt,
                    result=result,
                    error=exc,
                ),
            )
            continue
        artifact = {
            "schema_version": "1.0",
            "created_at": _now(),
            "status": "complete",
            "scope": scope,
            "task_id": task_id,
            "request_key": request_key,
            "judge_id": judge.id,
            "rule_id": record.get("rule_id"),
            "expected_verdict": record.get("expected_verdict"),
            "evaluation": evaluation.to_dict(),
            "metadata": {
                "calls": calls,
                "schema_attempts_used": schema_attempt,
                "total_attempts_used": attempt,
                "rubric_version": rubric["version"],
                "system_prompt_sha256": hashlib.sha256(request.system_prompt.encode()).hexdigest(),
                "user_prompt_sha256": hashlib.sha256(request.user_prompt.encode()).hexdigest(),
                "api_key_recorded": False,
            },
        }
        _write_json_atomic(final_path, artifact)
        return artifact
    failure = {
        "schema_version": "1.0",
        "created_at": _now(),
        "status": "failed",
        "scope": scope,
        "task_id": task_id,
        "request_key": request_key,
        "judge_id": judge.id,
        "error_type": "" if last_error is None else type(last_error).__name__,
        "error": "unknown error" if last_error is None else str(last_error),
        "api_key_recorded": False,
    }
    _write_json_atomic(final_path, failure)
    return failure


def _finding_verdict(artifact: Mapping[str, Any], rule_id: str) -> str:
    findings = artifact.get("evaluation", {}).get("findings", [])
    for finding in findings:
        if finding.get("rule_id") == rule_id:
            return str(finding.get("verdict"))
    raise SchemaError(f"Judge artifact is missing the requested rule: {rule_id}")


def evaluate_contrast_gate(
    artifacts: Sequence[Mapping[str, Any]],
    expected_count: int = 24,
    required_policy: str = "all_8_cases_for_each_of_3_judges",
) -> dict[str, Any]:
    complete = [item for item in artifacts if item.get("status") == "complete"]
    checks = []
    by_judge: dict[str, Counter[str]] = defaultdict(Counter)
    for artifact in complete:
        expected = str(artifact.get("expected_verdict"))
        rule_id = str(artifact.get("rule_id"))
        actual = _finding_verdict(artifact, rule_id)
        matched = actual == expected
        by_judge[str(artifact["judge_id"])]["matched" if matched else "mismatched"] += 1
        checks.append({
            "task_id": artifact["task_id"],
            "request_key": artifact["request_key"],
            "judge_id": artifact["judge_id"],
            "rule_id": rule_id,
            "expected_verdict": expected,
            "actual_verdict": actual,
            "matched": matched,
        })
    passed = len(artifacts) == expected_count and len(complete) == expected_count and all(
        item["matched"] for item in checks
    )
    return {
        "schema_version": "1.0",
        "created_at": _now(),
        "passed": passed,
        "required_exact_match_policy": required_policy,
        "expected_tasks": expected_count,
        "complete_tasks": len(complete),
        "matched": sum(item["matched"] for item in checks),
        "mismatched": sum(not item["matched"] for item in checks),
        "by_judge": {key: dict(value) for key, value in sorted(by_judge.items())},
        "checks": checks,
        "not_a_proof_of_overall_judge_accuracy": True,
    }


def _scope_summary(
    scope: str,
    artifacts: Sequence[Mapping[str, Any]],
    judges: Sequence[ModelSpec],
) -> dict[str, Any]:
    prices = {judge.id: judge for judge in judges}
    cost = 0.0
    calls = 0
    for artifact in artifacts:
        if artifact.get("status") != "complete":
            continue
        spec = prices[str(artifact["judge_id"])]
        for raw in artifact.get("metadata", {}).get("calls", []):
            calls += 1
            # Reconstruct only the fields required by estimated_list_cost.
            cost += (
                int(raw.get("input_tokens", 0)) * spec.input_price_per_million
                + int(raw.get("output_tokens", 0)) * spec.output_price_per_million
            ) / 1_000_000
    return {
        "schema_version": "1.0",
        "created_at": _now(),
        "scope": scope,
        "api_calls_started": True,
        "expected_tasks": len(artifacts),
        "complete_tasks": sum(item.get("status") == "complete" for item in artifacts),
        "failed_tasks": sum(item.get("status") != "complete" for item in artifacts),
        "provider_calls_in_complete_artifacts": calls,
        "estimated_list_cost_usd": round(cost, 6),
        "api_key_recorded": False,
    }


def run_scope(
    repo: Path,
    plan_path: Path,
    offline: Path,
    output: Path,
    scope: str,
    workers: int,
) -> dict[str, Any]:
    if not os.environ.get("OPENCODE_GO_API_KEY"):
        raise SchemaError("OPENCODE_GO_API_KEY is required for the approved Judge audit run")
    plan, _, by_scenario, judges, rubric = _load_inputs(repo, plan_path, offline)
    is_v21 = str(plan.get("schema_version")) == "2.1"
    supported = {"contrast", "full2160"} if is_v21 else {"contrast", "selected70"}
    if scope not in supported:
        raise SchemaError(f"Unsupported Judge audit scope for this plan: {scope}")
    if scope in {"selected70", "full2160"}:
        gate_path = output / "contrast" / "gate.json"
        if not gate_path.is_file() or _read_json(gate_path).get("passed") is not True:
            raise SchemaError(f"{scope} requires a passing contrast gate")
        request_path = (
            offline / "full-judge-requests.jsonl"
            if scope == "full2160"
            else offline / "v2-judge-requests.jsonl"
        )
    else:
        request_path = offline / "contrast-pair-requests.jsonl"
    records = _read_jsonl(request_path)
    if scope == "selected70":
        expected_records = 70
    elif scope == "full2160":
        expected_records = 2160
    else:
        expected_records = 18 if is_v21 else 8
    if len(records) != expected_records:
        raise SchemaError(f"Unexpected offline request count for {scope}: {len(records)}")
    contexts = {
        str(record["request_key"]): _request_context(record, by_scenario)
        for record in records
    }
    tasks = [(record, judge) for record in records for judge in judges]
    artifacts = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for record, judge in tasks:
            role, scenario, conversation, target_turn = contexts[str(record["request_key"])]
            future = executor.submit(
                _run_task,
                output,
                scope,
                record,
                judge,
                role,
                scenario,
                conversation,
                target_turn,
                rubric,
                3,
                100,
            )
            futures[future] = (str(record["request_key"]), judge.id)
        for index, future in enumerate(as_completed(futures), start=1):
            request_key, judge_id = futures[future]
            artifact = future.result()
            artifacts.append(artifact)
            if len(tasks) < 500 or index == len(tasks) or index % 25 == 0 or artifact["status"] != "complete":
                print(
                    f"judge-audit scope={scope} progress={index}/{len(tasks)} "
                    f"status={artifact['status']} judge={judge_id} request={request_key}",
                    flush=True,
                )
    artifacts.sort(key=lambda item: item["task_id"])
    summary = _scope_summary(scope, artifacts, judges)
    summary["expected_tasks"] = len(tasks)
    if summary["complete_tasks"] != len(tasks):
        summary["complete"] = False
        _write_json_atomic(output / scope / "summary.json", summary)
        raise SchemaError(f"Judge audit scope {scope} is incomplete; rerun to resume")
    summary["complete"] = True
    _write_json_atomic(output / scope / "summary.json", summary)
    if scope == "contrast":
        expected_tasks = int(plan["contrast_suite"]["judge_tasks"]) if is_v21 else 24
        policy = (
            str(plan["contrast_suite"]["required_gate"])
            if is_v21
            else "all_8_cases_for_each_of_3_judges"
        )
        gate = evaluate_contrast_gate(artifacts, expected_tasks, policy)
        _write_json_atomic(output / scope / "gate.json", gate)
        summary["gate"] = gate
        if not gate["passed"]:
            raise SchemaError("Contrast gate failed; do not start selected70")
    manifest = {
        "schema_version": "1.0",
        "created_at": _now(),
        "audit_id": plan["audit_id"],
        "rubric_version": plan["judge_rubric"]["version"],
        "api_calls_started": True,
        "provider_scope": "opencode_go_only",
        "paid_provider_fallback": False,
        "api_key_recorded": False,
        "plan_sha256": _sha256_file(plan_path),
        "offline_manifest_sha256": _sha256_file(offline / "manifest.json"),
        "scopes": {
            name: _read_json(output / name / "summary.json")
            for name in ("contrast", "selected70", "full2160")
            if (output / name / "summary.json").is_file()
        },
    }
    _write_json_atomic(output / "manifest.json", manifest)
    return summary


def analyze_selected(offline: Path, output: Path) -> dict[str, Any]:
    rows = _read_jsonl(offline / "disagreement-audit.jsonl")
    artifacts = [
        _read_json(path) for path in sorted((output / "selected70" / "final").glob("*.json"))
    ]
    complete = [item for item in artifacts if item.get("status") == "complete"]
    if len(rows) != 83 or len(complete) != 210:
        raise SchemaError("Selected Judge audit analysis requires 83 rows and 210 complete tasks")
    by_request_judge = {
        (str(item["request_key"]), str(item["judge_id"])): item for item in complete
    }
    comparisons = []
    new_severe_by_rule: Counter[str] = Counter()
    changed_by_judge: Counter[str] = Counter()
    old_known_correct = 0
    new_known_correct = 0
    old_known_opposite = 0
    new_known_opposite = 0
    known_opportunities = 0
    known_by_judge: dict[str, Counter[str]] = defaultdict(Counter)
    remaining_verdict_patterns: Counter[str] = Counter()
    for row in rows:
        request_key = "|".join(str(row["audit_id"]).split("|")[:-1])
        rule_id = str(row["rule"]["rule_id"])
        new = {}
        for judge_id in JUDGE_IDS:
            artifact = by_request_judge[(request_key, judge_id)]
            verdict = _finding_verdict(artifact, rule_id)
            finding = next(
                item for item in artifact["evaluation"]["findings"] if item["rule_id"] == rule_id
            )
            new[judge_id] = {
                "verdict": verdict,
                "confidence": finding.get("confidence"),
                "evidence": finding.get("evidence", ""),
                "rationale": finding.get("rationale", ""),
            }
            if verdict != row["judgments"][judge_id]["verdict"]:
                changed_by_judge[judge_id] += 1
        new_verdicts = {value["verdict"] for value in new.values()}
        new_severe = {"pass", "fail"}.issubset(new_verdicts)
        if new_severe:
            new_severe_by_rule[rule_id] += 1
            remaining_verdict_patterns["/".join(
                new[judge_id]["verdict"] for judge_id in JUDGE_IDS
            )] += 1
        expected = row["offline_review"]["expected_rule_verdict"]
        if expected in {"pass", "fail"}:
            opposite = "pass" if expected == "fail" else "fail"
            for judge_id in JUDGE_IDS:
                known_opportunities += 1
                old_verdict = row["judgments"][judge_id]["verdict"]
                new_verdict = new[judge_id]["verdict"]
                old_match = old_verdict == expected
                new_match = new_verdict == expected
                old_opposite = old_verdict == opposite
                new_opposite = new_verdict == opposite
                old_known_correct += old_match
                new_known_correct += new_match
                old_known_opposite += old_opposite
                new_known_opposite += new_opposite
                known_by_judge[judge_id]["opportunities"] += 1
                known_by_judge[judge_id]["old_exact_matches"] += old_match
                known_by_judge[judge_id]["new_exact_matches"] += new_match
                known_by_judge[judge_id]["old_opposite_direction"] += old_opposite
                known_by_judge[judge_id]["new_opposite_direction"] += new_opposite
        comparisons.append({
            "audit_id": row["audit_id"],
            "request_key": request_key,
            "rule_id": rule_id,
            "rule_description": row["rule"]["description"],
            "probes": row["probes"],
            "target_user": row["target_user"],
            "target_assistant": row["target_assistant"],
            "classification": row["offline_review"]["classification"],
            "expected_rule_verdict": expected,
            "old_judgments": row["judgments"],
            "new_judgments": new,
            "old_pass_fail_disagreement": True,
            "new_pass_fail_disagreement": new_severe,
        })
    old_by_rule = Counter(row["rule"]["rule_id"] for row in rows)
    summary = {
        "schema_version": "1.0",
        "created_at": _now(),
        "api_calls_started": True,
        "audited_cells": len(rows),
        "unique_turns_rejudged": 70,
        "judge_outputs": len(complete),
        "old_pass_fail_disagreements": 83,
        "new_pass_fail_disagreements_on_same_cells": sum(new_severe_by_rule.values()),
        "resolved_pass_fail_disagreements": 83 - sum(new_severe_by_rule.values()),
        "old_by_rule": dict(old_by_rule),
        "new_by_rule": dict(new_severe_by_rule),
        "verdict_changes_by_judge": dict(changed_by_judge),
        "known_direction_opportunities": known_opportunities,
        "old_known_direction_matches": old_known_correct,
        "new_known_direction_matches": new_known_correct,
        "known_direction_old_accuracy_percent": round(old_known_correct / known_opportunities * 100, 6),
        "known_direction_new_accuracy_percent": round(new_known_correct / known_opportunities * 100, 6),
        "old_known_opposite_direction_errors": old_known_opposite,
        "new_known_opposite_direction_errors": new_known_opposite,
        "known_direction_by_judge": {
            judge_id: dict(known_by_judge[judge_id]) for judge_id in JUDGE_IDS
        },
        "remaining_pass_fail_verdict_patterns_in_judge_order": {
            "judge_order": list(JUDGE_IDS),
            "patterns": dict(remaining_verdict_patterns),
        },
        "limitations": [
            "The 83 cells were selected because old Judges disagreed, so this is not an unbiased accuracy sample.",
            "The new ensemble is not human ground truth.",
            "No rank or full Challenge score is recomputed from this selected subset.",
        ],
    }
    analysis = output / "analysis-selected70"
    _write_jsonl(analysis / "cell-comparisons.jsonl", comparisons)
    _write_json_atomic(analysis / "summary.json", summary)
    report = f"""# Judge audit v2: 83重大不一致の再評価

- 同じ83セルでpass/fail不一致: 旧83件 → 新{summary['new_pass_fail_disagreements_on_same_cells']}件
- 解消した不一致: {summary['resolved_pass_fail_disagreements']}件
- 既知方向への一致: 旧{summary['old_known_direction_matches']}/{known_opportunities} → 新{summary['new_known_direction_matches']}/{known_opportunities}
- 既知例の正反対方向: 旧{summary['old_known_opposite_direction_errors']}件 → 新{summary['new_known_opposite_direction_errors']}件
- 再Judge: 70ターン、210最終Judge出力

これは旧不一致から選んだ監査標本であり、Judge精度全体、人間の真値、ランキングを示しません。
"""
    (analysis / "report.md").write_text(report, encoding="utf-8")
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--offline", type=Path, default=DEFAULT_OFFLINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_API_OUTPUT)
    sub = parser.add_subparsers(dest="command", required=True)
    contrast = sub.add_parser("run-contrast")
    contrast.add_argument("--workers", type=int, default=3)
    selected = sub.add_parser("run-selected70")
    selected.add_argument("--workers", type=int, default=4)
    full = sub.add_parser("run-full2160")
    full.add_argument("--workers", type=int, default=6)
    sub.add_parser("analyze-selected70")
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo = args.repo.resolve()
    plan_path = args.plan if args.plan.is_absolute() else repo / args.plan
    offline = args.offline if args.offline.is_absolute() else repo / args.offline
    output = args.output if args.output.is_absolute() else repo / args.output
    if args.command == "run-contrast":
        result = run_scope(repo, plan_path, offline.resolve(), output.resolve(), "contrast", args.workers)
    elif args.command == "run-selected70":
        result = run_scope(repo, plan_path, offline.resolve(), output.resolve(), "selected70", args.workers)
    elif args.command == "run-full2160":
        result = run_scope(repo, plan_path, offline.resolve(), output.resolve(), "full2160", args.workers)
    else:
        result = analyze_selected(offline.resolve(), output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
