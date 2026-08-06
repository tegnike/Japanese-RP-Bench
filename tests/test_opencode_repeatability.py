from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from japanese_rp_bench.v2.opencode_repeatability import (
    _judgment_artifact_paths,
    build_schedule,
    validate_plan,
)
from japanese_rp_bench.v2.opencode_repeatability_analysis import (
    holm_adjust,
    sample_extension_decision,
)
from japanese_rp_bench.v2.opencode_repeatability_extension import (
    _load_judge_amendment,
    build_schedule as build_extension_schedule,
    validate_plan as validate_extension_plan,
)
from japanese_rp_bench.v2.runner import _apply_registered_job_order, _challenge_judge_rubric
from japanese_rp_bench.v2.schemas import (
    Conversation,
    DialogueTurn,
    RolePack,
    ScenarioDefinition,
    SchemaError,
)
from japanese_rp_bench.v2.providers import ModelSpec


REPO = Path(__file__).resolve().parents[1]
PLAN_PATH = REPO / "configs" / "opencode_challenge_repeatability_2026-07-27.json"
EXTENSION_PLAN_PATH = (
    REPO / "configs" / "opencode_qwen38_repeatability_extension_2026-08-05.json"
)
EXTENSION_AMENDMENT_PATH = (
    REPO / "configs" / "opencode_qwen38_xai_grok_amendment_2026-08-06.json"
)


