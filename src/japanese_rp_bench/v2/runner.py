"""Resumable end-to-end benchmark runner for v2 role packs."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import yaml

from japanese_rp_bench.v2.batch import (
    BatchRequest,
    batch_state,
    build_batch_request,
    read_batch_results,
    submit_batch,
    wait_for_batch,
)
from japanese_rp_bench.v2.base import (
    LEGACY_DATASET_URL,
    LEGACY_DIMENSIONS,
    build_base_judge_request,
    build_base_role_pack,
    load_legacy_cases,
    parse_base_judge_response,
    score_base_conversation,
)
from japanese_rp_bench.v2.judge import (
    QUALITY_DIMENSIONS,
    build_judge_request,
    parse_judge_response,
    validate_judge_evaluation,
)
from japanese_rp_bench.v2.providers import (
    GenerationOutcomeError,
    GenerationResult,
    ModelSpec,
    ProviderError,
    RateLimitError,
    estimated_list_cost,
    generate_text,
)
from japanese_rp_bench.v2.rolepacks import load_role_pack
from japanese_rp_bench.v2.scoring import score_conversation
from japanese_rp_bench.v2.schemas import (
    Conversation,
    DialogueTurn,
    JudgeEvaluation,
    RoleDefinition,
    RolePack,
    ScenarioDefinition,
    SchemaError,
)


LOGGER = logging.getLogger("japanese_rp_bench.v2.runner")
SUMMARY_METRICS = (
    "core_fidelity_score",
    "deterministic_compliance_score",
    "judge_fidelity_score",
    "conversation_quality_score",
    "long_term_stability_score",
    "robustness_score",
    "recovery_score",
)
EXPENSIVE_JUDGE_PROVIDERS = {"gemini", "anthropic"}
RUN_FINGERPRINT_SCHEMA_VERSION = "1.0"
FINGERPRINT_SOURCE_FILES = (
    "base.py",
    "batch.py",
    "judge.py",
    "providers.py",
    "rolepacks.py",
    "rules.py",
    "runner.py",
    "schemas.py",
    "scoring.py",
)


@dataclass(frozen=True)
class _BatchJudgeTask:
    key: str
    judgment_path: Path
    judge_spec: ModelSpec
    role: RoleDefinition
    scenario: ScenarioDefinition
    conversation: Conversation
    turn: int | None
    system_prompt: str
    user_prompt: str
    max_output_tokens: int
    json_schema: Mapping[str, Any]
    run_fingerprint: str
    conversation_fingerprint: str


@dataclass(frozen=True)
class _GenerationTask:
    key: str
    conversation_path: Path
    role: RoleDefinition
    scenario: ScenarioDefinition
    target_spec: ModelSpec
    spec: ModelSpec
    purpose: str
    turn: int
    system_prompt: str
    messages: Tuple[Mapping[str, str], ...]
    max_output_tokens: int
    run_fingerprint: str


def run_benchmark(
    config_path: str | Path,
    output_path: str | Path,
    workers: int = 4,
    pilot_report_path: str | Path | None = None,
) -> Dict[str, Any]:
    if workers < 1:
        raise ValueError("workers must be at least 1")
    config_file = Path(config_path).resolve()
    output_root = Path(output_path).resolve()
    config = _load_yaml(config_file)
    role_packs = [load_role_pack(path) for path in config.get("role_packs", [])]
    base_config = config.get("base_track") or {}
    base_enabled = bool(base_config.get("enabled", False))
    base_cases: List[Dict[str, Any]] = []
    if base_enabled:
        base_cases = load_legacy_cases(base_config.get("dataset", LEGACY_DATASET_URL))
        selected_case_ids = base_config.get("case_ids")
        if selected_case_ids is not None:
            if not isinstance(selected_case_ids, list) or not selected_case_ids:
                raise SchemaError("base_track.case_ids must be a non-empty list")
            selected = {int(case_id) for case_id in selected_case_ids}
            base_cases = [case for case in base_cases if int(case["id"]) in selected]
            if {int(case["id"]) for case in base_cases} != selected:
                raise SchemaError("base_track.case_ids contains an unknown case ID")
        role_packs.insert(
            0,
            build_base_role_pack(base_cases, turns=int(base_config.get("turns", 10))),
        )
    if not role_packs:
        raise SchemaError("Benchmark config must enable base_track or include role_packs")
    target_specs = _load_model_specs(config, "targets")
    judge_specs = _load_model_specs(config, "judges")
    user_spec = _load_optional_model_spec(config, "user_simulator")
    if base_enabled and user_spec is None:
        raise SchemaError("base_track requires models.user_simulator")
    if len(judge_specs) < int(config["evaluation"]["judge_ensemble"].get("minimum_judges", 2)):
        raise SchemaError("Configured judge count is below evaluation.minimum_judges")
    _validate_credentials_available(target_specs, judge_specs, user_spec)
    target_max_output_tokens, user_max_output_tokens = _generation_limits(config)
    legacy_prompt_file = Path(
        config["evaluation"].get("legacy_prompt_file", "prompts/eval_prompt_SFW.txt")
    ).resolve()
    legacy_rubric = legacy_prompt_file.read_text(encoding="utf-8") if base_enabled else ""
    run_fingerprint, fingerprint_components = _build_run_fingerprint(
        config,
        role_packs,
        base_cases,
        legacy_rubric,
    )
    pilot_evidence = _validate_required_pilot_report(
        config,
        target_specs,
        judge_specs,
        target_max_output_tokens,
        user_max_output_tokens,
        int(config["evaluation"]["judge_max_output_tokens"]),
        int(config["evaluation"]["base_judge_max_output_tokens"]),
        run_fingerprint,
        pilot_report_path,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = _prepare_run_manifest(
        output_root,
        config_file,
        role_packs,
        target_specs,
        judge_specs,
        user_spec,
        workers,
        run_fingerprint,
        fingerprint_components,
    )
    if pilot_evidence is not None:
        manifest["pilot_gate"] = pilot_evidence
        _write_json(output_root / "manifest.json", manifest)
    if base_cases:
        _write_jsonl(output_root / "dataset" / "legacy-base.jsonl", base_cases)

    jobs = [
        (pack, scenario, target)
        for target in target_specs
        for pack in role_packs
        for scenario in pack.scenarios.values()
    ]
    _preflight_resume_artifacts(output_root, jobs, run_fingerprint)
    jobs.sort(
        key=lambda job: (
            output_root
            / "reports"
            / _safe_name(job[2].id)
            / f"{_safe_name(job[0].id)}__{_safe_name(job[1].id)}.json"
        ).is_file()
    )

    # Conversations are turn-dependent. Execute every currently-ready request
    # as one provider batch wave, checkpoint it, then advance to the next wave.
    _run_generation_waves(
        output_root,
        jobs,
        user_spec,
        target_max_output_tokens,
        user_max_output_tokens,
        config,
        run_fingerprint,
        workers,
    )

    _run_batch_judges(
        output_root,
        jobs,
        judge_specs,
        config,
        legacy_rubric,
        run_fingerprint,
    )

    reports: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    executor = ThreadPoolExecutor(max_workers=workers)
    futures = {
        executor.submit(
            _run_scenario,
            output_root,
            pack,
            scenario,
            target,
            user_spec,
            judge_specs,
            config,
            legacy_rubric,
            run_fingerprint,
        ): (target.id, pack.id, scenario.id)
        for pack, scenario, target in jobs
    }
    for future in as_completed(futures):
        target_id, pack_id, scenario_id = futures[future]
        try:
            report = future.result()
        except Exception as exc:
            failure = {
                "target": target_id,
                "role_pack": pack_id,
                "scenario": scenario_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            failures.append(failure)
            LOGGER.error(
                "incomplete target=%s pack=%s scenario=%s error=%s",
                target_id,
                pack_id,
                scenario_id,
                exc,
            )
        else:
            reports.append(report)
            LOGGER.info("completed target=%s pack=%s scenario=%s", target_id, pack_id, scenario_id)
    executor.shutdown(wait=True)

    leaderboard = _build_leaderboard(
        output_root,
        reports,
        target_specs,
        judge_specs,
        user_spec,
        run_fingerprint,
    )
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    manifest["status"] = "partial" if failures else "complete"
    manifest["failures"] = failures
    _write_json(output_root / "manifest.json", manifest)
    _write_json(output_root / "leaderboard.json", leaderboard)
    return leaderboard


def run_generation_pilot(
    config_path: str | Path,
    output_path: str | Path,
    workers: int = 4,
) -> Dict[str, Any]:
    """Run the checked-in low-cost generation and representative-Judge gate."""
    if workers < 1:
        raise ValueError("workers must be at least 1")
    config_file = Path(config_path).resolve()
    output_root = Path(output_path).resolve()
    config = _load_yaml(config_file)
    pilot = config.get("pilot")
    if not isinstance(pilot, Mapping):
        raise SchemaError("Benchmark config must define a pilot object")
    base_case_ids = pilot.get("base_case_ids")
    scenario_ids = pilot.get("scenario_ids")
    if not isinstance(base_case_ids, list) or not base_case_ids:
        raise SchemaError("pilot.base_case_ids must be a non-empty list")
    if not isinstance(scenario_ids, list) or not scenario_ids:
        raise SchemaError("pilot.scenario_ids must be a non-empty list")

    selected_case_ids = {int(value) for value in base_case_ids}
    base_config = config.get("base_track") or {}
    if not bool(base_config.get("enabled", False)):
        raise SchemaError("Generation pilot requires the Base track")
    all_base_cases = load_legacy_cases(base_config.get("dataset", LEGACY_DATASET_URL))
    base_cases = [
        case for case in all_base_cases if int(case["id"]) in selected_case_ids
    ]
    if {int(case["id"]) for case in base_cases} != selected_case_ids:
        raise SchemaError("pilot.base_case_ids contains an unknown case ID")

    selected_scenario_ids = {str(value) for value in scenario_ids}
    role_packs: List[RolePack] = [
        build_base_role_pack(base_cases, turns=int(base_config.get("turns", 10)))
    ]
    full_role_packs: List[RolePack] = []
    found_scenario_ids: set[str] = set()
    for path in config.get("role_packs", []):
        pack = load_role_pack(path)
        full_role_packs.append(pack)
        scenarios = {
            scenario_id: scenario
            for scenario_id, scenario in pack.scenarios.items()
            if scenario_id in selected_scenario_ids
        }
        if not scenarios:
            continue
        found_scenario_ids.update(scenarios)
        role_packs.append(
            RolePack(
                id=pack.id,
                name=pack.name,
                version=pack.version,
                description=pack.description,
                roles=pack.roles,
                scenarios=scenarios,
                metadata=pack.metadata,
            )
        )
    if found_scenario_ids != selected_scenario_ids:
        missing = ", ".join(sorted(selected_scenario_ids - found_scenario_ids))
        raise SchemaError(f"pilot.scenario_ids contains unknown scenarios: {missing}")

    target_specs = _load_model_specs(config, "targets")
    judge_specs = _load_model_specs(config, "judges")
    user_spec = _load_optional_model_spec(config, "user_simulator")
    if user_spec is None:
        raise SchemaError("Generation pilot requires models.user_simulator")
    _validate_credentials_available(target_specs, judge_specs, user_spec)
    target_limit, user_limit = _generation_limits(config)
    legacy_prompt_file = Path(
        config["evaluation"].get("legacy_prompt_file", "prompts/eval_prompt_SFW.txt")
    ).resolve()
    legacy_rubric = legacy_prompt_file.read_text(encoding="utf-8")
    run_fingerprint, fingerprint_components = _build_run_fingerprint(
        config,
        role_packs,
        base_cases,
        legacy_rubric,
    )
    protocol_base_cases = list(all_base_cases)
    configured_case_ids = base_config.get("case_ids")
    if configured_case_ids is not None:
        if not isinstance(configured_case_ids, list) or not configured_case_ids:
            raise SchemaError("base_track.case_ids must be a non-empty list")
        configured_ids = {int(value) for value in configured_case_ids}
        protocol_base_cases = [
            case for case in protocol_base_cases if int(case["id"]) in configured_ids
        ]
        if {int(case["id"]) for case in protocol_base_cases} != configured_ids:
            raise SchemaError("base_track.case_ids contains an unknown case ID")
    protocol_role_packs = [
        build_base_role_pack(
            protocol_base_cases,
            turns=int(base_config.get("turns", 10)),
        ),
        *full_role_packs,
    ]
    protocol_fingerprint, _ = _build_run_fingerprint(
        config,
        protocol_role_packs,
        protocol_base_cases,
        legacy_rubric,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = _prepare_run_manifest(
        output_root,
        config_file,
        role_packs,
        target_specs,
        judge_specs,
        user_spec,
        workers,
        run_fingerprint,
        fingerprint_components,
    )
    manifest["execution_mode"] = "protocol-pilot"
    manifest["protocol_fingerprint"] = protocol_fingerprint
    _write_json(output_root / "manifest.json", manifest)
    _write_jsonl(output_root / "dataset" / "legacy-base.jsonl", base_cases)
    jobs = [
        (pack, scenario, target)
        for target in target_specs
        for pack in role_packs
        for scenario in pack.scenarios.values()
    ]
    _preflight_resume_artifacts(output_root, jobs, run_fingerprint)
    _run_generation_waves(
        output_root,
        jobs,
        user_spec,
        target_limit,
        user_limit,
        config,
        run_fingerprint,
        workers,
    )
    _run_batch_judges(
        output_root,
        jobs,
        judge_specs,
        config,
        legacy_rubric,
        run_fingerprint,
        pilot_final_turn_only=True,
    )
    report = _build_generation_pilot_report(
        output_root,
        jobs,
        target_specs,
        user_spec,
        target_limit,
        user_limit,
        run_fingerprint,
        judge_specs=judge_specs,
        challenge_judge_limit=int(config["evaluation"]["judge_max_output_tokens"]),
        base_judge_limit=int(config["evaluation"]["base_judge_max_output_tokens"]),
    )
    report["config_sha256"] = _json_sha256(config)
    report["protocol_fingerprint"] = protocol_fingerprint
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    manifest["status"] = "pilot_complete" if report["passed"] else "pilot_failed"
    _write_json(output_root / "manifest.json", manifest)
    _write_json(output_root / "pilot-report.json", report)
    if not report["passed"]:
        raise SchemaError("Generation pilot gate failed; inspect pilot-report.json")
    return report


def _generate_scenario_conversation(
    output_root: Path,
    role_pack: RolePack,
    scenario: ScenarioDefinition,
    target_spec: ModelSpec,
    user_spec: ModelSpec | None,
    target_max_output_tokens: int,
    user_max_output_tokens: int,
    run_fingerprint: str,
) -> Conversation:
    stem = f"{_safe_name(role_pack.id)}__{_safe_name(scenario.id)}"
    conversation_path = (
        output_root / "conversations" / _safe_name(target_spec.id) / f"{stem}.json"
    )
    return _generate_conversation(
        conversation_path,
        role_pack.roles[scenario.role_id],
        scenario,
        target_spec,
        user_spec,
        target_max_output_tokens,
        user_max_output_tokens,
        run_fingerprint,
    )


def _run_generation_waves(
    output_root: Path,
    jobs: Sequence[Tuple[RolePack, ScenarioDefinition, ModelSpec]],
    user_spec: ModelSpec | None,
    target_max_output_tokens: int,
    user_max_output_tokens: int,
    config: Mapping[str, Any],
    run_fingerprint: str,
    workers: int,
) -> None:
    poll_interval, max_attempts = _batch_policy(config)
    sync_rate_limit_attempts, sync_rate_limit_backoff = _sync_rate_limit_policy(config)
    all_specs = {spec.id: spec for _, _, spec in jobs}
    if user_spec is not None:
        all_specs[user_spec.id] = user_spec
    while True:
        tasks = _collect_generation_tasks(
            output_root,
            jobs,
            user_spec,
            target_max_output_tokens,
            user_max_output_tokens,
            run_fingerprint,
        )
        active_states = _unprocessed_generation_batch_states(
            output_root,
            run_fingerprint,
        )
        if not tasks and not active_states:
            return
        _execute_generation_wave(
            output_root,
            tasks,
            active_states,
            all_specs,
            poll_interval,
            max_attempts,
            run_fingerprint,
            workers,
            sync_rate_limit_attempts,
            sync_rate_limit_backoff,
        )


def _collect_generation_tasks(
    output_root: Path,
    jobs: Sequence[Tuple[RolePack, ScenarioDefinition, ModelSpec]],
    user_spec: ModelSpec | None,
    target_max_output_tokens: int,
    user_max_output_tokens: int,
    run_fingerprint: str,
) -> List[_GenerationTask]:
    tasks: List[_GenerationTask] = []
    for role_pack, scenario, target_spec in jobs:
        role = role_pack.roles[scenario.role_id]
        stem = f"{_safe_name(role_pack.id)}__{_safe_name(scenario.id)}"
        path = output_root / "conversations" / _safe_name(target_spec.id) / f"{stem}.json"
        pending_path = path.with_suffix(".pending-user.json")
        if path.is_file():
            conversation = Conversation.from_dict(json.loads(path.read_text(encoding="utf-8")))
            _require_run_fingerprint(
                conversation.metadata,
                run_fingerprint,
                path,
                "conversation",
            )
            if conversation.target_model != target_spec.id:
                raise SchemaError(f"Existing conversation target mismatch: {path}")
            turns = list(conversation.turns)
        else:
            turns = []
        if len(turns) == len(scenario.user_messages):
            if pending_path.exists():
                pending_path.unlink()
            continue
        if len(turns) > len(scenario.user_messages):
            raise SchemaError(f"Existing conversation is longer than scenario: {path}")
        if scenario.mode == "scripted":
            for turn, expected in zip(turns, scenario.user_messages):
                if turn.user != expected:
                    raise SchemaError(f"Existing conversation does not match scenario: {path}")
        elif turns and turns[0].user != scenario.user_messages[0]:
            raise SchemaError(f"Existing simulated conversation has a different first input: {path}")

        turn_number = len(turns) + 1
        pending: Mapping[str, Any] | None = None
        if pending_path.is_file():
            value = json.loads(pending_path.read_text(encoding="utf-8"))
            if not isinstance(value, Mapping):
                raise SchemaError(f"Pending user checkpoint is not an object: {pending_path}")
            _require_run_fingerprint(
                value,
                run_fingerprint,
                pending_path,
                "pending user checkpoint",
            )
            if int(value.get("turn", 0)) != turn_number or not isinstance(value.get("user"), str):
                raise SchemaError(f"Pending user checkpoint does not match conversation: {pending_path}")
            pending = value

        if pending is None and (turn_number == 1 or scenario.mode == "scripted"):
            user_message = scenario.user_messages[turn_number - 1]
            pending = {
                "turn": turn_number,
                "user": user_message,
                "generation_call": None,
                "run_fingerprint": run_fingerprint,
            }
            _write_json(pending_path, pending)

        if pending is None:
            if user_spec is None:
                raise SchemaError(f"Simulated scenario requires a user model: {scenario.id}")
            user_messages: List[Mapping[str, str]] = [{"role": "user", "content": "対話開始"}]
            for item in turns:
                user_messages.append({"role": "assistant", "content": item.user})
                user_messages.append({"role": "user", "content": item.assistant})
            tasks.append(
                _GenerationTask(
                    key=_generation_task_key(
                        target_spec.id,
                        role_pack.id,
                        scenario.id,
                        "user_simulator",
                        turn_number,
                    ),
                    conversation_path=path,
                    role=role,
                    scenario=scenario,
                    target_spec=target_spec,
                    spec=user_spec,
                    purpose="user_simulator",
                    turn=turn_number,
                    system_prompt=_user_system_prompt(scenario),
                    messages=tuple(user_messages),
                    max_output_tokens=user_max_output_tokens,
                    run_fingerprint=run_fingerprint,
                )
            )
            continue

        target_messages: List[Mapping[str, str]] = []
        for item in turns:
            target_messages.append({"role": "user", "content": item.user})
            target_messages.append({"role": "assistant", "content": item.assistant})
        target_messages.append({"role": "user", "content": str(pending["user"])})
        tasks.append(
            _GenerationTask(
                key=_generation_task_key(
                    target_spec.id,
                    role_pack.id,
                    scenario.id,
                    "target",
                    turn_number,
                ),
                conversation_path=path,
                role=role,
                scenario=scenario,
                target_spec=target_spec,
                spec=target_spec,
                purpose="target",
                turn=turn_number,
                system_prompt=_target_system_prompt(role),
                messages=tuple(target_messages),
                max_output_tokens=target_max_output_tokens,
                run_fingerprint=run_fingerprint,
            )
        )
    return tasks


def _execute_generation_wave(
    output_root: Path,
    tasks: Sequence[_GenerationTask],
    active_states: Mapping[str, Tuple[Path, Dict[str, Any]]],
    all_specs: Mapping[str, ModelSpec],
    poll_interval: float,
    max_attempts: int,
    run_fingerprint: str,
    workers: int,
    sync_rate_limit_attempts: int,
    sync_rate_limit_backoff: float,
) -> None:
    tasks_by_spec: Dict[str, List[_GenerationTask]] = {}
    for task in tasks:
        tasks_by_spec.setdefault(task.spec.id, []).append(task)

    batch_states: List[Tuple[ModelSpec, Path, Dict[str, Any]]] = []
    batch_spec_ids = {
        spec_id
        for spec_id, grouped in tasks_by_spec.items()
        if grouped and grouped[0].spec.batch
    } | set(active_states)
    for spec_id in sorted(batch_spec_ids):
        spec = all_specs.get(spec_id)
        if spec is None:
            raise SchemaError(f"Generation batch references unknown model spec: {spec_id}")
        active = active_states.get(spec_id)
        if active is not None:
            batch_states.append((spec, active[0], active[1]))
            continue
        grouped = tasks_by_spec.get(spec_id, [])
        if not grouped:
            continue
        batch_states.append(
            (
                spec,
                *_submit_generation_batch(
                    output_root,
                    spec,
                    grouped,
                    max_attempts,
                    run_fingerprint,
                ),
            )
        )

    synchronous = [task for task in tasks if not task.spec.batch]
    if synchronous:
        _execute_synchronous_generation_tasks(
            output_root,
            synchronous,
            workers,
            sync_rate_limit_attempts,
            sync_rate_limit_backoff,
        )

    current_tasks = {task.key: task for task in tasks}
    for spec, state_path, state in batch_states:
        batch_id = str(state["batch_id"])
        if not batch_id:
            raise SchemaError(
                "Generation batch submission has an unknown outcome and will not be "
                f"automatically duplicated: {state_path}"
            )
        status = wait_for_batch(spec, batch_id, poll_interval)
        refs = state.get("requests") or []
        provider_requests = [
            BatchRequest(
                str(ref["custom_id"]),
                _batch_limit_payload(spec, int(ref.get("max_output_tokens", 0))),
            )
            for ref in refs
        ]
        results = read_batch_results(spec, batch_id, status, provider_requests)
        ref_by_custom_id = {str(ref["custom_id"]): ref for ref in refs}
        errors: List[Dict[str, Any]] = []
        terminal_errors: List[str] = []
        for item in results:
            ref = ref_by_custom_id.get(item.custom_id)
            if ref is None:
                errors.append({"custom_id": item.custom_id, "error": "unknown custom_id"})
                continue
            ready_task = current_tasks.get(str(ref["task_key"]))
            if item.error is not None:
                errors.append(
                    {
                        "custom_id": item.custom_id,
                        "task_key": ref["task_key"],
                        "error": item.error,
                        "terminal": item.terminal,
                    }
                )
                if item.generation is not None:
                    if ready_task is not None:
                        _record_generation_attempt(ready_task, item.generation, item.error)
                    else:
                        _record_generation_attempt_from_ref(ref, item.generation, item.error)
                if item.terminal:
                    terminal_errors.append(f"{ref['task_key']}: {item.error}")
                continue
            if item.generation is None:
                errors.append(
                    {
                        "custom_id": item.custom_id,
                        "task_key": ref["task_key"],
                        "error": "unknown batch result error",
                        "terminal": False,
                    }
                )
                continue
            if ready_task is not None:
                _apply_generation_result(ready_task, item.generation)
            elif not _generation_ref_is_applied(ref, run_fingerprint):
                raise SchemaError(
                    "Generation batch task is neither ready nor already applied: "
                    f"{ref['task_key']}"
                )
        state["completed_at"] = datetime.now(timezone.utc).isoformat()
        state["provider_state"] = batch_state(spec, status)
        state["provider_status"] = status
        state["errors"] = errors
        state["processed_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(state_path, state)
        if terminal_errors:
            raise SchemaError(
                "Batch generation returned a terminal outcome; the response was preserved "
                f"and the run was stopped: {terminal_errors[0]}"
            )


def _execute_synchronous_generation_tasks(
    output_root: Path,
    tasks: Sequence[_GenerationTask],
    workers: int,
    max_attempts: int,
    backoff_seconds: float,
) -> None:
    """Retry only explicit 429 tasks while halving synchronous concurrency."""

    pending = list(tasks)
    current_workers = max(1, min(workers, len(pending)))
    for attempt in range(1, max_attempts + 1):
        rate_limited: List[_GenerationTask] = []
        rate_limit_errors: List[str] = []
        executor = ThreadPoolExecutor(max_workers=current_workers)
        futures = {
            executor.submit(
                generate_text,
                task.spec,
                task.system_prompt,
                task.messages,
                task.max_output_tokens,
            ): task
            for task in pending
        }
        try:
            for future in as_completed(futures):
                task = futures[future]
                try:
                    result = future.result()
                except RateLimitError as exc:
                    rate_limited.append(task)
                    rate_limit_errors.append(str(exc))
                    continue
                except GenerationOutcomeError as exc:
                    _record_generation_attempt(task, exc.result, str(exc))
                    raise
                _apply_generation_result(task, result)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        if not rate_limited:
            return

        next_workers = max(1, min(current_workers // 2, len(rate_limited)))
        exhausted = attempt == max_attempts
        _append_jsonl(
            output_root / "rate-limit-events.jsonl",
            {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "attempt": attempt,
                "workers_before": current_workers,
                "workers_after": next_workers,
                "rate_limited_tasks": sorted(task.key for task in rate_limited),
                "errors": sorted(set(rate_limit_errors)),
                "outcome": "exhausted" if exhausted else "retrying",
            },
        )
        if exhausted:
            raise RateLimitError(
                f"{len(rate_limited)} synchronous generation request(s) still rate-limited "
                f"after {max_attempts} attempts at minimum concurrency {next_workers}"
            )

        delay = min(backoff_seconds * attempt, 60.0)
        LOGGER.warning(
            "synchronous generation rate-limited tasks=%s workers=%s->%s "
            "retry_in_seconds=%s",
            len(rate_limited),
            current_workers,
            next_workers,
            delay,
        )
        if delay:
            time.sleep(delay)
        pending = sorted(rate_limited, key=lambda task: task.key)
        current_workers = next_workers


def _submit_generation_batch(
    output_root: Path,
    spec: ModelSpec,
    tasks: Sequence[_GenerationTask],
    max_attempts: int,
    run_fingerprint: str,
) -> Tuple[Path, Dict[str, Any]]:
    batch_dir = output_root / "batches" / "generation" / _safe_name(spec.id)
    state_paths = sorted(batch_dir.glob("attempt-*.json"))
    prior_states = [json.loads(path.read_text(encoding="utf-8")) for path in state_paths]
    for task in tasks:
        attempts = sum(
            any(str(ref.get("task_key")) == task.key for ref in state.get("requests", []))
            for state in prior_states
        )
        if attempts >= max_attempts:
            raise SchemaError(
                f"Generation task {task.key} is still incomplete after {max_attempts} batch attempts"
            )
    attempt = len(state_paths) + 1
    provider_requests = [
        build_batch_request(
            spec,
            f"r{index:05d}",
            task.system_prompt,
            task.messages,
            task.max_output_tokens,
        )
        for index, task in enumerate(tasks)
    ]
    state = {
        "schema_version": "1.0",
        "run_fingerprint": run_fingerprint,
        "phase": "generation",
        "model_id": spec.id,
        "provider": spec.provider,
        "model": spec.model,
        "attempt": attempt,
        "submission_started_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": "",
        "provider_response": None,
        "requests": [
            {
                "custom_id": request.custom_id,
                "task_key": task.key,
                "conversation_path": str(task.conversation_path),
                "scenario_id": task.scenario.id,
                "turn": task.turn,
                "purpose": task.purpose,
                "model_id": task.spec.id,
                "max_output_tokens": task.max_output_tokens,
                "run_fingerprint": run_fingerprint,
            }
            for request, task in zip(provider_requests, tasks)
        ],
    }
    state_path = batch_dir / f"attempt-{attempt:04d}.json"
    _write_json(state_path, state)
    try:
        submitted = submit_batch(
            spec,
            provider_requests,
            f"japanese-rp-bench-generation-{_safe_name(spec.id)}-a{attempt}",
        )
    except Exception as exc:
        state["submission_error"] = f"{type(exc).__name__}: {exc}"
        state["submission_outcome"] = "unknown"
        _write_json(state_path, state)
        raise
    state["submitted_at"] = datetime.now(timezone.utc).isoformat()
    state["batch_id"] = submitted["batch_id"]
    state["provider_response"] = submitted["provider_response"]
    state["submission_outcome"] = "submitted"
    _write_json(state_path, state)
    LOGGER.info(
        "submitted generation batch model=%s requests=%s batch=%s",
        spec.id,
        len(provider_requests),
        submitted["batch_id"],
    )
    return state_path, state


def _unprocessed_generation_batch_states(
    output_root: Path,
    run_fingerprint: str,
) -> Dict[str, Tuple[Path, Dict[str, Any]]]:
    active: Dict[str, Tuple[Path, Dict[str, Any]]] = {}
    for path in sorted((output_root / "batches" / "generation").glob("**/attempt-*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise SchemaError(f"Generation batch state is not an object: {path}")
        _require_run_fingerprint(value, run_fingerprint, path, "generation batch state")
        if value.get("processed_at"):
            continue
        spec_id = str(value.get("model_id", ""))
        if not spec_id or spec_id in active:
            raise SchemaError(f"Multiple or invalid active generation batches for {spec_id}: {path}")
        active[spec_id] = (path, value)
    return active


def _apply_generation_result(task: _GenerationTask, result: GenerationResult) -> None:
    path = task.conversation_path
    pending_path = path.with_suffix(".pending-user.json")
    if path.is_file():
        conversation = Conversation.from_dict(json.loads(path.read_text(encoding="utf-8")))
        _require_run_fingerprint(
            conversation.metadata,
            task.run_fingerprint,
            path,
            "conversation",
        )
        turns = list(conversation.turns)
        metadata = dict(conversation.metadata)
    else:
        turns = []
        metadata = {"generation_calls": [], "run_fingerprint": task.run_fingerprint}
    if len(turns) >= task.turn:
        return
    if len(turns) != task.turn - 1:
        raise SchemaError(f"Generation result turn is not ready: {task.key}")
    call = result.to_dict()
    call["purpose"] = task.purpose
    if task.purpose == "user_simulator":
        if pending_path.is_file():
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            if int(pending.get("turn", 0)) == task.turn and pending.get("user") == result.text:
                return
            raise SchemaError(f"User result conflicts with pending checkpoint: {pending_path}")
        _write_json(
            pending_path,
            {
                "turn": task.turn,
                "user": result.text,
                "generation_call": call,
                "run_fingerprint": task.run_fingerprint,
            },
        )
        return
    if not pending_path.is_file():
        raise SchemaError(f"Target result has no pending user checkpoint: {task.key}")
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    _require_run_fingerprint(
        pending,
        task.run_fingerprint,
        pending_path,
        "pending user checkpoint",
    )
    if int(pending.get("turn", 0)) != task.turn:
        raise SchemaError(f"Target pending checkpoint turn mismatch: {pending_path}")
    user_call = pending.get("generation_call")
    if isinstance(user_call, Mapping):
        metadata.setdefault("generation_calls", []).append(dict(user_call))
    metadata.setdefault("generation_calls", []).append(call)
    turns.append(
        DialogueTurn(
            index=task.turn,
            user=str(pending["user"]),
            assistant=result.text,
        )
    )
    conversation = Conversation(
        role_id=task.role.id,
        scenario_id=task.scenario.id,
        target_model=task.target_spec.id,
        turns=tuple(turns),
        metadata=metadata,
    )
    _write_json(path, _conversation_to_dict(conversation))
    pending_path.unlink(missing_ok=True)


def _generation_ref_is_applied(ref: Mapping[str, Any], run_fingerprint: str) -> bool:
    path = Path(str(ref["conversation_path"]))
    turn = int(ref["turn"])
    purpose = str(ref["purpose"])
    if path.is_file():
        conversation = Conversation.from_dict(json.loads(path.read_text(encoding="utf-8")))
        _require_run_fingerprint(
            conversation.metadata,
            run_fingerprint,
            path,
            "conversation",
        )
        if len(conversation.turns) >= turn:
            return True
    if purpose == "user_simulator":
        pending_path = path.with_suffix(".pending-user.json")
        if pending_path.is_file():
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            _require_run_fingerprint(
                pending,
                run_fingerprint,
                pending_path,
                "pending user checkpoint",
            )
            return int(pending.get("turn", 0)) == turn
    return False


def _record_generation_attempt(
    task: _GenerationTask,
    result: GenerationResult,
    error: str,
) -> None:
    _record_generation_attempt_from_ref(
        {
            "conversation_path": str(task.conversation_path),
            "scenario_id": task.scenario.id,
            "turn": task.turn,
            "model_id": task.spec.id,
            "purpose": task.purpose,
            "run_fingerprint": task.run_fingerprint,
        },
        result,
        error,
    )


def _record_generation_attempt_from_ref(
    ref: Mapping[str, Any],
    result: GenerationResult,
    error: str,
) -> None:
    path = Path(str(ref["conversation_path"]))
    _append_jsonl(
        path.with_suffix(".generation-attempts.jsonl"),
        {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "scenario_id": str(ref["scenario_id"]),
            "turn": int(ref["turn"]),
            "model_id": str(ref["model_id"]),
            "purpose": str(ref["purpose"]),
            "run_fingerprint": str(ref["run_fingerprint"]),
            "error_type": "GenerationOutcomeError",
            "error": error,
            "call": result.to_dict(),
            "raw_response": result.text,
        },
    )


def _generation_task_key(
    target_id: str,
    pack_id: str,
    scenario_id: str,
    purpose: str,
    turn: int,
) -> str:
    return "|".join((target_id, pack_id, scenario_id, purpose, f"turn-{turn}"))


def _build_generation_pilot_report(
    output_root: Path,
    jobs: Sequence[Tuple[RolePack, ScenarioDefinition, ModelSpec]],
    target_specs: Sequence[ModelSpec],
    user_spec: ModelSpec,
    target_limit: int,
    user_limit: int,
    run_fingerprint: str,
    *,
    judge_specs: Sequence[ModelSpec],
    challenge_judge_limit: int,
    base_judge_limit: int,
) -> Dict[str, Any]:
    generation_calls: List[Mapping[str, Any]] = []
    conversations = 0
    for role_pack, scenario, target_spec in jobs:
        stem = f"{_safe_name(role_pack.id)}__{_safe_name(scenario.id)}"
        path = output_root / "conversations" / _safe_name(target_spec.id) / f"{stem}.json"
        conversation = _load_completed_conversation(
            path,
            scenario,
            target_spec,
            run_fingerprint,
        )
        conversations += 1
        generation_calls.extend(conversation.metadata.get("generation_calls", []))

    judge_calls: List[Mapping[str, Any]] = []
    for path in (output_root / "judgments").glob("**/*.jsonl"):
        if path.name.endswith(".raw-attempts.jsonl"):
            continue
        for artifact in _read_jsonl(path):
            metadata = artifact.get("metadata") or {}
            judge_calls.extend(metadata.get("calls", []))
    calls = [*generation_calls, *judge_calls]

    specs = {spec.id: spec for spec in [*target_specs, user_spec, *judge_specs]}
    missing_reasoning_config = [
        str(call.get("response_id", ""))
        for call in calls
        if not isinstance(call.get("reasoning_config"), Mapping)
        or not call.get("reasoning_config")
    ]
    unexpected_termination = [
        str(call.get("response_id", ""))
        for call in calls
        if str(call.get("termination_category", "")) not in {"completed", "refusal"}
    ]
    wrong_limits = []
    wrong_billing = []
    target_call_counts = {spec.id: 0 for spec in target_specs}
    user_call_count = 0
    for call in calls:
        purpose = str(call.get("purpose", ""))
        if purpose == "user_simulator":
            expected_limit = user_limit
        elif purpose == "judge":
            expected_limit = (
                base_judge_limit
                if call.get("track") == "legacy-base"
                else challenge_judge_limit
            )
        else:
            expected_limit = target_limit
        if int(call.get("requested_max_output_tokens", 0)) != expected_limit:
            wrong_limits.append(str(call.get("response_id", "")))
        spec_id = str(call.get("requested_model", ""))
        spec = specs.get(spec_id)
        if spec is not None and spec.batch and call.get("billing_mode") != "batch":
            wrong_billing.append(str(call.get("response_id", "")))
        if purpose == "user_simulator":
            user_call_count += 1
        elif purpose == "target" and spec_id in target_call_counts:
            target_call_counts[spec_id] += 1

    generation_attempts: List[Mapping[str, Any]] = []
    for path in (output_root / "conversations").glob("**/*.generation-attempts.jsonl"):
        generation_attempts.extend(_read_jsonl(path))
    truncation_count = sum(
        str((item.get("call") or {}).get("termination_category", "")) == "truncated"
        for item in generation_attempts
    )
    missing_targets = [
        spec_id for spec_id, count in target_call_counts.items() if count == 0
    ]
    judge_call_counts = {
        spec.id: sum(
            str(call.get("requested_model", "")) == spec.id for call in judge_calls
        )
        for spec in judge_specs
    }
    expected_judge_calls_per_model = len(jobs)
    missing_judges = [
        spec_id
        for spec_id, count in judge_call_counts.items()
        if count != expected_judge_calls_per_model
    ]
    judge_attempts: List[Mapping[str, Any]] = []
    for path in (output_root / "judgments").glob("**/*.raw-attempts.jsonl"):
        judge_attempts.extend(_read_jsonl(path))
    truncation_count += sum(
        str((item.get("call") or {}).get("termination_category", "")) == "truncated"
        for item in judge_attempts
    )
    passed = not any(
        (
            missing_reasoning_config,
            unexpected_termination,
            wrong_limits,
            wrong_billing,
            missing_targets,
            missing_judges,
            truncation_count,
            user_call_count == 0,
        )
    )
    return {
        "schema_version": "1.0",
        "run_fingerprint": run_fingerprint,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "expected_conversations": len(jobs),
        "completed_conversations": conversations,
        "generation_calls": len(generation_calls),
        "judge_calls": len(judge_calls),
        "target_call_counts": target_call_counts,
        "user_simulator_calls": user_call_count,
        "judge_call_counts": judge_call_counts,
        "expected_judge_calls_per_model": expected_judge_calls_per_model,
        "target_max_output_tokens": target_limit,
        "user_max_output_tokens": user_limit,
        "challenge_judge_max_output_tokens": challenge_judge_limit,
        "base_judge_max_output_tokens": base_judge_limit,
        "truncation_count": truncation_count,
        "generation_outcome_attempts": len(generation_attempts),
        "missing_reasoning_config": missing_reasoning_config,
        "unexpected_termination": unexpected_termination,
        "wrong_output_limits": wrong_limits,
        "wrong_billing_mode": wrong_billing,
        "missing_targets": missing_targets,
        "missing_judges": missing_judges,
    }


def _run_batch_judges(
    output_root: Path,
    jobs: Sequence[Tuple[RolePack, ScenarioDefinition, ModelSpec]],
    judge_specs: Sequence[ModelSpec],
    config: Mapping[str, Any],
    legacy_rubric: str,
    run_fingerprint: str,
    *,
    pilot_final_turn_only: bool = False,
) -> None:
    batch_specs = [spec for spec in judge_specs if spec.batch]
    if not batch_specs:
        return
    poll_interval, max_attempts = _batch_policy(config)

    while True:
        active: List[Tuple[ModelSpec, Path, Dict[str, Any]]] = []
        pending_by_spec: Dict[str, List[_BatchJudgeTask]] = {
            spec.id: _collect_batch_judge_tasks(
                output_root,
                jobs,
                spec,
                config,
                legacy_rubric,
                run_fingerprint,
                pilot_final_turn_only=pilot_final_turn_only,
            )
            for spec in batch_specs
        }
        for spec in batch_specs:
            batch_dir = output_root / "batches" / "judging" / _safe_name(spec.id)
            state_paths = sorted(batch_dir.glob("attempt-*.json"))
            unprocessed = []
            for path in state_paths:
                state_value = json.loads(path.read_text(encoding="utf-8"))
                _require_run_fingerprint(
                    state_value,
                    run_fingerprint,
                    path,
                    "batch state",
                )
                if not state_value.get("processed_at"):
                    unprocessed.append((path, state_value))
            if unprocessed:
                active.extend((spec, path, value) for path, value in unprocessed)
                continue

            pending = pending_by_spec[spec.id]
            if not pending:
                continue
            attempt = len(state_paths) + 1
            if attempt > max_attempts:
                sample = ", ".join(task.key for task in pending[:3])
                raise SchemaError(
                    f"Batch judge {spec.id} still has {len(pending)} missing results "
                    f"after {max_attempts} attempts: {sample}"
                )
            provider_requests = [
                build_batch_request(
                    spec,
                    f"r{index:05d}",
                    task.system_prompt,
                    [{"role": "user", "content": task.user_prompt}],
                    task.max_output_tokens,
                    json_mode=True,
                    json_schema=task.json_schema,
                )
                for index, task in enumerate(pending)
            ]
            state = {
                "schema_version": "1.0",
                "run_fingerprint": run_fingerprint,
                "judge_id": spec.id,
                "provider": spec.provider,
                "model": spec.model,
                "attempt": attempt,
                "submission_started_at": datetime.now(timezone.utc).isoformat(),
                "batch_id": "",
                "provider_response": None,
                "requests": [
                    {
                        "custom_id": request.custom_id,
                        "task_key": task.key,
                        "max_output_tokens": task.max_output_tokens,
                    }
                    for request, task in zip(provider_requests, pending)
                ],
            }
            state_path = batch_dir / f"attempt-{attempt:02d}.json"
            _write_json(state_path, state)
            try:
                submitted = submit_batch(
                    spec,
                    provider_requests,
                    f"japanese-rp-bench-{_safe_name(spec.id)}-a{attempt}",
                )
            except Exception as exc:
                state["submission_error"] = f"{type(exc).__name__}: {exc}"
                state["submission_outcome"] = "unknown"
                _write_json(state_path, state)
                raise
            state["submitted_at"] = datetime.now(timezone.utc).isoformat()
            state["batch_id"] = submitted["batch_id"]
            state["provider_response"] = submitted["provider_response"]
            state["submission_outcome"] = "submitted"
            _write_json(state_path, state)
            active.append((spec, state_path, state))
            LOGGER.info(
                "submitted batch judge=%s requests=%s batch=%s",
                spec.id,
                len(provider_requests),
                submitted["batch_id"],
            )

        if not active:
            return

        terminal_batch_errors: List[Dict[str, str]] = []
        for spec, state_path, state in active:
            batch_id = str(state["batch_id"])
            if not batch_id:
                raise SchemaError(
                    "Judge batch submission has an unknown outcome and will not be "
                    f"automatically duplicated: {state_path}"
                )
            status = wait_for_batch(spec, batch_id, poll_interval)
            request_refs_value = state.get("requests") or []
            if not isinstance(request_refs_value, list) or not all(
                isinstance(item, Mapping) for item in request_refs_value
            ):
                raise SchemaError(f"Judge batch state has invalid request references: {state_path}")
            request_refs: List[Mapping[str, Any]] = request_refs_value
            provider_requests = [
                BatchRequest(
                    str(item["custom_id"]),
                    _batch_limit_payload(spec, int(item.get("max_output_tokens", 0))),
                )
                for item in request_refs
            ]
            results = read_batch_results(spec, batch_id, status, provider_requests)
            task_map = {
                task.key: task
                for task in _collect_batch_judge_tasks(
                    output_root,
                    jobs,
                    spec,
                    config,
                    legacy_rubric,
                    run_fingerprint,
                    pilot_final_turn_only=pilot_final_turn_only,
                )
            }
            custom_to_key = {
                str(item["custom_id"]): str(item["task_key"])
                for item in request_refs
            }
            errors: List[Dict[str, Any]] = []
            for item in results:
                task_key = custom_to_key.get(item.custom_id)
                task = task_map.get(task_key or "")
                if task is None:
                    continue
                if item.error is not None:
                    error = {
                        "custom_id": item.custom_id,
                        "task_key": task.key,
                        "error": item.error,
                        "terminal": item.terminal,
                    }
                    errors.append(error)
                    if item.generation is not None:
                        _record_raw_judge_attempt(
                            task.judgment_path,
                            task.judge_spec,
                            task.scenario.id,
                            item.generation,
                            turn=task.turn,
                            error=item.error,
                            force=True,
                        )
                    if item.terminal:
                        terminal_batch_errors.append(
                            {
                                "judge_id": spec.id,
                                "task_key": task.key,
                                "error": item.error,
                            }
                        )
                    continue
                if item.generation is None:
                    errors.append(
                        {
                            "custom_id": item.custom_id,
                            "task_key": task.key,
                            "error": "unknown batch result error",
                            "terminal": False,
                        }
                    )
                    continue
                try:
                    _save_batch_judgment(task, item.generation)
                except (KeyError, TypeError, ValueError, SchemaError, ProviderError) as exc:
                    errors.append(
                        {
                            "custom_id": item.custom_id,
                            "task_key": task.key,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
            state["completed_at"] = datetime.now(timezone.utc).isoformat()
            state["provider_state"] = batch_state(spec, status)
            state["provider_status"] = status
            state["errors"] = errors
            state["processed_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(state_path, state)
            LOGGER.info(
                "processed batch judge=%s results=%s errors=%s batch=%s",
                spec.id,
                len(results),
                len(errors),
                batch_id,
            )
        if terminal_batch_errors:
            first = terminal_batch_errors[0]
            raise SchemaError(
                "Batch judge returned a terminal generation outcome; "
                "the response was preserved for audit and was not scored: "
                f"{first['judge_id']} {first['task_key']} {first['error']}"
            )


def _collect_batch_judge_tasks(
    output_root: Path,
    jobs: Sequence[Tuple[RolePack, ScenarioDefinition, ModelSpec]],
    judge_spec: ModelSpec,
    config: Mapping[str, Any],
    legacy_rubric: str,
    run_fingerprint: str,
    *,
    pilot_final_turn_only: bool = False,
) -> List[_BatchJudgeTask]:
    tasks: List[_BatchJudgeTask] = []
    for role_pack, scenario, target_spec in jobs:
        role = role_pack.roles[scenario.role_id]
        stem = f"{_safe_name(role_pack.id)}__{_safe_name(scenario.id)}"
        conversation_path = (
            output_root / "conversations" / _safe_name(target_spec.id) / f"{stem}.json"
        )
        conversation = Conversation.from_dict(
            json.loads(conversation_path.read_text(encoding="utf-8"))
        )
        _require_run_fingerprint(
            conversation.metadata,
            run_fingerprint,
            conversation_path,
            "conversation",
        )
        conversation_fingerprint = _conversation_fingerprint(conversation)
        judgment_path = (
            output_root / "judgments" / _safe_name(target_spec.id) / f"{stem}.jsonl"
        )
        artifacts = _read_jsonl(judgment_path) if judgment_path.is_file() else []
        _validate_judgment_provenance(
            artifacts,
            judgment_path,
            run_fingerprint,
            conversation_fingerprint,
        )
        if scenario.track == "legacy-base":
            if any(str(item.get("judge_id")) == judge_spec.id for item in artifacts):
                continue
            request = build_base_judge_request(
                role,
                scenario,
                conversation,
                legacy_rubric,
                keyed_findings=judge_spec.provider == "anthropic",
            )
            tasks.append(
                _BatchJudgeTask(
                    key=_batch_task_key(target_spec.id, role_pack.id, scenario.id, judge_spec.id),
                    judgment_path=judgment_path,
                    judge_spec=judge_spec,
                    role=role,
                    scenario=scenario,
                    conversation=conversation,
                    turn=None,
                    system_prompt=request.system_prompt,
                    user_prompt=request.user_prompt,
                    max_output_tokens=int(
                        config["evaluation"].get("base_judge_max_output_tokens", 8192)
                    ),
                    json_schema=_base_judge_json_schema(
                        role,
                        len(conversation.turns),
                        fixed_turn_keys=judge_spec.provider == "anthropic",
                        fixed_rule_keys=judge_spec.provider == "anthropic",
                    ),
                    run_fingerprint=run_fingerprint,
                    conversation_fingerprint=conversation_fingerprint,
                )
            )
            continue

        existing = {
            (str(item.get("judge_id")), int(item.get("turn", 0)))
            for item in artifacts
            if _is_complete_judge_artifact(item, role)
        }
        turns_to_judge = (
            conversation.turns[-1:]
            if pilot_final_turn_only
            else conversation.turns
        )
        for turn in turns_to_judge:
            if (judge_spec.id, turn.index) in existing:
                continue
            judge_request = build_judge_request(
                role,
                scenario,
                conversation,
                turn.index,
                keyed_findings=judge_spec.provider == "anthropic",
            )
            tasks.append(
                _BatchJudgeTask(
                    key=_batch_task_key(
                        target_spec.id,
                        role_pack.id,
                        scenario.id,
                        judge_spec.id,
                        turn.index,
                    ),
                    judgment_path=judgment_path,
                    judge_spec=judge_spec,
                    role=role,
                    scenario=scenario,
                    conversation=conversation,
                    turn=turn.index,
                    system_prompt=judge_request.system_prompt,
                    user_prompt=judge_request.user_prompt,
                    max_output_tokens=int(config["evaluation"].get("judge_max_output_tokens", 4096)),
                    json_schema=_judge_json_schema(
                        role,
                        string_scores=judge_spec.provider == "anthropic",
                        fixed_rule_keys=judge_spec.provider == "anthropic",
                    ),
                    run_fingerprint=run_fingerprint,
                    conversation_fingerprint=conversation_fingerprint,
                )
            )
    return tasks


def _save_batch_judgment(task: _BatchJudgeTask, result: GenerationResult) -> None:
    _record_raw_judge_attempt(
        task.judgment_path,
        task.judge_spec,
        task.scenario.id,
        result,
        turn=task.turn,
    )
    if task.turn is None:
        artifact = parse_base_judge_response(
            result.text,
            task.judge_spec.id,
            task.role,
            len(task.conversation.turns),
        )
    else:
        artifact = parse_judge_response(
            result.text,
            task.judge_spec.id,
            task.turn,
            task.role,
        ).to_dict()
    call = result.to_dict()
    call["purpose"] = "judge"
    call["track"] = task.scenario.track
    artifact["metadata"] = {
        "calls": [call],
        "raw_response": result.text,
        "run_fingerprint": task.run_fingerprint,
        "conversation_fingerprint": task.conversation_fingerprint,
    }
    _append_jsonl(task.judgment_path, artifact)


def _is_complete_judge_artifact(
    artifact: Mapping[str, Any],
    role: RoleDefinition,
) -> bool:
    try:
        evaluation = JudgeEvaluation.from_dict(artifact, role)
        validate_judge_evaluation(evaluation, role)
    except (KeyError, TypeError, ValueError, SchemaError):
        return False
    return True


def _batch_task_key(
    target_id: str,
    pack_id: str,
    scenario_id: str,
    judge_id: str,
    turn: int | None = None,
) -> str:
    suffix = "base" if turn is None else f"turn-{turn}"
    return "|".join((target_id, pack_id, scenario_id, judge_id, suffix))


def _run_scenario(
    output_root: Path,
    role_pack: RolePack,
    scenario: ScenarioDefinition,
    target_spec: ModelSpec,
    user_spec: ModelSpec | None,
    judge_specs: Sequence[ModelSpec],
    config: Mapping[str, Any],
    legacy_rubric: str,
    run_fingerprint: str,
) -> Dict[str, Any]:
    role = role_pack.roles[scenario.role_id]
    stem = f"{_safe_name(role_pack.id)}__{_safe_name(scenario.id)}"
    conversation_path = output_root / "conversations" / _safe_name(target_spec.id) / f"{stem}.json"
    judgments_path = output_root / "judgments" / _safe_name(target_spec.id) / f"{stem}.jsonl"
    report_path = output_root / "reports" / _safe_name(target_spec.id) / f"{stem}.json"

    conversation = _load_completed_conversation(
        conversation_path,
        scenario,
        target_spec,
        run_fingerprint,
    )
    minimum_judges = int(config["evaluation"]["judge_ensemble"].get("minimum_judges", 2))
    if scenario.track == "legacy-base":
        base_judgments = _generate_base_judgments(
            judgments_path,
            role,
            scenario,
            conversation,
            judge_specs,
            legacy_rubric,
            int(config["evaluation"].get("base_judge_max_output_tokens", 8192)),
            run_fingerprint,
        )
        report = score_base_conversation(
            role_pack,
            conversation,
            base_judgments,
            minimum_judges=minimum_judges,
        )
    else:
        judgments = _generate_judgments(
            judgments_path,
            role,
            scenario,
            conversation,
            judge_specs,
            int(config["evaluation"].get("judge_max_output_tokens", 4096)),
            run_fingerprint,
        )
        report = score_conversation(
            role_pack,
            conversation,
            judgments,
            minimum_judges=minimum_judges,
        )
    report["artifacts"] = {
        "conversation": str(conversation_path),
        "judgments": str(judgments_path),
    }
    report["run_fingerprint"] = run_fingerprint
    _write_json(report_path, report)
    return report


def _load_completed_conversation(
    path: Path,
    scenario: ScenarioDefinition,
    target_spec: ModelSpec,
    run_fingerprint: str,
) -> Conversation:
    if not path.is_file():
        raise SchemaError(f"Conversation is missing after generation waves: {path}")
    conversation = Conversation.from_dict(json.loads(path.read_text(encoding="utf-8")))
    _require_run_fingerprint(
        conversation.metadata,
        run_fingerprint,
        path,
        "conversation",
    )
    if conversation.target_model != target_spec.id:
        raise SchemaError(f"Existing conversation target mismatch: {path}")
    if len(conversation.turns) != len(scenario.user_messages):
        raise SchemaError(
            f"Conversation is incomplete after generation waves: {path}; "
            f"expected {len(scenario.user_messages)} turns, found {len(conversation.turns)}"
        )
    return conversation


def _generate_conversation(
    path: Path,
    role: RoleDefinition,
    scenario: ScenarioDefinition,
    target_spec: ModelSpec,
    user_spec: ModelSpec | None,
    target_max_output_tokens: int,
    user_max_output_tokens: int,
    run_fingerprint: str,
) -> Conversation:
    if target_spec.batch or (user_spec is not None and user_spec.batch):
        raise SchemaError(
            "Batch-enabled conversation models must run through the generation wave executor"
        )
    pending_path = path.with_suffix(".pending-user.json")
    if path.is_file():
        existing = Conversation.from_dict(json.loads(path.read_text(encoding="utf-8")))
        _require_run_fingerprint(
            existing.metadata,
            run_fingerprint,
            path,
            "conversation",
        )
        if existing.target_model != target_spec.id:
            raise SchemaError(f"Existing conversation target mismatch: {path}")
        turns = list(existing.turns)
        metadata = dict(existing.metadata)
    else:
        turns = []
        metadata = {
            "generation_calls": [],
            "run_fingerprint": run_fingerprint,
        }
    if scenario.mode == "scripted":
        for turn, expected in zip(turns, scenario.user_messages):
            if turn.user != expected:
                raise SchemaError(f"Existing conversation does not match scenario: {path}")
    elif turns and turns[0].user != scenario.user_messages[0]:
        raise SchemaError(f"Existing simulated conversation has a different first input: {path}")
    if len(turns) > len(scenario.user_messages):
        raise SchemaError(f"Existing conversation is longer than scenario: {path}")

    pending_user: Dict[str, Any] | None = None
    if pending_path.is_file():
        value = json.loads(pending_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise SchemaError(f"Pending user checkpoint is not an object: {pending_path}")
        _require_run_fingerprint(
            value,
            run_fingerprint,
            pending_path,
            "pending user checkpoint",
        )
        pending_turn = int(value.get("turn", 0))
        if pending_turn <= len(turns):
            pending_path.unlink()
        elif pending_turn != len(turns) + 1 or not isinstance(value.get("user"), str):
            raise SchemaError(f"Pending user checkpoint does not match conversation: {pending_path}")
        else:
            pending_user = value

    system_prompt = _target_system_prompt(role)
    for index in range(len(turns), len(scenario.user_messages)):
        user_call: Dict[str, Any] | None = None
        if pending_user is not None and int(pending_user["turn"]) == index + 1:
            user_message = str(pending_user["user"])
            checkpoint_call = pending_user.get("generation_call")
            if isinstance(checkpoint_call, dict):
                user_call = checkpoint_call
        elif index == 0 or scenario.mode == "scripted":
            user_message = scenario.user_messages[index]
        else:
            if user_spec is None:
                raise SchemaError(f"Simulated scenario requires a user model: {scenario.id}")
            user_messages: List[Dict[str, str]] = [{"role": "user", "content": "対話開始"}]
            for item in turns:
                user_messages.append({"role": "assistant", "content": item.user})
                user_messages.append({"role": "user", "content": item.assistant})
            user_result = _generate_conversation_call(
                path,
                scenario,
                index + 1,
                "user_simulator",
                run_fingerprint,
                user_spec,
                _user_system_prompt(scenario),
                user_messages,
                max_output_tokens=user_max_output_tokens,
            )
            user_message = user_result.text
            user_call = user_result.to_dict()
            user_call["purpose"] = "user_simulator"
        _write_json(
            pending_path,
            {
                "turn": index + 1,
                "user": user_message,
                "generation_call": user_call,
                "run_fingerprint": run_fingerprint,
            },
        )
        if user_call is not None:
            metadata.setdefault("generation_calls", []).append(user_call)
        messages: List[Dict[str, str]] = []
        for item in turns:
            messages.append({"role": "user", "content": item.user})
            messages.append({"role": "assistant", "content": item.assistant})
        messages.append({"role": "user", "content": user_message})
        result = _generate_conversation_call(
            path,
            scenario,
            index + 1,
            "target",
            run_fingerprint,
            target_spec,
            system_prompt,
            messages,
            max_output_tokens=target_max_output_tokens,
        )
        turns.append(DialogueTurn(index=index + 1, user=user_message, assistant=result.text))
        target_call = result.to_dict()
        target_call["purpose"] = "target"
        metadata.setdefault("generation_calls", []).append(target_call)
        conversation = Conversation(
            role_id=role.id,
            scenario_id=scenario.id,
            target_model=target_spec.id,
            turns=tuple(turns),
            metadata=metadata,
        )
        _write_json(path, _conversation_to_dict(conversation))
        pending_path.unlink(missing_ok=True)
        pending_user = None
        LOGGER.info("generated target=%s scenario=%s turn=%s", target_spec.id, scenario.id, index + 1)
    return Conversation(
        role_id=role.id,
        scenario_id=scenario.id,
        target_model=target_spec.id,
        turns=tuple(turns),
        metadata=metadata,
    )


def _generate_conversation_call(
    path: Path,
    scenario: ScenarioDefinition,
    turn: int,
    purpose: str,
    run_fingerprint: str,
    spec: ModelSpec,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
) -> GenerationResult:
    try:
        return generate_text(
            spec,
            system_prompt,
            messages,
            max_output_tokens=max_output_tokens,
        )
    except GenerationOutcomeError as exc:
        _append_jsonl(
            path.with_suffix(".generation-attempts.jsonl"),
            {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "scenario_id": scenario.id,
                "turn": turn,
                "model_id": spec.id,
                "purpose": purpose,
                "run_fingerprint": run_fingerprint,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "call": exc.result.to_dict(),
                "raw_response": exc.result.text,
            },
        )
        raise


def _generate_base_judgments(
    path: Path,
    role: RoleDefinition,
    scenario: ScenarioDefinition,
    conversation: Conversation,
    judge_specs: Sequence[ModelSpec],
    legacy_rubric: str,
    max_output_tokens: int,
    run_fingerprint: str,
) -> List[Dict[str, Any]]:
    artifacts = _read_jsonl(path) if path.is_file() else []
    conversation_fingerprint = _conversation_fingerprint(conversation)
    _validate_judgment_provenance(
        artifacts,
        path,
        run_fingerprint,
        conversation_fingerprint,
    )
    existing = {str(item["judge_id"]): item for item in artifacts}
    for judge_spec in judge_specs:
        if judge_spec.id in existing:
            continue
        if judge_spec.batch:
            raise SchemaError(
                f"Batch judgment is missing after batch processing: {judge_spec.id} {scenario.id}"
            )
        call_attempts = []
        last_error: Exception | None = None
        attempts = 1 if judge_spec.provider in EXPENSIVE_JUDGE_PROVIDERS else 3
        request = build_base_judge_request(
            role,
            scenario,
            conversation,
            legacy_rubric,
            keyed_findings=judge_spec.provider == "anthropic",
        )
        for _ in range(attempts):
            try:
                result = generate_text(
                    judge_spec,
                    request.system_prompt,
                    [{"role": "user", "content": request.user_prompt}],
                    max_output_tokens=max_output_tokens,
                    json_mode=True,
                    json_schema=_base_judge_json_schema(
                        role,
                        len(conversation.turns),
                        fixed_turn_keys=judge_spec.provider == "anthropic",
                        fixed_rule_keys=judge_spec.provider == "anthropic",
                    ),
                )
                call = result.to_dict()
                call["purpose"] = "judge"
                call["track"] = scenario.track
                call_attempts.append(call)
                _record_raw_judge_attempt(
                    path,
                    judge_spec,
                    scenario.id,
                    result,
                )
                artifact = parse_base_judge_response(
                    result.text,
                    judge_spec.id,
                    role,
                    len(conversation.turns),
                )
                artifact["metadata"] = {
                    "calls": call_attempts,
                    "raw_response": result.text,
                    "run_fingerprint": run_fingerprint,
                    "conversation_fingerprint": conversation_fingerprint,
                }
                _append_jsonl(path, artifact)
                existing[judge_spec.id] = artifact
                LOGGER.info("base judged judge=%s scenario=%s", judge_spec.id, scenario.id)
                break
            except RateLimitError:
                raise
            except GenerationOutcomeError as exc:
                _record_raw_judge_attempt(
                    path,
                    judge_spec,
                    scenario.id,
                    exc.result,
                    error=str(exc),
                    force=True,
                )
                raise SchemaError(
                    "Base judge returned a terminal generation outcome; "
                    "the response was preserved for audit and was not scored: "
                    f"{judge_spec.id} {scenario.id} {exc}"
                ) from exc
            except (KeyError, TypeError, ValueError, SchemaError, ProviderError) as exc:
                last_error = exc
        else:
            raise SchemaError(
                f"Base judge {judge_spec.id} returned invalid output after retries: {last_error}"
            )
    return [existing[spec.id] for spec in judge_specs]


def _generate_judgments(
    path: Path,
    role: RoleDefinition,
    scenario: ScenarioDefinition,
    conversation: Conversation,
    judge_specs: Sequence[ModelSpec],
    max_output_tokens: int,
    run_fingerprint: str,
) -> List[JudgeEvaluation]:
    artifacts = _read_jsonl(path) if path.is_file() else []
    conversation_fingerprint = _conversation_fingerprint(conversation)
    _validate_judgment_provenance(
        artifacts,
        path,
        run_fingerprint,
        conversation_fingerprint,
    )
    existing = {
        (str(item["judge_id"]), int(item["turn"])): item
        for item in artifacts
        if _is_complete_judge_artifact(item, role)
    }
    for turn in conversation.turns:
        for judge_spec in judge_specs:
            key = (judge_spec.id, turn.index)
            if key in existing:
                continue
            if judge_spec.batch:
                raise SchemaError(
                    "Batch judgment is missing after batch processing: "
                    f"{judge_spec.id} {scenario.id} turn {turn.index}"
                )
            call_attempts = []
            last_error: Exception | None = None
            attempts = 1 if judge_spec.provider in EXPENSIVE_JUDGE_PROVIDERS else 3
            request = build_judge_request(
                role,
                scenario,
                conversation,
                turn.index,
                keyed_findings=judge_spec.provider == "anthropic",
            )
            for _ in range(attempts):
                try:
                    result = generate_text(
                        judge_spec,
                        request.system_prompt,
                        [{"role": "user", "content": request.user_prompt}],
                        max_output_tokens=max_output_tokens,
                        json_mode=True,
                        json_schema=_judge_json_schema(
                            role,
                            string_scores=judge_spec.provider == "anthropic",
                            fixed_rule_keys=judge_spec.provider == "anthropic",
                        ),
                    )
                    call = result.to_dict()
                    call["purpose"] = "judge"
                    call["track"] = scenario.track
                    call_attempts.append(call)
                    _record_raw_judge_attempt(
                        path,
                        judge_spec,
                        scenario.id,
                        result,
                        turn=turn.index,
                    )
                    evaluation = parse_judge_response(
                        result.text,
                        judge_spec.id,
                        turn.index,
                        role,
                    )
                    artifact = evaluation.to_dict()
                    artifact["metadata"] = {
                        "calls": call_attempts,
                        "raw_response": result.text,
                        "run_fingerprint": run_fingerprint,
                        "conversation_fingerprint": conversation_fingerprint,
                    }
                    _append_jsonl(path, artifact)
                    existing[key] = artifact
                    LOGGER.info(
                        "judged judge=%s scenario=%s turn=%s",
                        judge_spec.id,
                        scenario.id,
                        turn.index,
                    )
                    break
                except RateLimitError:
                    raise
                except GenerationOutcomeError as exc:
                    _record_raw_judge_attempt(
                        path,
                        judge_spec,
                        scenario.id,
                        exc.result,
                        turn=turn.index,
                        error=str(exc),
                        force=True,
                    )
                    raise SchemaError(
                        "Judge returned a terminal generation outcome; "
                        "the response was preserved for audit and was not scored: "
                        f"{judge_spec.id} {scenario.id} turn {turn.index} {exc}"
                    ) from exc
                except (KeyError, TypeError, ValueError, SchemaError, ProviderError) as exc:
                    last_error = exc
            else:
                raise SchemaError(
                    f"Judge {judge_spec.id} returned invalid output after retries: {last_error}"
                )
    ordered = [existing[(spec.id, turn.index)] for turn in conversation.turns for spec in judge_specs]
    return [JudgeEvaluation.from_dict(item, role) for item in ordered]


def _base_judge_json_schema(
    role: RoleDefinition,
    turns: int,
    *,
    fixed_turn_keys: bool = False,
    fixed_rule_keys: bool = False,
) -> Dict[str, Any]:
    rule_ids = [rule.id for rule in role.judge_rules]
    score_schema: Dict[str, Any] = (
        {"type": "string", "enum": ["1", "2", "3", "4", "5"]}
        if fixed_turn_keys
        else {"type": "integer", "enum": [1, 2, 3, 4, 5]}
    )
    finding_properties = {
        "rule_id": {"type": "string", "enum": rule_ids},
        "verdict": {
            "type": "string",
            "enum": ["pass", "partial", "fail", "not_applicable"],
        },
        "confidence": {"type": "number"},
        "evidence": {"type": "string"},
        "rationale": {"type": "string"},
    }
    finding = {
        "type": "object",
        "properties": finding_properties,
        "required": ["rule_id", "verdict", "confidence", "evidence", "rationale"],
        "additionalProperties": False,
    }
    if fixed_rule_keys:
        keyed_finding = {
            "type": "object",
            "properties": {
                key: value
                for key, value in finding_properties.items()
                if key != "rule_id"
            },
            "required": ["verdict", "confidence", "evidence", "rationale"],
            "additionalProperties": False,
        }
        rule_findings_schema: Dict[str, Any] = {
            "type": "object",
            "properties": {rule_id: keyed_finding for rule_id in rule_ids},
            "required": rule_ids,
            "additionalProperties": False,
        }
    else:
        rule_findings_schema = {
            "type": "array",
            "items": finding,
            "minItems": len(rule_ids),
            "maxItems": len(rule_ids),
        }
    turn_fidelity = {
        "type": "object",
        "properties": {
            "turn": {"type": "integer", "enum": list(range(1, turns + 1))},
            "score": score_schema,
            "failed_rule_ids": {
                "type": "array",
                "items": {"type": "string", "enum": rule_ids},
            },
        },
        "required": ["turn", "score", "failed_rule_ids"],
        "additionalProperties": False,
    }
    if fixed_turn_keys:
        fixed_turn_value = {
            "type": "object",
            "properties": {
                "score": score_schema,
                "failed_rule_ids": {
                    "type": "array",
                    "items": {"type": "string", "enum": rule_ids},
                },
            },
            "required": ["score", "failed_rule_ids"],
            "additionalProperties": False,
        }
        turn_fidelity_schema: Dict[str, Any] = {
            "type": "object",
            "properties": {str(turn): fixed_turn_value for turn in range(1, turns + 1)},
            "required": [str(turn) for turn in range(1, turns + 1)],
            "additionalProperties": False,
        }
    else:
        turn_fidelity_schema = {
            "type": "array",
            "items": turn_fidelity,
            "minItems": turns,
            "maxItems": turns,
        }
    return {
        "type": "object",
        "properties": {
            "evaluation_reason": {"type": "string"},
            "legacy_scores": {
                "type": "object",
                "properties": {
                    dimension: score_schema
                    for dimension in LEGACY_DIMENSIONS
                },
                "required": list(LEGACY_DIMENSIONS),
                "additionalProperties": False,
            },
            "rule_findings": rule_findings_schema,
            "turn_fidelity": turn_fidelity_schema,
        },
        "required": ["evaluation_reason", "legacy_scores", "rule_findings", "turn_fidelity"],
        "additionalProperties": False,
    }


def _judge_json_schema(
    role: RoleDefinition,
    *,
    string_scores: bool = False,
    fixed_rule_keys: bool = False,
) -> Dict[str, Any]:
    rule_ids = [rule.id for rule in role.judge_rules]
    score_schema: Dict[str, Any] = (
        {"type": "string", "enum": ["1", "2", "3", "4", "5"]}
        if string_scores
        else {"type": "integer", "enum": [1, 2, 3, 4, 5]}
    )
    finding_properties = {
        "rule_id": {"type": "string", "enum": rule_ids},
        "verdict": {
            "type": "string",
            "enum": ["pass", "partial", "fail", "not_applicable"],
        },
        "confidence": {"type": "number"},
        "evidence": {"type": "string"},
        "rationale": {"type": "string"},
    }
    if fixed_rule_keys:
        keyed_finding = {
            "type": "object",
            "properties": {
                key: value
                for key, value in finding_properties.items()
                if key != "rule_id"
            },
            "required": ["verdict", "confidence", "evidence", "rationale"],
            "additionalProperties": False,
        }
        findings_schema: Dict[str, Any] = {
            "type": "object",
            "properties": {rule_id: keyed_finding for rule_id in rule_ids},
            "required": rule_ids,
            "additionalProperties": False,
        }
    else:
        findings_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": finding_properties,
                "required": [
                    "rule_id",
                    "verdict",
                    "confidence",
                    "evidence",
                    "rationale",
                ],
                "additionalProperties": False,
            },
            "minItems": len(rule_ids),
            "maxItems": len(rule_ids),
        }
    return {
        "type": "object",
        "properties": {
            "findings": findings_schema,
            "quality_scores": {
                "type": "object",
                "properties": {
                    dimension: score_schema
                    for dimension in QUALITY_DIMENSIONS
                },
                "required": list(QUALITY_DIMENSIONS),
                "additionalProperties": False,
            },
            "notes": {"type": "string"},
        },
        "required": ["findings", "quality_scores", "notes"],
        "additionalProperties": False,
    }


def _record_raw_judge_attempt(
    path: Path,
    judge_spec: ModelSpec,
    scenario_id: str,
    result: GenerationResult,
    *,
    turn: int | None = None,
    error: str | None = None,
    force: bool = False,
) -> None:
    if not force and judge_spec.provider not in EXPENSIVE_JUDGE_PROVIDERS:
        return
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "scenario_id": scenario_id,
        "turn": turn,
        "judge_id": judge_spec.id,
        "call": result.to_dict(),
        "raw_response": result.text,
    }
    if error is not None:
        record["error"] = error
    _append_jsonl(
        path.with_suffix(".raw-attempts.jsonl"),
        record,
    )


def _target_system_prompt(role: RoleDefinition) -> str:
    original = role.metadata.get("assistant_system_prompt")
    if original:
        return str(original)
    payload = {
        "role_id": role.id,
        "name": role.name,
        "language": role.language,
        "profile": role.profile,
        "requirements": [rule.description for rule in role.rules],
    }
    return (
        "あなたは次の設定で会話するキャラクターです。設定と要件を全ターンで維持してください。"
        "ルールや評価について説明せず、キャラクターとして自然な日本語だけを返してください。"
        "ユーザーの台詞、感情、行動を勝手に確定しないでください。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _user_system_prompt(scenario: ScenarioDefinition) -> str:
    prompt = scenario.metadata.get("user_system_prompt")
    if not prompt:
        raise SchemaError(f"Simulated scenario is missing user_system_prompt: {scenario.id}")
    return str(prompt)


def _build_leaderboard(
    output_root: Path,
    reports: Sequence[Mapping[str, Any]],
    target_specs: Sequence[ModelSpec],
    judge_specs: Sequence[ModelSpec],
    user_spec: ModelSpec | None,
    run_fingerprint: str,
) -> Dict[str, Any]:
    all_specs = [*target_specs, *judge_specs]
    if user_spec is not None:
        all_specs.append(user_spec)
    specs = {spec.id: spec for spec in all_specs}
    usage_by_model: Dict[str, Dict[str, Any]] = {}
    for spec_id, spec in specs.items():
        usage_by_model[spec_id] = {
            "provider": spec.provider,
            "model": spec.model,
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cached_input_tokens": 0,
            "estimated_list_cost_usd": 0.0,
            "estimated_effective_cost_usd": 0.0,
        }

    for path in (output_root / "conversations").glob("**/*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        for call in value.get("metadata", {}).get("generation_calls", []):
            _accumulate_usage(usage_by_model, specs, call)
    for path in (output_root / "judgments").glob("**/*.jsonl"):
        for value in _read_jsonl(path):
            for call in value.get("metadata", {}).get("calls", []):
                _accumulate_usage(usage_by_model, specs, call)

    targets: Dict[str, Any] = {}
    for target in target_specs:
        target_reports = [report for report in reports if report["target_model"] == target.id]
        metrics = {}
        for metric in SUMMARY_METRICS:
            values = [report["summary"].get(metric) for report in target_reports]
            present = [float(value) for value in values if value is not None]
            metrics[metric] = None if not present else round(mean(present), 3)
        tracks: Dict[str, Dict[str, Any]] = {}
        for track in sorted({str(report["track"]) for report in target_reports}):
            track_reports = [report for report in target_reports if report["track"] == track]
            track_values = [
                float(report["summary"]["core_fidelity_score"])
                for report in track_reports
                if report["summary"]["core_fidelity_score"] is not None
            ]
            tracks[track] = {
                "scenarios": len(track_reports),
                "core_fidelity_score": None if not track_values else round(mean(track_values), 3),
            }
        targets[target.id] = {
            "provider": target.provider,
            "model": target.model,
            "scenarios": len(target_reports),
            "major_violations": sum(int(report["summary"]["major_violations"]) for report in target_reports),
            "eligible_scenarios": sum(bool(report["summary"]["eligible_for_overall"]) for report in target_reports),
            "metrics": metrics,
            "tracks": tracks,
        }
        base_reports = [report for report in target_reports if report["track"] == "legacy-base"]
        if base_reports:
            dimension_names = list(base_reports[0]["legacy"]["dimension_scores"])
            dimensions = {
                dimension: round(
                    mean(float(report["legacy"]["dimension_scores"][dimension]) for report in base_reports),
                    3,
                )
                for dimension in dimension_names
            }
            targets[target.id]["legacy_base"] = {
                "cases": len(base_reports),
                "turns_per_case": len(base_reports[0]["turns"]),
                "overall_average": round(mean(dimensions.values()), 3),
                "dimension_scores": dimensions,
                "comparison_note": (
                    "Same original 30 settings and rubric; current user simulator and judges differ "
                    "from the frozen 2024 protocol."
                ),
            }
    for usage in usage_by_model.values():
        usage["estimated_list_cost_usd"] = round(usage["estimated_list_cost_usd"], 6)
        usage["estimated_effective_cost_usd"] = round(
            usage["estimated_effective_cost_usd"], 6
        )
    return {
        "schema_version": "2.0",
        "run_fingerprint": run_fingerprint,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "targets": targets,
        "usage_by_model": usage_by_model,
        "estimated_list_cost_usd": round(
            sum(value["estimated_list_cost_usd"] for value in usage_by_model.values()),
            6,
        ),
        "estimated_effective_cost_usd": round(
            sum(value["estimated_effective_cost_usd"] for value in usage_by_model.values()),
            6,
        ),
        "notes": [
            "Scores are macro-averaged across scenarios; no weighted overall score is defined.",
            "List costs do not account for discounts; effective costs apply the 50% "
            "OpenAI/Gemini/Anthropic Batch API multiplier recorded on each call.",
            "Effective costs do not account for free tiers or data-sharing incentives.",
        ],
    }


def _accumulate_usage(
    usage_by_model: Dict[str, Dict[str, Any]],
    specs: Mapping[str, ModelSpec],
    call: Mapping[str, Any],
) -> None:
    spec_id = str(call["requested_model"])
    if spec_id not in usage_by_model:
        return
    usage = usage_by_model[spec_id]
    for key in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens"):
        usage[key] += int(call.get(key, 0))
    result = GenerationResult(**{key: call.get(key, default) for key, default in {
        "text": "",
        "requested_model": spec_id,
        "resolved_model": str(call.get("resolved_model", "")),
        "provider": str(call.get("provider", specs[spec_id].provider)),
        "response_id": str(call.get("response_id", "")),
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cached_input_tokens": 0,
        "billing_mode": str(call.get("billing_mode", "standard")),
    }.items()})
    list_cost = estimated_list_cost(specs[spec_id], result)
    usage["estimated_list_cost_usd"] += list_cost
    usage["estimated_effective_cost_usd"] += list_cost * (
        0.5 if result.billing_mode == "batch" else 1.0
    )


def _build_run_fingerprint(
    config: Mapping[str, Any],
    role_packs: Sequence[RolePack],
    base_cases: Sequence[Mapping[str, Any]],
    legacy_rubric: str,
) -> Tuple[str, Dict[str, Any]]:
    source_root = Path(__file__).resolve().parent
    source_hashes = {
        name: _sha256_bytes((source_root / name).read_bytes())
        for name in FINGERPRINT_SOURCE_FILES
    }
    components = {
        "schema_version": RUN_FINGERPRINT_SCHEMA_VERSION,
        "config_sha256": _json_sha256(config),
        "role_packs_sha256": _json_sha256([asdict(pack) for pack in role_packs]),
        "base_cases_sha256": _json_sha256(base_cases),
        "legacy_rubric_sha256": _sha256_bytes(legacy_rubric.encode("utf-8")),
        "source_sha256": source_hashes,
    }
    return _json_sha256(components), components


def _prepare_run_manifest(
    output_root: Path,
    config_file: Path,
    role_packs: Sequence[RolePack],
    target_specs: Sequence[ModelSpec],
    judge_specs: Sequence[ModelSpec],
    user_spec: ModelSpec | None,
    workers: int,
    run_fingerprint: str,
    fingerprint_components: Mapping[str, Any],
) -> Dict[str, Any]:
    manifest_path = output_root / "manifest.json"
    now = datetime.now(timezone.utc).isoformat()
    if manifest_path.is_file():
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise SchemaError(f"Existing run manifest is not an object: {manifest_path}")
        _require_run_fingerprint(value, run_fingerprint, manifest_path, "run manifest")
        manifest = dict(value)
        manifest["resumed_at"] = now
    else:
        if _has_benchmark_artifacts(output_root):
            raise SchemaError(
                "Existing benchmark artifacts have no run manifest and cannot be resumed safely: "
                f"{output_root}. Use a new empty output directory."
            )
        manifest = {
            "schema_version": "2.1",
            "started_at": now,
        }
    manifest.update(
        {
            "status": "running",
            "config": str(config_file),
            "role_packs": [
                {"id": pack.id, "version": pack.version} for pack in role_packs
            ],
            "targets": [_public_model_spec(spec) for spec in target_specs],
            "judges": [_public_model_spec(spec) for spec in judge_specs],
            "user_simulator": (
                None if user_spec is None else _public_model_spec(user_spec)
            ),
            "workers": workers,
            "run_fingerprint": run_fingerprint,
            "fingerprint_components": dict(fingerprint_components),
        }
    )
    _write_json(manifest_path, manifest)
    return manifest


def _has_benchmark_artifacts(output_root: Path) -> bool:
    return any(
        (output_root / name).exists()
        for name in (
            "conversations",
            "judgments",
            "reports",
            "batches",
            "dataset",
            "leaderboard.json",
            "pilot-report.json",
        )
    )


def _preflight_resume_artifacts(
    output_root: Path,
    jobs: Sequence[Tuple[RolePack, ScenarioDefinition, ModelSpec]],
    run_fingerprint: str,
) -> None:
    expected_reports = set()
    for role_pack, scenario, target_spec in jobs:
        stem = f"{_safe_name(role_pack.id)}__{_safe_name(scenario.id)}"
        target_dir = _safe_name(target_spec.id)
        conversation_path = output_root / "conversations" / target_dir / f"{stem}.json"
        pending_path = conversation_path.with_suffix(".pending-user.json")
        judgment_path = output_root / "judgments" / target_dir / f"{stem}.jsonl"
        report_path = output_root / "reports" / target_dir / f"{stem}.json"
        expected_reports.add(report_path)

        conversation: Conversation | None = None
        if conversation_path.is_file():
            conversation = Conversation.from_dict(
                json.loads(conversation_path.read_text(encoding="utf-8"))
            )
            _require_run_fingerprint(
                conversation.metadata,
                run_fingerprint,
                conversation_path,
                "conversation",
            )
        if pending_path.is_file():
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            if not isinstance(pending, Mapping):
                raise SchemaError(
                    f"Pending user checkpoint is not an object: {pending_path}"
                )
            _require_run_fingerprint(
                pending,
                run_fingerprint,
                pending_path,
                "pending user checkpoint",
            )
        if judgment_path.is_file():
            if conversation is None:
                raise SchemaError(
                    "Existing judgments have no matching conversation and cannot be resumed "
                    f"safely: {judgment_path}"
                )
            _validate_judgment_provenance(
                _read_jsonl(judgment_path),
                judgment_path,
                run_fingerprint,
                _conversation_fingerprint(conversation),
            )
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(report, Mapping):
                raise SchemaError(f"Existing report is not an object: {report_path}")
            _require_run_fingerprint(report, run_fingerprint, report_path, "report")

    for state_path in (output_root / "batches").glob("**/attempt-*.json"):
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, Mapping):
            raise SchemaError(f"Existing batch state is not an object: {state_path}")
        _require_run_fingerprint(state, run_fingerprint, state_path, "batch state")

    for report_path in (output_root / "reports").glob("**/*.json"):
        if report_path not in expected_reports:
            raise SchemaError(
                "Existing report is not part of the current run configuration: "
                f"{report_path}"
            )


def _require_run_fingerprint(
    value: Mapping[str, Any],
    expected: str,
    path: Path,
    artifact_name: str,
) -> None:
    actual = value.get("run_fingerprint")
    if not actual:
        raise SchemaError(
            f"Existing {artifact_name} has no run_fingerprint and cannot be reused safely: "
            f"{path}"
        )
    if str(actual) != expected:
        raise SchemaError(
            f"Existing {artifact_name} run_fingerprint mismatch: {path}; "
            f"expected {expected}, found {actual}"
        )


def _conversation_fingerprint(conversation: Conversation) -> str:
    return _json_sha256(
        {
            "role_id": conversation.role_id,
            "scenario_id": conversation.scenario_id,
            "target_model": conversation.target_model,
            "turns": [asdict(turn) for turn in conversation.turns],
        }
    )


def _validate_judgment_provenance(
    artifacts: Sequence[Mapping[str, Any]],
    path: Path,
    run_fingerprint: str,
    conversation_fingerprint: str,
) -> None:
    for index, artifact in enumerate(artifacts, start=1):
        metadata = artifact.get("metadata")
        if not isinstance(metadata, Mapping):
            raise SchemaError(
                f"Existing judgment has no provenance metadata: {path} line {index}"
            )
        _require_run_fingerprint(
            metadata,
            run_fingerprint,
            path,
            f"judgment line {index}",
        )
        actual_conversation = metadata.get("conversation_fingerprint")
        if not actual_conversation:
            raise SchemaError(
                "Existing judgment has no conversation_fingerprint and cannot be reused "
                f"safely: {path} line {index}"
            )
        if str(actual_conversation) != conversation_fingerprint:
            raise SchemaError(
                f"Existing judgment conversation_fingerprint mismatch: {path} line {index}; "
                f"expected {conversation_fingerprint}, found {actual_conversation}"
            )


def _json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_model_specs(config: Mapping[str, Any], key: str) -> List[ModelSpec]:
    values = (config.get("models") or {}).get(key, [])
    if not isinstance(values, list) or not values:
        raise SchemaError(f"Benchmark config models.{key} must be a non-empty list")
    specs = [ModelSpec.from_dict(value) for value in values]
    ids = [spec.id for spec in specs]
    if len(ids) != len(set(ids)):
        raise SchemaError(f"Benchmark config models.{key} contains duplicate ids")
    return specs


def _load_optional_model_spec(config: Mapping[str, Any], key: str) -> ModelSpec | None:
    value = (config.get("models") or {}).get(key)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise SchemaError(f"Benchmark config models.{key} must be an object")
    return ModelSpec.from_dict(value)


def _validate_credentials_available(
    target_specs: Sequence[ModelSpec],
    judge_specs: Sequence[ModelSpec],
    user_spec: ModelSpec | None,
) -> None:
    """Fail before any provider submission when a configured credential is missing."""
    specs = [*target_specs, *judge_specs]
    if user_spec is not None:
        specs.append(user_spec)
    required = sorted({spec.api_key_env for spec in specs})
    invalid = [name for name in required if not name]
    if invalid:
        raise SchemaError("Configured model has an empty api_key_env")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ProviderError(
            "Required provider credentials are missing; no benchmark requests were "
            f"submitted: {', '.join(missing)}"
        )


def _load_yaml(path: Path) -> Mapping[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise SchemaError("Benchmark config YAML root must be an object")
    return value


def _generation_limits(config: Mapping[str, Any]) -> Tuple[int, int]:
    generation = config.get("generation")
    if not isinstance(generation, Mapping):
        raise SchemaError("Benchmark config generation must be an object")
    if "max_output_tokens" in generation:
        raise SchemaError(
            "generation.max_output_tokens is ambiguous; use target_max_output_tokens "
            "and user_max_output_tokens"
        )
    missing = [
        key
        for key in ("target_max_output_tokens", "user_max_output_tokens")
        if key not in generation
    ]
    if missing:
        raise SchemaError(f"Benchmark config generation is missing: {', '.join(missing)}")
    target_limit = int(generation["target_max_output_tokens"])
    user_limit = int(generation["user_max_output_tokens"])
    if target_limit < 1 or user_limit < 1:
        raise SchemaError("Generation output token limits must be positive")
    return target_limit, user_limit


def _sync_rate_limit_policy(config: Mapping[str, Any]) -> Tuple[int, float]:
    generation = config.get("generation") or {}
    if not isinstance(generation, Mapping):
        raise SchemaError("Benchmark config generation must be an object")
    max_attempts = int(generation.get("sync_rate_limit_max_attempts", 3))
    backoff_seconds = float(generation.get("sync_rate_limit_backoff_seconds", 30))
    if max_attempts < 1:
        raise SchemaError("generation.sync_rate_limit_max_attempts must be at least 1")
    if backoff_seconds < 0:
        raise SchemaError(
            "generation.sync_rate_limit_backoff_seconds must be zero or greater"
        )
    return max_attempts, backoff_seconds


def _validate_required_pilot_report(
    config: Mapping[str, Any],
    target_specs: Sequence[ModelSpec],
    judge_specs: Sequence[ModelSpec],
    target_limit: int,
    user_limit: int,
    challenge_judge_limit: int,
    base_judge_limit: int,
    protocol_fingerprint: str,
    pilot_report_path: str | Path | None,
) -> Dict[str, Any] | None:
    if "pilot" not in config:
        return None
    if pilot_report_path is None:
        raise SchemaError(
            "This benchmark config requires a passing generation pilot; provide --pilot-report"
        )
    path = Path(pilot_report_path).resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise SchemaError(f"Pilot report is not an object: {path}")
    if value.get("passed") is not True:
        raise SchemaError(f"Pilot report did not pass: {path}")
    if str(value.get("config_sha256", "")) != _json_sha256(config):
        raise SchemaError(f"Pilot report was produced from a different config: {path}")
    if str(value.get("protocol_fingerprint", "")) != protocol_fingerprint:
        raise SchemaError(
            "Pilot report was produced from a different implementation, Role Pack, "
            f"dataset, or rubric: {path}"
        )
    expected_targets = {spec.id for spec in target_specs}
    actual_counts = value.get("target_call_counts")
    if not isinstance(actual_counts, Mapping) or set(actual_counts) != expected_targets:
        raise SchemaError(f"Pilot report target coverage does not match the benchmark: {path}")
    if any(int(actual_counts[target]) < 1 for target in expected_targets):
        raise SchemaError(f"Pilot report has an untested target: {path}")
    if int(value.get("target_max_output_tokens", 0)) != target_limit:
        raise SchemaError(f"Pilot report target output limit does not match: {path}")
    if int(value.get("user_max_output_tokens", 0)) != user_limit:
        raise SchemaError(f"Pilot report user output limit does not match: {path}")
    expected_judges = {spec.id for spec in judge_specs}
    actual_judge_counts = value.get("judge_call_counts")
    if not isinstance(actual_judge_counts, Mapping) or set(actual_judge_counts) != expected_judges:
        raise SchemaError(f"Pilot report Judge coverage does not match the benchmark: {path}")
    if any(int(actual_judge_counts[judge]) < 1 for judge in expected_judges):
        raise SchemaError(f"Pilot report has an untested Judge: {path}")
    if int(value.get("challenge_judge_max_output_tokens", 0)) != challenge_judge_limit:
        raise SchemaError(f"Pilot report Challenge Judge output limit does not match: {path}")
    if int(value.get("base_judge_max_output_tokens", 0)) != base_judge_limit:
        raise SchemaError(f"Pilot report Base Judge output limit does not match: {path}")
    if int(value.get("truncation_count", -1)) != 0:
        raise SchemaError(f"Pilot report contains truncated generations: {path}")
    return {
        "path": str(path),
        "sha256": _sha256_bytes(path.read_bytes()),
        "run_fingerprint": str(value.get("run_fingerprint", "")),
        "protocol_fingerprint": str(value.get("protocol_fingerprint", "")),
        "passed": True,
    }


def _batch_policy(config: Mapping[str, Any]) -> Tuple[float, int]:
    batch = config.get("batch") or {}
    if not isinstance(batch, Mapping):
        raise SchemaError("Benchmark config batch must be an object")
    poll_interval = float(batch.get("poll_interval_seconds", 30))
    max_attempts = int(batch.get("max_attempts", 2))
    if poll_interval < 1:
        raise SchemaError("batch.poll_interval_seconds must be at least 1")
    if max_attempts < 1:
        raise SchemaError("batch.max_attempts must be at least 1")
    return poll_interval, max_attempts


def _batch_limit_payload(spec: ModelSpec, max_output_tokens: int) -> Dict[str, Any]:
    if spec.provider == "openai":
        return {"max_output_tokens": max_output_tokens}
    if spec.provider == "gemini":
        return {"generationConfig": {"maxOutputTokens": max_output_tokens}}
    if spec.provider == "anthropic":
        return {"max_tokens": max_output_tokens}
    raise SchemaError(f"Provider does not support batch execution: {spec.provider}")


def _public_model_spec(spec: ModelSpec) -> Dict[str, Any]:
    value = asdict(spec)
    value.pop("api_key_env", None)
    return value


def _conversation_to_dict(conversation: Conversation) -> Dict[str, Any]:
    return {
        "role_id": conversation.role_id,
        "scenario_id": conversation.scenario_id,
        "target_model": conversation.target_model,
        "turns": [asdict(turn) for turn in conversation.turns],
        "metadata": dict(conversation.metadata),
    }


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise SchemaError(f"JSONL line must be an object: {path}")
            values.append(value)
    return values


def _append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )
    temporary.replace(path)


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_." else "-" for character in value)
