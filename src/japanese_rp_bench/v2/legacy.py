"""Read and freeze the published Japanese-RP-Bench v1 evaluation artifacts."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Iterable


LEGACY_DIMENSIONS = (
    "Roleplay Adherence",
    "Consistency",
    "Contextual Understanding",
    "Expressiveness",
    "Creativity",
    "Naturalness of Japanese",
    "Enjoyment of the Dialogue",
    "Appropriateness of Turn-Taking",
)

LEGACY_USER_MODEL = "anthropic.claude-3-5-sonnet-20240620-v1:0"
LEGACY_JUDGES = (
    "gpt-4o-2024-08-06",
    "o1-mini-2024-09-12",
    "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "gemini-1.5-pro-002",
)


def build_legacy_snapshot(
    evaluations_dir: str | Path,
    *,
    expected_cases: int = 30,
    expected_judges: int = 4,
) -> dict[str, Any]:
    """Aggregate the checked-in v1 JSONL files without calling any model APIs."""

    root = Path(evaluations_dir)
    paths = sorted(root.glob("*.jsonl"))
    if not paths:
        raise ValueError(f"No legacy evaluation JSONL files found in {root}")

    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_files: dict[str, str] = {}
    digest = hashlib.sha256()

    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        raw = path.read_bytes()
        digest.update(raw)
        for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            _validate_legacy_record(value, path, line_number, expected_judges)
            model = value["target_model_name"]
            by_model[model].append(value)
            source_files[model] = path.name

    models = []
    for model, records in by_model.items():
        if len(records) != expected_cases:
            raise ValueError(
                f"{model} has {len(records)} cases; expected {expected_cases}"
            )
        case_ids = [record["id"] for record in records]
        if len(set(case_ids)) != expected_cases:
            raise ValueError(f"{model} contains duplicate legacy case IDs")
        dimension_scores = {
            dimension: sum(float(record[dimension]) for record in records) / len(records)
            for dimension in LEGACY_DIMENSIONS
        }
        # The published notebook rounds each dimension to three decimals before
        # calculating Overall Average. Preserve that order for exact parity.
        published_dimension_scores = {
            dimension: round(score, 3)
            for dimension, score in dimension_scores.items()
        }
        overall = sum(
            Decimal(str(score)) for score in published_dimension_scores.values()
        ) / Decimal(len(LEGACY_DIMENSIONS))
        published_overall = float(
            overall.quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN)
        )
        models.append(
            {
                "rank": 0,
                "target_model": model,
                "overall_average": published_overall,
                "dimension_scores": published_dimension_scores,
                "cases": len(records),
                "judge_evaluations": sum(
                    len(record["individual_evaluations"]) for record in records
                ),
                "source_file": source_files[model],
            }
        )

    models.sort(key=lambda row: (-row["overall_average"], row["target_model"]))
    for rank, row in enumerate(models, start=1):
        row["rank"] = rank

    return {
        "schema_version": "legacy-snapshot-1.0",
        "track": "legacy-2024-frozen",
        "comparable_to_published_v1": True,
        "description": (
            "Offline reconstruction from the evaluation artifacts committed by the "
            "original Japanese-RP-Bench authors. No conversations were regenerated "
            "and no evaluations were rerun."
        ),
        "protocol": {
            "cases_per_model": expected_cases,
            "assistant_turns_per_case": 10,
            "user_model": LEGACY_USER_MODEL,
            "judge_models": list(LEGACY_JUDGES),
            "judges_per_case": expected_judges,
            "dimensions": list(LEGACY_DIMENSIONS),
            "score_range": [1, 5],
        },
        "source": {
            "directory": str(root),
            "files": len(paths),
            "sha256": digest.hexdigest(),
        },
        "summary": {
            "models": len(models),
            "conversations": sum(row["cases"] for row in models),
            "judge_evaluations": sum(row["judge_evaluations"] for row in models),
        },
        "leaderboard": models,
    }


def legacy_snapshot_markdown(snapshot: dict[str, Any]) -> str:
    """Render a compact, reviewable copy of a legacy snapshot leaderboard."""

    lines = [
        "# Japanese-RP-Bench Legacy 2024 (frozen)",
        "",
        "This table is reconstructed offline from the evaluation artifacts committed "
        "to the original repository. It does not contain newly generated judgments.",
        "",
        "| Rank | Model | Overall | Roleplay | Consistency | Japanese |",
        "|---:|:---|---:|---:|---:|---:|",
    ]
    for row in snapshot["leaderboard"]:
        dimensions = row["dimension_scores"]
        lines.append(
            f"| {row['rank']} | {row['target_model']} | {row['overall_average']:.3f} "
            f"| {dimensions['Roleplay Adherence']:.3f} "
            f"| {dimensions['Consistency']:.3f} "
            f"| {dimensions['Naturalness of Japanese']:.3f} |"
        )
    return "\n".join(lines) + "\n"


def _validate_legacy_record(
    value: Any,
    path: Path,
    line_number: int,
    expected_judges: int,
) -> None:
    label = f"{path}:{line_number}"
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    for key in ("id", "target_model_name", "user_model_name", "conversation_history"):
        if key not in value:
            raise ValueError(f"{label} is missing {key}")
    if value["user_model_name"] != LEGACY_USER_MODEL:
        raise ValueError(f"{label} uses an unexpected user model")
    if len(value["conversation_history"]) != 20:
        raise ValueError(f"{label} does not contain 10 user/assistant turns")
    judges = value.get("judge_model_names")
    evaluations = value.get("individual_evaluations")
    if not isinstance(judges, list) or set(judges) != set(LEGACY_JUDGES):
        raise ValueError(f"{label} uses an unexpected judge ensemble")
    if not isinstance(evaluations, list) or len(evaluations) != expected_judges:
        raise ValueError(f"{label} does not contain {expected_judges} judge evaluations")
    for dimension in LEGACY_DIMENSIONS:
        score = value.get(dimension)
        if not isinstance(score, (int, float)) or not 1 <= score <= 5:
            raise ValueError(f"{label} has an invalid {dimension} score")
