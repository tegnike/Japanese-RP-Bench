from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from japanese_rp_bench.v2.opencode_calibration import (
    _cohens_kappa,
    _rankdata,
    _spearman,
    validate_plan,
)
from japanese_rp_bench.v2.providers import ModelSpec
from japanese_rp_bench.v2.runner import _uses_anthropic_judge_schema
from japanese_rp_bench.v2.schemas import SchemaError
from japanese_rp_bench.v2.schemas import Conversation, DialogueTurn


REPO = Path(__file__).resolve().parents[1]
PLAN_PATH = REPO / "configs" / "opencode_judge_calibration_2026-07-27.json"
ANALYSIS_PLAN_PATH = REPO / "configs" / "opencode_judge_calibration_analysis_2026-07-27.json"


class OpenCodeCalibrationPlanTests(unittest.TestCase):
    def plan(self) -> dict:
        return json.loads(PLAN_PATH.read_text(encoding="utf-8"))

    def test_preregistered_plan_has_the_exact_fixed_scope(self) -> None:
        result = validate_plan(self.plan())

        self.assertEqual(result["calibration_targets"], 9)
        self.assertEqual(result["holdout_targets"], 6)
        self.assertEqual(result["candidates"], 5)
        self.assertEqual(result["expected_judge_outputs"], 2976)

    def test_analysis_clarification_keeps_the_original_plan_hash_frozen(self) -> None:
        analysis_plan = json.loads(ANALYSIS_PLAN_PATH.read_text(encoding="utf-8"))
        actual = hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest()

        self.assertEqual(analysis_plan["parent_preregistered_plan"]["sha256"], actual)
        self.assertFalse(analysis_plan["changes_to_registered_thresholds"])

    def test_reasoning_request_cannot_drift_from_provider_mapping(self) -> None:
        plan = copy.deepcopy(self.plan())
        qwen = next(item for item in plan["judge_candidates"] if item["model"] == "qwen3.7-plus")
        qwen["reasoning_request"] = {"thinking": {"type": "disabled"}}

        with self.assertRaisesRegex(SchemaError, "Reasoning request mismatch"):
            validate_plan(plan)

    def test_target_model_cannot_be_used_as_same_id_judge(self) -> None:
        plan = copy.deepcopy(self.plan())
        plan["judge_candidates"][0]["model"] = "qwen3.7-max"

        with self.assertRaisesRegex(SchemaError, "duplicates a target model ID"):
            validate_plan(plan)

    def test_opencode_anthropic_compatible_judge_uses_fixed_schema(self) -> None:
        spec = ModelSpec(
            id="judge-opencode-qwen3.7-plus",
            provider="opencode_go",
            model="qwen3.7-plus",
            api_key_env="OPENCODE_GO_API_KEY",
            reasoning="low",
            input_price_per_million=0.4,
            output_price_per_million=1.6,
            api_style="anthropic_messages",
        )

        self.assertTrue(_uses_anthropic_judge_schema(spec))

    def test_calibration_rank_and_spearman_handle_ties(self) -> None:
        self.assertEqual(_rankdata([10.0, 20.0, 20.0, 40.0]), [1.0, 2.5, 2.5, 4.0])
        self.assertAlmostEqual(_spearman([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]), 1.0)
        self.assertAlmostEqual(_spearman([1.0, 2.0, 3.0], [30.0, 20.0, 10.0]), -1.0)

    def test_major_agreement_reports_kappa_and_both_specific_agreements(self) -> None:
        result = _cohens_kappa(
            [True, True, False, False],
            [True, False, True, False],
        )

        self.assertEqual(result["confusion"], {
            "true_positive": 1,
            "true_negative": 1,
            "false_positive": 1,
            "false_negative": 1,
        })
        self.assertEqual(result["cohens_kappa"], 0.0)
        self.assertEqual(result["positive_agreement"], 0.5)
        self.assertEqual(result["negative_agreement"], 0.5)

    def test_conversation_serialization_used_by_ensemble_reports_exists(self) -> None:
        conversation = Conversation(
            role_id="role",
            scenario_id="scenario",
            target_model="target",
            turns=(DialogueTurn(index=1, user="user", assistant="assistant"),),
        )

        self.assertEqual(conversation.to_dict()["turns"][0]["assistant"], "assistant")


if __name__ == "__main__":
    unittest.main()
