"""CLI for validating role packs and scoring provider-neutral artifacts."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Iterable, List

from japanese_rp_bench.v2.judge import build_judge_request
from japanese_rp_bench.v2.legacy import build_legacy_snapshot, legacy_snapshot_markdown
from japanese_rp_bench.v2.providers import ProviderError
from japanese_rp_bench.v2.rolepacks import load_role_pack
from japanese_rp_bench.v2.runner import run_benchmark
from japanese_rp_bench.v2.scoring import resolve_conversation, score_conversation
from japanese_rp_bench.v2.schemas import Conversation, JudgeEvaluation, SchemaError


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="japanese-rp-bench-v2",
        description="Model-independent role fidelity evaluation tools",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate a role pack")
    validate_parser.add_argument("role_pack")

    requests_parser = subparsers.add_parser(
        "prepare-judging", help="Export provider-neutral judge requests as JSONL"
    )
    requests_parser.add_argument("--role-pack", required=True)
    requests_parser.add_argument("--conversation", required=True)
    requests_parser.add_argument("--output", required=True)

    score_parser = subparsers.add_parser(
        "score", help="Combine deterministic checks with judge JSONL results"
    )
    score_parser.add_argument("--role-pack", required=True)
    score_parser.add_argument("--conversation", required=True)
    score_parser.add_argument("--judgments")
    score_parser.add_argument("--minimum-judges", type=int, default=2)
    score_parser.add_argument("--output", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Generate conversations, run judges, and build a leaderboard"
    )
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--workers", type=int, default=4)

    legacy_parser = subparsers.add_parser(
        "legacy-snapshot",
        help="Reconstruct the frozen 2024 leaderboard from checked-in evaluations",
    )
    legacy_parser.add_argument("--evaluations", default="evaluations")
    legacy_parser.add_argument("--output", required=True)
    legacy_parser.add_argument("--markdown")

    args = parser.parse_args()
    try:
        if args.command == "validate":
            _validate(args.role_pack)
        elif args.command == "prepare-judging":
            _prepare_judging(args.role_pack, args.conversation, args.output)
        elif args.command == "score":
            _score(
                args.role_pack,
                args.conversation,
                args.judgments,
                args.output,
                args.minimum_judges,
            )
        elif args.command == "run":
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
            leaderboard = run_benchmark(args.config, args.output, workers=args.workers)
            print(json.dumps(leaderboard, ensure_ascii=False, indent=2))
        elif args.command == "legacy-snapshot":
            snapshot = build_legacy_snapshot(args.evaluations)
            _write_json(args.output, snapshot)
            if args.markdown:
                target = Path(args.markdown)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(legacy_snapshot_markdown(snapshot), encoding="utf-8")
            print(json.dumps(snapshot["summary"], ensure_ascii=False, indent=2))
    except (OSError, json.JSONDecodeError, ProviderError, SchemaError, ValueError) as exc:
        parser.error(str(exc))


def _validate(role_pack_path: str) -> None:
    role_pack = load_role_pack(role_pack_path)
    print(
        json.dumps(
            {
                "status": "valid",
                "role_pack": role_pack.id,
                "version": role_pack.version,
                "roles": len(role_pack.roles),
                "scenarios": len(role_pack.scenarios),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _prepare_judging(role_pack_path: str, conversation_path: str, output_path: str) -> None:
    role_pack = load_role_pack(role_pack_path)
    conversation = _load_conversation(conversation_path)
    role = role_pack.roles.get(conversation.role_id)
    scenario = role_pack.scenarios.get(conversation.scenario_id)
    if role is None or scenario is None:
        raise SchemaError("Conversation role or scenario is not present in the role pack")
    resolve_conversation(role_pack, conversation)
    requests = [
        build_judge_request(role, scenario, conversation, turn.index).to_dict()
        for turn in conversation.turns
    ]
    _write_jsonl(output_path, requests)


def _score(
    role_pack_path: str,
    conversation_path: str,
    judgments_path: str | None,
    output_path: str,
    minimum_judges: int = 2,
) -> None:
    role_pack = load_role_pack(role_pack_path)
    conversation = _load_conversation(conversation_path)
    if conversation.role_id not in role_pack.roles:
        raise SchemaError(f"Unknown conversation role: {conversation.role_id}")
    role = role_pack.roles[conversation.role_id]
    judgments: List[JudgeEvaluation] = []
    if judgments_path:
        for value in _read_jsonl(judgments_path):
            judgments.append(JudgeEvaluation.from_dict(value, role))
    report = score_conversation(
        role_pack,
        conversation,
        judgments,
        minimum_judges=minimum_judges,
    )
    _write_json(output_path, report)


def _load_conversation(path: str) -> Conversation:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SchemaError("Conversation JSON root must be an object")
    return Conversation.from_dict(value)


def _read_jsonl(path: str) -> Iterable[dict[str, Any]]:
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise SchemaError(f"JSONL line {line_number} must be an object")
        yield value


def _write_json(path: str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: str, values: Iterable[Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
