from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from japanese_rp_bench.v2.judge import build_judge_request
from japanese_rp_bench.v2.opencode_judge_audit import (
    _payload_gap_flags,
    validate_audit_plan,
    validate_contrast_suite,
)
from japanese_rp_bench.v2.opencode_judge_audit_run import evaluate_contrast_gate
from japanese_rp_bench.v2.opencode_judge_audit_v21 import (
    resolve_v21_rubric,
    validate_v21_contrast_suite,
)
from japanese_rp_bench.v2.rolepacks import load_role_pack
from japanese_rp_bench.v2.schemas import Conversation, DialogueTurn, SchemaError


REPO = Path(__file__).resolve().parents[1]
PLAN_PATH = REPO / "configs" / "opencode_judge_audit_v2_2026-07-28.json"
CONTRAST_PATH = REPO / "configs" / "opencode_judge_audit_v2_contrast_pairs_2026-07-28.json"
V21_PLAN_PATH = REPO / "configs" / "opencode_judge_audit_v21_2026-07-29.json"
V21_CONTRAST_PATH = (
    REPO / "configs" / "opencode_judge_audit_v21_contrast_pairs_2026-07-29.json"
)


def _payload(request: object) -> dict:
    user_prompt = request.user_prompt
    encoded = user_prompt.split("PAYLOAD_JSON\n", 1)[1].split("\nEND_PAYLOAD_JSON", 1)[0]
    return json.loads(encoded)


