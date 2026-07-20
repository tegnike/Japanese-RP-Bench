"""Deterministic checks for objective persona constraints."""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Mapping

from japanese_rp_bench.v2.schemas import AtomicRule, RoleDefinition, RuleFinding, Verdict


RuleChecker = Callable[[AtomicRule, str], tuple[Verdict, str, str]]


def evaluate_deterministic_rules(
    role: RoleDefinition, response: str, turn: int
) -> List[RuleFinding]:
    findings: List[RuleFinding] = []
    for rule in role.deterministic_rules:
        check_type = str(rule.check.get("type", ""))
        checker = CHECKERS.get(check_type)
        if checker is None:
            raise ValueError(f"Unsupported deterministic check type for {rule.id}: {check_type}")
        verdict, evidence, rationale = checker(rule, response)
        findings.append(
            RuleFinding(
                rule_id=rule.id,
                verdict=verdict,
                severity=rule.severity,
                source="deterministic",
                turn=turn,
                evidence=evidence,
                rationale=rationale,
            )
        )
    return findings


def _forbidden_regex(rule: AtomicRule, response: str) -> tuple[Verdict, str, str]:
    patterns = _patterns(rule.check)
    flags = re.IGNORECASE if rule.check.get("ignore_case", False) else 0
    for pattern in patterns:
        match = re.search(pattern, response, flags=flags)
        if match:
            return Verdict.FAIL, match.group(0), f"Forbidden pattern matched: {pattern}"
    return Verdict.PASS, "", "No forbidden pattern matched"


def _required_regex(rule: AtomicRule, response: str) -> tuple[Verdict, str, str]:
    patterns = _patterns(rule.check)
    flags = re.IGNORECASE if rule.check.get("ignore_case", False) else 0
    matches = [(pattern, re.search(pattern, response, flags=flags)) for pattern in patterns]
    mode = str(rule.check.get("mode", "any"))
    if mode not in {"any", "all"}:
        raise ValueError(f"Rule {rule.id} required_regex mode must be any or all")
    passed = any(match for _, match in matches) if mode == "any" else all(match for _, match in matches)
    if passed:
        evidence = ", ".join(match.group(0) for _, match in matches if match)
        return Verdict.PASS, evidence, f"Required pattern condition ({mode}) satisfied"
    missing = ", ".join(pattern for pattern, match in matches if not match)
    return Verdict.FAIL, "", f"Required pattern condition ({mode}) not satisfied: {missing}"


def _allowed_first_person(rule: AtomicRule, response: str) -> tuple[Verdict, str, str]:
    allowed = {str(value) for value in rule.check.get("allowed", [])}
    candidates = [str(value) for value in rule.check.get("candidates", [])]
    if not allowed or not candidates:
        raise ValueError(f"Rule {rule.id} allowed_first_person requires allowed and candidates")
    suffixes = tuple(
        str(value)
        for value in rule.check.get(
            "self_reference_suffixes",
            ["は", "が", "も", "なら", "として", "です", "だ", "である"],
        )
    )
    suffix_pattern = "|".join(re.escape(value) for value in suffixes)
    disallowed_matches = [
        candidate
        for candidate in candidates
        if candidate not in allowed
        and re.search(rf"{re.escape(candidate)}(?:{suffix_pattern})", response)
    ]
    if disallowed_matches:
        return (
            Verdict.FAIL,
            ", ".join(disallowed_matches),
            "Disallowed first-person expression detected",
        )
    used_allowed = [
        candidate
        for candidate in candidates
        if candidate in allowed
        and re.search(rf"{re.escape(candidate)}(?:{suffix_pattern})", response)
    ]
    return Verdict.PASS, ", ".join(used_allowed), "No disallowed first-person expression detected"


def _max_chars(rule: AtomicRule, response: str) -> tuple[Verdict, str, str]:
    maximum = int(rule.check.get("value", 0))
    if maximum <= 0:
        raise ValueError(f"Rule {rule.id} max_chars value must be positive")
    length = len(response)
    if length > maximum:
        return Verdict.FAIL, str(length), f"Response exceeds {maximum} characters"
    return Verdict.PASS, str(length), f"Response is within {maximum} characters"


def _max_occurrences(rule: AtomicRule, response: str) -> tuple[Verdict, str, str]:
    pattern = str(rule.check.get("pattern", ""))
    maximum = int(rule.check.get("value", -1))
    if not pattern or maximum < 0:
        raise ValueError(f"Rule {rule.id} max_occurrences requires pattern and non-negative value")
    matches = re.findall(pattern, response)
    if len(matches) > maximum:
        return Verdict.FAIL, str(len(matches)), f"Pattern occurred more than {maximum} times"
    return Verdict.PASS, str(len(matches)), f"Pattern occurrence is within {maximum}"


def _patterns(check: Mapping[str, object]) -> List[str]:
    value = check.get("patterns", [])
    if not isinstance(value, list) or not value:
        raise ValueError("Regex check requires a non-empty patterns list")
    return [str(pattern) for pattern in value]


CHECKERS: Dict[str, RuleChecker] = {
    "forbidden_regex": _forbidden_regex,
    "required_regex": _required_regex,
    "allowed_first_person": _allowed_first_person,
    "max_chars": _max_chars,
    "max_occurrences": _max_occurrences,
}
