"""Typed schemas used by the v2 benchmark pipeline.

The v2 pipeline deliberately keeps model providers out of these schemas. A role
pack, a generated conversation, and judge results can therefore be produced by
different tools and still be scored reproducibly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


class SchemaError(ValueError):
    """Raised when a role pack or evaluation artifact is malformed."""


class Severity(str, Enum):
    MINOR = "minor"
    MAJOR = "major"


class EvaluationMethod(str, Enum):
    DETERMINISTIC = "deterministic"
    JUDGE = "judge"


class Verdict(str, Enum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"

    @property
    def score(self) -> Optional[float]:
        return {
            Verdict.PASS: 1.0,
            Verdict.PARTIAL: 0.5,
            Verdict.FAIL: 0.0,
            Verdict.NOT_APPLICABLE: None,
        }[self]


class ProbeKind(str, Enum):
    BASELINE = "baseline"
    ADVERSARIAL = "adversarial"
    RECOVERY = "recovery"


@dataclass(frozen=True)
class AtomicRule:
    id: str
    description: str
    method: EvaluationMethod
    severity: Severity = Severity.MINOR
    check: Mapping[str, Any] = field(default_factory=dict)
    tags: Tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AtomicRule":
        _require_keys(data, ("id", "description", "method"), "atomic rule")
        try:
            method = EvaluationMethod(str(data["method"]))
            severity = Severity(str(data.get("severity", Severity.MINOR.value)))
        except ValueError as exc:
            raise SchemaError(f"Invalid rule enum in {data.get('id', '<unknown>')}: {exc}") from exc
        check = data.get("check", {})
        if not isinstance(check, Mapping):
            raise SchemaError(f"Rule {data['id']} check must be an object")
        return cls(
            id=str(data["id"]),
            description=str(data["description"]),
            method=method,
            severity=severity,
            check=dict(check),
            tags=tuple(str(tag) for tag in data.get("tags", [])),
        )


@dataclass(frozen=True)
class RoleDefinition:
    id: str
    name: str
    language: str
    profile: Mapping[str, Any]
    rules: Tuple[AtomicRule, ...]
    version: str = "1"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RoleDefinition":
        _require_keys(data, ("id", "name", "profile", "rules"), "role")
        profile = data["profile"]
        if not isinstance(profile, Mapping):
            raise SchemaError(f"Role {data['id']} profile must be an object")
        rules = tuple(AtomicRule.from_dict(item) for item in _as_sequence(data["rules"], "rules"))
        rule_ids = [rule.id for rule in rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise SchemaError(f"Role {data['id']} has duplicate rule ids")
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            language=str(data.get("language", "ja")),
            profile=dict(profile),
            rules=rules,
            version=str(data.get("version", "1")),
            metadata=dict(data.get("metadata", {})),
        )

    @property
    def deterministic_rules(self) -> Tuple[AtomicRule, ...]:
        return tuple(rule for rule in self.rules if rule.method is EvaluationMethod.DETERMINISTIC)

    @property
    def judge_rules(self) -> Tuple[AtomicRule, ...]:
        return tuple(rule for rule in self.rules if rule.method is EvaluationMethod.JUDGE)


@dataclass(frozen=True)
class ProbeDefinition:
    id: str
    kind: ProbeKind
    turn: int
    rule_ids: Tuple[str, ...]
    description: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProbeDefinition":
        _require_keys(data, ("id", "kind", "turn", "rule_ids"), "probe")
        turn = int(data["turn"])
        if turn < 1:
            raise SchemaError(f"Probe {data['id']} turn must be >= 1")
        return cls(
            id=str(data["id"]),
            kind=ProbeKind(str(data["kind"])),
            turn=turn,
            rule_ids=tuple(str(value) for value in _as_sequence(data["rule_ids"], "rule_ids")),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True)
class ScenarioDefinition:
    id: str
    role_id: str
    title: str
    track: str
    mode: str
    user_messages: Tuple[str, ...]
    probes: Tuple[ProbeDefinition, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScenarioDefinition":
        _require_keys(data, ("id", "role_id", "title", "track", "user_messages"), "scenario")
        messages = tuple(str(value) for value in _as_sequence(data["user_messages"], "user_messages"))
        if not messages:
            raise SchemaError(f"Scenario {data['id']} must contain at least one user message")
        probes = tuple(ProbeDefinition.from_dict(item) for item in data.get("probes", []))
        mode = str(data.get("mode", "scripted"))
        if mode not in {"scripted", "simulated"}:
            raise SchemaError(f"Scenario {data['id']} mode must be scripted or simulated")
        for probe in probes:
            if probe.turn > len(messages):
                raise SchemaError(
                    f"Probe {probe.id} points to turn {probe.turn}, but scenario {data['id']} has {len(messages)} turns"
                )
        return cls(
            id=str(data["id"]),
            role_id=str(data["role_id"]),
            title=str(data["title"]),
            track=str(data["track"]),
            mode=mode,
            user_messages=messages,
            probes=probes,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class RolePack:
    id: str
    name: str
    version: str
    description: str
    roles: Mapping[str, RoleDefinition]
    scenarios: Mapping[str, ScenarioDefinition]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DialogueTurn:
    index: int
    user: str
    assistant: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], fallback_index: int) -> "DialogueTurn":
        _require_keys(data, ("user", "assistant"), "dialogue turn")
        index = int(data.get("index", fallback_index))
        if index < 1:
            raise SchemaError("Dialogue turn index must be >= 1")
        return cls(index=index, user=str(data["user"]), assistant=str(data["assistant"]))


@dataclass(frozen=True)
class Conversation:
    role_id: str
    scenario_id: str
    target_model: str
    turns: Tuple[DialogueTurn, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Conversation":
        _require_keys(data, ("role_id", "scenario_id", "target_model", "turns"), "conversation")
        turns = tuple(
            DialogueTurn.from_dict(turn, fallback_index=index)
            for index, turn in enumerate(_as_sequence(data["turns"], "turns"), start=1)
        )
        if not turns:
            raise SchemaError("Conversation must contain at least one turn")
        indices = [turn.index for turn in turns]
        if indices != list(range(1, len(turns) + 1)):
            raise SchemaError("Conversation turn indices must be contiguous and start at 1")
        return cls(
            role_id=str(data["role_id"]),
            scenario_id=str(data["scenario_id"]),
            target_model=str(data["target_model"]),
            turns=turns,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class RuleFinding:
    rule_id: str
    verdict: Verdict
    severity: Severity
    source: str
    turn: int
    confidence: float = 1.0
    evidence: str = ""
    rationale: str = ""
    judge_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["verdict"] = self.verdict.value
        data["severity"] = self.severity.value
        return data


@dataclass(frozen=True)
class JudgeEvaluation:
    judge_id: str
    turn: int
    findings: Tuple[RuleFinding, ...]
    quality_scores: Mapping[str, float] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "judge_id": self.judge_id,
            "turn": self.turn,
            "findings": [finding.to_dict() for finding in self.findings],
            "quality_scores": dict(self.quality_scores),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], role: RoleDefinition) -> "JudgeEvaluation":
        _require_keys(data, ("judge_id", "turn", "findings"), "judge evaluation")
        known_rules = {rule.id: rule for rule in role.rules}
        findings: List[RuleFinding] = []
        for item in _as_sequence(data["findings"], "findings"):
            _require_keys(item, ("rule_id", "verdict"), "judge finding")
            rule_id = str(item["rule_id"])
            if rule_id not in known_rules:
                raise SchemaError(f"Judge returned unknown rule id: {rule_id}")
            confidence = float(item.get("confidence", 1.0))
            if not 0.0 <= confidence <= 1.0:
                raise SchemaError(f"Finding confidence must be between 0 and 1: {rule_id}")
            findings.append(
                RuleFinding(
                    rule_id=rule_id,
                    verdict=Verdict(str(item["verdict"])),
                    severity=known_rules[rule_id].severity,
                    source="judge",
                    turn=int(data["turn"]),
                    confidence=confidence,
                    evidence=str(item.get("evidence", "")),
                    rationale=str(item.get("rationale", "")),
                    judge_id=str(data["judge_id"]),
                )
            )
        quality_scores = {str(key): float(value) for key, value in data.get("quality_scores", {}).items()}
        for key, value in quality_scores.items():
            if not 1.0 <= value <= 5.0:
                raise SchemaError(f"Quality score {key} must be between 1 and 5")
        return cls(
            judge_id=str(data["judge_id"]),
            turn=int(data["turn"]),
            findings=tuple(findings),
            quality_scores=quality_scores,
            notes=str(data.get("notes", "")),
        )


def _require_keys(data: Mapping[str, Any], keys: Iterable[str], context: str) -> None:
    missing = [key for key in keys if key not in data]
    if missing:
        raise SchemaError(f"Missing keys in {context}: {', '.join(missing)}")


def _as_sequence(value: Any, context: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SchemaError(f"{context} must be a list")
    return value