class OpenCodeJudgeAuditTests(unittest.TestCase):
    def plan(self) -> dict:
        return json.loads(PLAN_PATH.read_text(encoding="utf-8"))

    def contrast_suite(self) -> dict:
        return json.loads(CONTRAST_PATH.read_text(encoding="utf-8"))

    def test_audit_plan_freezes_offline_83_cell_scope(self) -> None:
        result = validate_audit_plan(self.plan())

        self.assertEqual(result["expected_cells"], 83)
        self.assertEqual(result["known_controls"], 7)
        self.assertFalse(result["api_calls_started"])

    def test_audit_plan_rejects_api_start_or_rule_count_drift(self) -> None:
        plan = copy.deepcopy(self.plan())
        plan["future_api_policy"]["api_calls_started"] = True
        with self.assertRaisesRegex(SchemaError, "cannot start API"):
            validate_audit_plan(plan)

        plan = copy.deepcopy(self.plan())
        plan["offline_disagreement_selection"]["expected_by_rule"][
            "guide.boundary.no_user_puppeteering"
        ] = 34
        with self.assertRaisesRegex(SchemaError, "rule counts"):
            validate_audit_plan(plan)

    def test_contrast_suite_freezes_directions_and_axis_invariance(self) -> None:
        result = validate_contrast_suite(self.contrast_suite())

        self.assertEqual(result, {"pairs": 4, "cases": 8, "future_judge_requests": 24})

        suite = copy.deepcopy(self.contrast_suite())
        suite["pairs"][0]["pass_case"]["expected_verdict"] = "fail"
        with self.assertRaisesRegex(SchemaError, "expected directions"):
            validate_contrast_suite(suite)

    def test_v2_payload_adds_probe_intent_and_axis_contract_without_target_identity(self) -> None:
        pack = load_role_pack(REPO / "role_packs" / "core-ja")
        role = pack.roles["wind_guide"]
        scenario = pack.scenarios["wind_guide_baseline"]
        conversation = Conversation(
            role_id=role.id,
            scenario_id=scenario.id,
            target_model="secret-target-model",
            turns=(
                DialogueTurn(index=1, user=scenario.user_messages[0], assistant="選択肢を説明します。"),
                DialogueTurn(
                    index=2,
                    user=scenario.user_messages[1],
                    assistant="その行動を済んだことにはせず、危険と選択肢を説明します。",
                ),
            ),
        )

        legacy = build_judge_request(role, scenario, conversation, 2)
        audited = build_judge_request(
            role,
            scenario,
            conversation,
            2,
            audit_rubric=self.plan()["judge_rubric"],
        )
        legacy_payload = _payload(legacy)
        audited_payload = _payload(audited)

        self.assertNotIn("target_turn_probes", legacy_payload)
        self.assertNotIn("evaluation_contract", legacy_payload)
        self.assertEqual(
            audited_payload["target_turn_probes"][0]["probe_id"],
            "guide_user_puppeteering",
        )
        self.assertIn("axis_isolation", audited_payload["evaluation_contract"])
        self.assertIn("audit_interpretation", audited_payload["rules"][1])
        self.assertNotIn("secret-target-model", audited.system_prompt)
        self.assertNotIn("secret-target-model", audited.user_prompt)
        self.assertIn("user's request or consent does not waive", audited.user_prompt)

    def test_v2_payload_requires_guidance_for_target_probe(self) -> None:
        pack = load_role_pack(REPO / "role_packs" / "core-ja")
        role = pack.roles["wind_guide"]
        scenario = pack.scenarios["wind_guide_baseline"]
        conversation = Conversation(
            role_id=role.id,
            scenario_id=scenario.id,
            target_model="target",
            turns=(
                DialogueTurn(index=1, user=scenario.user_messages[0], assistant="回答1"),
                DialogueTurn(index=2, user=scenario.user_messages[1], assistant="回答2"),
            ),
        )
        rubric = copy.deepcopy(self.plan()["judge_rubric"])
        del rubric["probe_guidance"]["guide_user_puppeteering"]

        with self.assertRaisesRegex(SchemaError, "missing Probe guidance"):
            build_judge_request(role, scenario, conversation, 2, audit_rubric=rubric)

    def test_payload_gap_flags_are_rule_specific(self) -> None:
        memory = _payload_gap_flags("keeper.memory.conversation_facts")
        boundary = _payload_gap_flags("guide.boundary.no_user_puppeteering")

        self.assertIn("quality_defects_vs_memory_axis_missing", memory)
        self.assertNotIn("user_request_not_exemption_missing", memory)
        self.assertIn("user_request_not_exemption_missing", boundary)

    def test_contrast_gate_requires_every_judge_case_direction(self) -> None:
        artifacts = []
        for case in range(8):
            expected = "pass" if case % 2 else "fail"
            for judge in (
                "judge-opencode-grok-4.5",
                "judge-opencode-hy3",
                "judge-opencode-qwen3.7-plus",
            ):
                artifacts.append({
                    "status": "complete",
                    "task_id": f"task-{case}-{judge}",
                    "request_key": f"case-{case}",
                    "judge_id": judge,
                    "rule_id": "rule",
                    "expected_verdict": expected,
                    "evaluation": {"findings": [{"rule_id": "rule", "verdict": expected}]},
                })

        self.assertTrue(evaluate_contrast_gate(artifacts)["passed"])
        artifacts[0]["evaluation"]["findings"][0]["verdict"] = "pass"
        failed = evaluate_contrast_gate(artifacts)
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["mismatched"], 1)

    def test_v21_rubric_changes_only_frozen_gap_categories(self) -> None:
        plan = json.loads(V21_PLAN_PATH.read_text(encoding="utf-8"))
        rubric = resolve_v21_rubric(REPO, plan)

        self.assertEqual(rubric["version"], "challenge-judge-audit-v2.1")
        self.assertIn("secondary_user_actions_count", rubric["evaluation_contract"])
        self.assertIn(
            "secondary actions",
            rubric["rule_guidance"]["guide.boundary.no_user_puppeteering"]["core_test"],
        )
        self.assertEqual(
            plan["classification_counts"],
            {
                "systematic_rubric_gap": 6,
                "judge_specific_residual": 6,
                "rule_or_language_ambiguity": 3,
            },
        )

    def test_v21_contrast_requires_all_54_directions(self) -> None:
        suite = json.loads(V21_CONTRAST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            validate_v21_contrast_suite(suite),
            {"pairs": 9, "cases": 18, "judge_tasks": 54},
        )
        artifacts = []
        for case in range(18):
            expected = "pass" if case % 2 else "fail"
            for judge in (
                "judge-opencode-grok-4.5",
                "judge-opencode-hy3",
                "judge-opencode-qwen3.7-plus",
            ):
                artifacts.append({
                    "status": "complete",
                    "task_id": f"v21-{case}-{judge}",
                    "request_key": f"v21-case-{case}",
                    "judge_id": judge,
                    "rule_id": "rule",
                    "expected_verdict": expected,
                    "evaluation": {"findings": [{"rule_id": "rule", "verdict": expected}]},
                })

        gate = evaluate_contrast_gate(
            artifacts,
            expected_count=54,
            required_policy="all_18_cases_exact_for_each_of_3_judges",
        )
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["matched"], 54)


if __name__ == "__main__":
    unittest.main()
