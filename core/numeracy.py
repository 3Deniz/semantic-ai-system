from __future__ import annotations

import re
from typing import Any


DIGITS = {str(i) for i in range(10)}
CORE_SYMBOLS = {"+", "-", "*", "/", "(", ")"}
CURRICULUM_PHASES = ("letters", "digits", "operations", "real_numbers", "calculus", "logarithms")


def _kg_objects_for_relation(kg: Any, relation: str, subjects: set[str] | None = None) -> set[str]:
    values: set[str] = set()
    if kg is None:
        return values
    subject_filter = subjects or {"numeracy"}
    for s, r, o, _c in getattr(kg, "triples", []):
        if str(s).lower() in subject_filter and str(r).lower() == relation:
            values.add(str(o))
    return values


def get_numeracy_snapshot(kg: Any) -> dict[str, set[str]]:
    return {
        "digits": _kg_objects_for_relation(kg, "knows_digit", {"numeracy"}),
        "symbols": _kg_objects_for_relation(kg, "knows_symbol", {"numeracy"}),
        "concepts": _kg_objects_for_relation(kg, "knows_concept", {"numeracy"}),
    }


def get_completed_phases(kg: Any) -> set[str]:
    return _kg_objects_for_relation(kg, "completed_phase", {"curriculum"})


def missing_prerequisite_phases(completed: set[str], target_phase: str) -> list[str]:
    if target_phase not in CURRICULUM_PHASES:
        return []
    idx = CURRICULUM_PHASES.index(target_phase)
    required = CURRICULUM_PHASES[:idx]
    return [phase for phase in required if phase not in completed]


def required_numeric_tokens(expression: str) -> dict[str, set[str]]:
    expr = expression or ""
    required_digits = set(ch for ch in expr if ch.isdigit())
    required_symbols = set(ch for ch in expr if ch in CORE_SYMBOLS)
    if "." in expr:
        required_symbols.add(".")
    if "/" in expr:
        required_symbols.add("/")
    return {
        "digits": required_digits,
        "symbols": required_symbols,
        "concepts": {"number"},
    }


def can_compute_expression(kg: Any, expression: str) -> tuple[bool, list[str]]:
    snapshot = get_numeracy_snapshot(kg)
    required = required_numeric_tokens(expression)

    missing_digits = sorted(required["digits"] - snapshot["digits"])
    missing_symbols = sorted(required["symbols"] - snapshot["symbols"])
    missing_concepts = sorted(required["concepts"] - snapshot["concepts"])

    missing: list[str] = []
    if missing_digits:
        missing.extend([f"digit:{d}" for d in missing_digits])
    if missing_symbols:
        missing.extend([f"symbol:{s}" for s in missing_symbols])
    if missing_concepts:
        missing.extend([f"concept:{c}" for c in missing_concepts])

    return len(missing) == 0, missing


def required_phases_for_arithmetic(expression: str) -> list[str]:
    phases = ["letters", "digits", "operations"]
    flags = detect_decimal_or_fraction(expression)
    if flags["has_decimal"] or flags["has_fraction"]:
        phases.append("real_numbers")
    return phases


def required_phases_for_calculus() -> list[str]:
    return ["letters", "digits", "operations", "real_numbers", "calculus"]


def required_phases_for_logarithms() -> list[str]:
    return ["letters", "digits", "operations", "real_numbers", "calculus", "logarithms"]


def missing_curriculum_phases(kg: Any, required_phases: list[str]) -> list[str]:
    completed = get_completed_phases(kg)
    return [phase for phase in required_phases if phase not in completed]


def basic_numeracy_facts() -> list[dict]:
    facts: list[dict] = []
    for d in sorted(DIGITS):
        facts.append({
            "subject": "numeracy",
            "relation": "knows_digit",
            "object": d,
            "confidence": 1.0,
            "source_type": "curriculum",
            "source_document": "numeracy_basic",
        })
    for s in sorted(CORE_SYMBOLS | {"."}):
        facts.append({
            "subject": "numeracy",
            "relation": "knows_symbol",
            "object": s,
            "confidence": 1.0,
            "source_type": "curriculum",
            "source_document": "numeracy_basic",
        })
    for concept in ("number", "integer", "decimal", "fraction", "real"):
        facts.append({
            "subject": "numeracy",
            "relation": "knows_concept",
            "object": concept,
            "confidence": 1.0,
            "source_type": "curriculum",
            "source_document": "numeracy_basic",
        })
    return facts


def curriculum_phase_facts(phase: str) -> list[dict]:
    if phase not in CURRICULUM_PHASES:
        return []

    facts: list[dict] = [{
        "subject": "curriculum",
        "relation": "completed_phase",
        "object": phase,
        "confidence": 1.0,
        "source_type": "curriculum",
        "source_document": "math_foundation_curriculum",
    }]

    if phase == "letters":
        for ch in "abcdefghijklmnopqrstuvwxyz":
            facts.append({
                "subject": "numeracy",
                "relation": "knows_letter",
                "object": ch,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "math_foundation_curriculum",
            })

    if phase == "digits":
        for d in sorted(DIGITS):
            facts.append({
                "subject": "numeracy",
                "relation": "knows_digit",
                "object": d,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "math_foundation_curriculum",
            })
        facts.append({
            "subject": "numeracy",
            "relation": "knows_concept",
            "object": "number",
            "confidence": 1.0,
            "source_type": "curriculum",
            "source_document": "math_foundation_curriculum",
        })

    if phase == "operations":
        for s in sorted(CORE_SYMBOLS):
            facts.append({
                "subject": "numeracy",
                "relation": "knows_symbol",
                "object": s,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "math_foundation_curriculum",
            })
        for concept in ("integer", "operation", "addition", "subtraction", "multiplication", "division"):
            facts.append({
                "subject": "numeracy",
                "relation": "knows_concept",
                "object": concept,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "math_foundation_curriculum",
            })

    if phase == "real_numbers":
        for s in (".", "/"):
            facts.append({
                "subject": "numeracy",
                "relation": "knows_symbol",
                "object": s,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "math_foundation_curriculum",
            })
        for concept in ("decimal", "fraction", "real"):
            facts.append({
                "subject": "numeracy",
                "relation": "knows_concept",
                "object": concept,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "math_foundation_curriculum",
            })

    if phase == "calculus":
        for concept in ("derivative", "integral", "limit", "function"):
            facts.append({
                "subject": "numeracy",
                "relation": "knows_concept",
                "object": concept,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "math_foundation_curriculum",
            })

    if phase == "logarithms":
        for concept in ("logarithm", "log", "ln", "base", "change_of_base", "exponent", "inverse_function"):
            facts.append({
                "subject": "numeracy",
                "relation": "knows_concept",
                "object": concept,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "math_foundation_curriculum",
            })

    return facts


def detect_decimal_or_fraction(text: str) -> dict[str, bool]:
    q = text or ""
    return {
        "has_decimal": bool(re.search(r"\d+\.\d+", q)),
        "has_fraction": bool(re.search(r"\d+\s*/\s*\d+", q)),
    }
