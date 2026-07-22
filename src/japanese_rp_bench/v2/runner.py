"""Resumable end-to-end benchmark runner for v2 role packs."""

from __future__ import annotations

import json
import logging
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


def run_benchmark(config_path: str | Path, output_path: str | Path, workers: int = 4) -> Dict[str, Any]:
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

    output_root.mkdir(parents=True, exist_ok=True)
    if base_cases:
        _write_jsonl(output_root / "dataset" / "legacy-base.jsonl", base_cases)
    legacy_prompt_file = Path(
        config["evaluation"].get("legacy_prompt_file", "prompts/eval_prompt_SFW.txt")
    ).resolve()
    legacy_rubric = legacy_prompt_file.read_text(encoding="utf-8") if base_enabled else ""
    manifest = {
        "schema_version": "2.0",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "config": str(config_file),
        "role_packs": [{"id": pack.id, "version": pack.version} for pack in role_packs],
        "targets": [_public_model_spec(spec) for spec in target_specs],
        "judges": [_public_model_spec(spec) for spec in judge_specs],
        "user_simulator": None if user_spec is None else _public_model_spec(user_spec),
        "workers": workers,
    }
    _write_json(output_root / "manifest.json", manifest)

    jobs = [
        (pack, scenario, target)
        for target in target_specs
        for pack in role_packs
        for scenario in pack.scenarios.values()
    ]
    jobs.sort(
        key=lambda job: (
            output_root
            / "reports"
            / _safe_name(job[2].id)
            / f"{_safe_name(job[0].id)}__{_safe_name(job[1].id)}.json"
        ).is_file()
    )

    # Finish and checkpoint all target conversations before any paid judge work.
    # This keeps an invalid judge response from blocking the remaining target
    # generation and lets a resumed run reuse every completed conversation.
    generation_executor = ThreadPoolExecutor(max_workers=workers)
    generation_futures = {
        generation_executor.submit(
            _generate_scenario_conversation,
            output_root,
            pack,
            scenario,
            target,
            user_spec,
            int(config["generation"].get("max_output_tokens", 384)),
        ): (target.id, pack.id, scenario.id)
        for pack, scenario, target in jobs
    }
    try:
        for future in as_completed(generation_futures):
            future.result()
    except Exception:
        for pending in generation_futures:
            pending.cancel()
        generation_executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        generation_executor.shutdown(wait=True)

    _run_batch_judges(
        output_root,
        jobs,
        judge_specs,
        config,
        legacy_rubric,
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

    leaderboard = _build_leaderboard(output_root, reports, target_specs, judge_specs, user_spec)
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    manifest["status"] = "partial" if failures else "complete"
    manifest["failures"] = failures
    _write_json(output_root / "manifest.json", manifest)
    _write_json(output_root / "leaderboard.json", leaderboard)
    return leaderboard


def _generate_scenario_conversation(
    output_root: Path,
    role_pack: RolePack,
    scenario: ScenarioDefinition,
    target_spec: ModelSpec,
    user_spec: ModelSpec | None,
    max_output_tokens: int,
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
        max_output_tokens,
    )


def _run_batch_judges(
    output_root: Path,
    jobs: Sequence[Tuple[RolePack, ScenarioDefinition, ModelSpec]],
    judge_specs: Sequence[ModelSpec],
    config: Mapping[str, Any],
    legacy_rubric: str,
) -> None:
    batch_specs = [spec for spec in judge_specs if spec.batch]
    if not batch_specs:
        return
    batch_config = config["evaluation"].get("batch") or {}
    poll_interval = float(batch_config.get("poll_interval_seconds", 30))
    max_attempts = int(batch_config.get("max_attempts", 2))
    if poll_interval < 1:
        raise SchemaError("evaluation.batch.poll_interval_seconds must be at least 1")
    if max_attempts < 1:
        raise SchemaError("evaluation.batch.max_attempts must be at least 1")

    while True:
        active: List[Tuple[ModelSpec, Path, Dict[str, Any]]] = []
        pending_by_spec: Dict[str, List[_BatchJudgeTask]] = {
            spec.id: _collect_batch_judge_tasks(
                output_root,
                jobs,
                spec,
                config,
                legacy_rubric,
            )
            for spec in batch_specs
        }
        for spec in batch_specs:
            batch_dir = output_root / "batches" / _safe_name(spec.id)
            state_paths = sorted(batch_dir.glob("attempt-*.json"))
            unprocessed = []
            for path in state_paths:
                state_value = json.loads(path.read_text(encoding="utf-8"))
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
            submitted = submit_batch(
                spec,
                provider_requests,
                f"japanese-rp-bench-{_safe_name(spec.id)}-a{attempt}",
            )
            state = {
                "schema_version": "1.0",
                "judge_id": spec.id,
                "provider": spec.provider,
                "model": spec.model,
                "attempt": attempt,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "batch_id": submitted["batch_id"],
                "provider_response": submitted["provider_response"],
                "requests": [
                    {"custom_id": request.custom_id, "task_key": task.key}
                    for request, task in zip(provider_requests, pending)
                ],
            }
            state_path = batch_dir / f"attempt-{attempt:02d}.json"
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

        for spec, state_path, state in active:
            batch_id = str(state["batch_id"])
            status = wait_for_batch(spec, batch_id, poll_interval)
            request_refs = state.get("requests") or []
            provider_requests = [
                BatchRequest(str(item["custom_id"]), {}) for item in request_refs
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
                )
            }
            custom_to_key = {
                str(item["custom_id"]): str(item["task_key"])
                for item in request_refs
            }
            errors: List[Dict[str, str]] = []
            for item in results:
                task_key = custom_to_key.get(item.custom_id)
                task = task_map.get(task_key or "")
                if task is None:
                    continue
                if item.generation is None:
                    errors.append(
                        {
                            "custom_id": item.custom_id,
                            "task_key": task.key,
                            "error": item.error or "unknown batch result error",
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


def _collect_batch_judge_tasks(
    output_root: Path,
    jobs: Sequence[Tuple[RolePack, ScenarioDefinition, ModelSpec]],
    judge_spec: ModelSpec,
    config: Mapping[str, Any],
    legacy_rubric: str,
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
        judgment_path = (
            output_root / "judgments" / _safe_name(target_spec.id) / f"{stem}.jsonl"
        )
        artifacts = _read_jsonl(judgment_path) if judgment_path.is_file() else []
        if scenario.track == "legacy-base":
            if any(str(item.get("judge_id")) == judge_spec.id for item in artifacts):
                continue
            request = build_base_judge_request(role, scenario, conversation, legacy_rubric)
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
                        config["evaluation"].get("base_judge_max_output_tokens", 6144)
                    ),
                    json_schema=_base_judge_json_schema(
                        role,
                        len(conversation.turns),
                        fixed_turn_keys=judge_spec.provider == "anthropic",
                    ),
                )
            )
            continue

        existing = {
            (str(item.get("judge_id")), int(item.get("turn", 0)))
            for item in artifacts
            if _is_complete_judge_artifact(item, role)
        }
        for turn in conversation.turns:
            if (judge_spec.id, turn.index) in existing:
                continue
            request = build_judge_request(role, scenario, conversation, turn.index)
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
                    system_prompt=request.system_prompt,
                    user_prompt=request.user_prompt,
                    max_output_tokens=int(config["evaluation"].get("judge_max_output_tokens", 4096)),
                    json_schema=_judge_json_schema(
                        role,
                        string_scores=judge_spec.provider == "anthropic",
                    ),
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
    artifact["metadata"] = {
        "calls": [result.to_dict()],
        "raw_response": result.text,
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
) -> Dict[str, Any]:
    role = role_pack.roles[scenario.role_id]
    stem = f"{_safe_name(role_pack.id)}__{_safe_name(scenario.id)}"
    conversation_path = output_root / "conversations" / _safe_name(target_spec.id) / f"{stem}.json"
    judgments_path = output_root / "judgments" / _safe_name(target_spec.id) / f"{stem}.jsonl"
    report_path = output_root / "reports" / _safe_name(target_spec.id) / f"{stem}.json"

    conversation = _generate_conversation(
        conversation_path,
        role,
        scenario,
        target_spec,
        user_spec,
        int(config["generation"].get("max_output_tokens", 384)),
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
            int(config["evaluation"].get("base_judge_max_output_tokens", 6144)),
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
    _write_json(report_path, report)
    return report


def _generate_conversation(
    path: Path,
    role: RoleDefinition,
    scenario: ScenarioDefinition,
    target_spec: ModelSpec,
    user_spec: ModelSpec | None,
    max_output_tokens: int,
) -> Conversation:
    pending_path = path.with_suffix(".pending-user.json")
    if path.is_file():
        existing = Conversation.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if existing.target_model != target_spec.id:
            raise SchemaError(f"Existing conversation target mismatch: {path}")
        turns = list(existing.turns)
        metadata = dict(existing.metadata)
    else:
        turns = []
        metadata = {"generation_calls": []}
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
            user_result = generate_text(
                user_spec,
                _user_system_prompt(scenario),
                user_messages,
                max_output_tokens=max_output_tokens,
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
            },
        )
        if user_call is not None:
            metadata.setdefault("generation_calls", []).append(user_call)
        messages: List[Dict[str, str]] = []
        for item in turns:
            messages.append({"role": "user", "content": item.user})
            messages.append({"role": "assistant", "content": item.assistant})
        messages.append({"role": "user", "content": user_message})
        result = generate_text(
            target_spec,
            system_prompt,
            messages,
            max_output_tokens=max_output_tokens,
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


def _generate_base_judgments(
    path: Path,
    role: RoleDefinition,
    scenario: ScenarioDefinition,
    conversation: Conversation,
    judge_specs: Sequence[ModelSpec],
    legacy_rubric: str,
    max_output_tokens: int,
) -> List[Dict[str, Any]]:
    artifacts = _read_jsonl(path) if path.is_file() else []
    existing = {str(item["judge_id"]): item for item in artifacts}
    request = build_base_judge_request(role, scenario, conversation, legacy_rubric)
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
                    ),
                )
                call_attempts.append(result.to_dict())
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
                artifact["metadata"] = {"calls": call_attempts, "raw_response": result.text}
                _append_jsonl(path, artifact)
                existing[judge_spec.id] = artifact
                LOGGER.info("base judged judge=%s scenario=%s", judge_spec.id, scenario.id)
                break
            except RateLimitError:
                raise
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
) -> List[JudgeEvaluation]:
    artifacts = _read_jsonl(path) if path.is_file() else []
    existing = {
        (str(item["judge_id"]), int(item["turn"])): item
        for item in artifacts
        if _is_complete_judge_artifact(item, role)
    }
    for turn in conversation.turns:
        request = build_judge_request(role, scenario, conversation, turn.index)
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
                        ),
                    )
                    call_attempts.append(result.to_dict())
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
) -> Dict[str, Any]:
    rule_ids = [rule.id for rule in role.judge_rules]
    score_schema = (
        {"type": "string", "enum": ["1", "2", "3", "4", "5"]}
        if fixed_turn_keys
        else {"type": "integer", "enum": [1, 2, 3, 4, 5]}
    )
    finding = {
        "type": "object",
        "properties": {
            "rule_id": {"type": "string", "enum": rule_ids},
            "verdict": {
                "type": "string",
                "enum": ["pass", "partial", "fail", "not_applicable"],
            },
            "confidence": {"type": "number"},
            "evidence": {"type": "string"},
            "rationale": {"type": "string"},
        },
        "required": ["rule_id", "verdict", "confidence", "evidence", "rationale"],
        "additionalProperties": False,
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
            "rule_findings": {
                "type": "array",
                "items": finding,
                "minItems": len(rule_ids),
                "maxItems": len(rule_ids),
            },
            "turn_fidelity": turn_fidelity_schema,
        },
        "required": ["evaluation_reason", "legacy_scores", "rule_findings", "turn_fidelity"],
        "additionalProperties": False,
    }


def _judge_json_schema(
    role: RoleDefinition,
    *,
    string_scores: bool = False,
) -> Dict[str, Any]:
    rule_ids = [rule.id for rule in role.judge_rules]
    score_schema = (
        {"type": "string", "enum": ["1", "2", "3", "4", "5"]}
        if string_scores
        else {"type": "integer", "enum": [1, 2, 3, 4, 5]}
    )
    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string", "enum": rule_ids},
                        "verdict": {
                            "type": "string",
                            "enum": ["pass", "partial", "fail", "not_applicable"],
                        },
                        "confidence": {"type": "number"},
                        "evidence": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
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
            },
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
) -> None:
    if judge_spec.provider not in EXPENSIVE_JUDGE_PROVIDERS:
        return
    _append_jsonl(
        path.with_suffix(".raw-attempts.jsonl"),
        {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "scenario_id": scenario_id,
            "turn": turn,
            "judge_id": judge_spec.id,
            "call": result.to_dict(),
            "raw_response": result.text,
        },
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
            "Gemini/Anthropic Batch API multiplier recorded on each call.",
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


def _load_yaml(path: Path) -> Mapping[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise SchemaError("Benchmark config YAML root must be an object")
    return value


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