class OpenCodeChallengeRepeatabilityTests(unittest.TestCase):
    def plan(self) -> dict:
        return json.loads(PLAN_PATH.read_text(encoding="utf-8"))

    def test_preregistered_plan_has_exact_scope_and_counts(self) -> None:
        result = validate_plan(self.plan())

        self.assertEqual(result["targets"], 8)
        self.assertEqual(result["judges"], 3)
        self.assertEqual(result["registered_conversations"], 480)
        self.assertEqual(result["registered_target_responses"], 2160)
        self.assertEqual(result["registered_judge_outputs"], 6480)
        self.assertEqual(result["pairwise_comparisons_per_metric"], 28)

    def test_qwen38_extension_freezes_one_comparable_model(self) -> None:
        plan = json.loads(EXTENSION_PLAN_PATH.read_text(encoding="utf-8"))

        result = validate_extension_plan(REPO, EXTENSION_PLAN_PATH, plan)
        schedule = build_extension_schedule(REPO, plan)

        self.assertEqual(result["target"], "opencode-go-qwen3.8-max")
        self.assertEqual(result["conversations"], 60)
        self.assertEqual(result["target_responses"], 270)
        self.assertEqual(result["judge_outputs"], 810)
        self.assertEqual(result["rubric_version"], "challenge-judge-audit-v2.1")
        self.assertEqual(set(schedule["blocks"]), {f"block-{index:02d}" for index in range(11)})
        self.assertTrue(all(len(jobs) == len(set(jobs)) == 6 for jobs in schedule["blocks"].values()))

    def test_qwen38_xai_amendment_changes_only_grok_execution_route(self) -> None:
        amendment, spec = _load_judge_amendment(
            REPO,
            EXTENSION_AMENDMENT_PATH,
            EXTENSION_PLAN_PATH,
        )

        self.assertEqual(amendment["amendment_id"], "qwen38-direct-xai-grok-20260806-v1")
        self.assertEqual(spec.id, "judge-opencode-grok-4.5")
        self.assertEqual((spec.provider, spec.model, spec.reasoning), ("xai", "grok-4.5", "low"))
        self.assertEqual(spec.api_key_env, "XAI_API_KEY")

    def test_runner_accepts_only_a_versioned_optional_challenge_rubric(self) -> None:
        self.assertIsNone(_challenge_judge_rubric({"evaluation": {}}))
        rubric = {"version": "challenge-judge-audit-v2.1"}
        self.assertEqual(
            _challenge_judge_rubric({"evaluation": {"challenge_judge_rubric": rubric}}),
            rubric,
        )
        with self.assertRaisesRegex(SchemaError, "versioned"):
            _challenge_judge_rubric(
                {"evaluation": {"challenge_judge_rubric": {}}}
            )

    def test_practical_difference_and_all_target_extension_cannot_drift(self) -> None:
        plan = copy.deepcopy(self.plan())
        plan["analysis"]["minimum_practical_difference"]["continuous_score_points"] = 2.0

        with self.assertRaisesRegex(SchemaError, "practical-difference"):
            validate_plan(plan)

        plan = copy.deepcopy(self.plan())
        plan["sample_extension"]["extend_all_targets_and_scenarios_together"] = False
        with self.assertRaisesRegex(SchemaError, "all-target"):
            validate_plan(plan)

        plan = copy.deepcopy(self.plan())
        plan["analysis"]["bootstrap"]["replicates"] = 1000
        with self.assertRaisesRegex(SchemaError, "bootstrap"):
            validate_plan(plan)

        plan = copy.deepcopy(self.plan())
        plan["analysis"]["multiple_comparisons"]["family"] = "selected_pairs"
        with self.assertRaisesRegex(SchemaError, "Holm"):
            validate_plan(plan)

    def test_schedule_is_deterministic_complete_and_precomputed_through_block_20(self) -> None:
        first = build_schedule(REPO, self.plan())
        second = build_schedule(REPO, self.plan())

        self.assertEqual(first, second)
        self.assertEqual(set(first["blocks"]), {f"block-{index:02d}" for index in range(21)})
        for jobs in first["blocks"].values():
            self.assertEqual(len(jobs), 48)
            self.assertEqual(len(set(jobs)), 48)
        self.assertNotEqual(first["blocks"]["block-01"], first["blocks"]["block-02"])

    def test_registered_job_order_requires_every_job_exactly_once(self) -> None:
        scenario_a = ScenarioDefinition(
            id="a", role_id="role", title="A", track="core-ja", mode="scripted",
            user_messages=("a",),
        )
        scenario_b = ScenarioDefinition(
            id="b", role_id="role", title="B", track="core-ja", mode="scripted",
            user_messages=("b",),
        )
        pack = RolePack(
            id="pack", name="Pack", version="1", description="", roles={},
            scenarios={"a": scenario_a, "b": scenario_b},
        )
        target = ModelSpec(
            id="target", provider="opencode_go", api_style="openai_chat", model="target",
            api_key_env="KEY", reasoning="none", input_price_per_million=0,
            output_price_per_million=0,
        )
        jobs = [(pack, scenario_a, target), (pack, scenario_b, target)]
        ordered = _apply_registered_job_order(
            jobs,
            {"execution": {"job_order": ["target|pack|b", "target|pack|a"]}},
        )

        self.assertEqual([job[1].id for job in ordered], ["b", "a"])
        with self.assertRaisesRegex(SchemaError, "every configured job"):
            _apply_registered_job_order(
                jobs,
                {"execution": {"job_order": ["target|pack|a"]}},
            )

    def test_conversation_to_dict_round_trips_for_ensemble_analysis(self) -> None:
        conversation = Conversation(
            role_id="role",
            scenario_id="scenario",
            target_model="target",
            turns=(DialogueTurn(index=1, user="u", assistant="a"),),
            metadata={"fingerprint": "x"},
        )

        self.assertEqual(Conversation.from_dict(conversation.to_dict()), conversation)

    def test_repeatability_audit_separates_raw_judge_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            judgments = run_root / "judgments" / "target"
            judgments.mkdir(parents=True)
            (judgments / "scenario.jsonl").write_text("{}\n", encoding="utf-8")
            (judgments / "scenario.raw-attempts.jsonl").write_text("{}\n", encoding="utf-8")

            final_paths, raw_attempt_paths = _judgment_artifact_paths(run_root)

        self.assertEqual([path.name for path in final_paths], ["scenario.jsonl"])
        self.assertEqual(
            [path.name for path in raw_attempt_paths],
            ["scenario.raw-attempts.jsonl"],
        )

    def test_holm_adjustment_is_monotone_in_sorted_p_value_order(self) -> None:
        adjusted = holm_adjust([0.04, 0.01, 0.03, 0.002])

        self.assertEqual(adjusted, [0.06, 0.03, 0.06, 0.008])

    def test_sample_extension_uses_only_registered_top_set_and_wide_crossing_interval(self) -> None:
        targets = self.plan()["targets"]
        target_ids = [target["id"] for target in targets]
        points = {
            target_id: {
                "challenge_rp_summary": 90.0 - index * 5.0,
                "major_free_rate": 100.0,
                "major_violation_rate": 0.0,
            }
            for index, target_id in enumerate(target_ids)
        }
        points[target_ids[1]]["challenge_rp_summary"] = 88.0
        ranks = {
            "models": {
                target_id: {"rank_probabilities": {"1": 0.5 if index < 2 else 0.0}}
                for index, target_id in enumerate(target_ids)
            }
        }
        comparisons = [
            {
                "metric": "challenge_rp_summary",
                "model_a": target_ids[0],
                "model_b": target_ids[1],
                "confidence_interval_95": [-1.0, 4.5],
            }
        ]

        decision = sample_extension_decision(points, comparisons, ranks)

        self.assertTrue(decision["extend"])
        self.assertEqual(decision["top_decision_set"], sorted(target_ids[:2]))
        self.assertFalse(decision["api_calls_started"])


if __name__ == "__main__":
    unittest.main()
