from __future__ import annotations

from typing import Any


PRIMARY_GRADUATION_PROFILE: dict[str, set[str]] = {
    "literacy": {
        "reading_comprehension",
        "writing",
        "grammar",
        "vocabulary",
        "summarization",
    },
    "mathematics": {
        "number",
        "integer",
        "operation",
        "addition",
        "subtraction",
        "multiplication",
        "division",
        "fraction",
        "decimal",
        "real",
        "problem_solving",
        "geometry",
        "measurement",
        "time",
    },
    "science": {
        "matter",
        "energy",
        "force",
        "ecosystem",
        "human_body",
        "experiment",
        "observation",
    },
    "social_studies": {
        "community",
        "culture",
        "history",
        "map",
        "citizenship",
        "rights",
        "responsibility",
    },
    "economy": {
        "scarcity",
        "choice",
        "opportunity_cost",
        "demand",
        "supply",
        "price",
        "market",
        "budget",
    },
    "digital_and_life_skills": {
        "digital_literacy",
        "safe_internet",
        "communication",
        "collaboration",
        "self_regulation",
        "critical_thinking",
    },
}


def _known_concepts(kg: Any) -> set[str]:
    concepts: set[str] = set()
    for _s, r, o, _c in getattr(kg, "triples", []):
        relation = str(r).lower().strip()
        if relation == "knows_concept":
            concepts.add(str(o).lower().strip())
    return concepts


def _status_from_coverage(coverage: float) -> str:
    if coverage >= 0.85:
        return "ready"
    if coverage >= 0.35:
        return "in_progress"
    return "missing"


def _domain_recommendations(domain: str, missing: list[str]) -> list[str]:
    if domain == "mathematics":
        return [
            "Use POST /learn/numeracy/basic, then continue with POST /learn/curriculum/phase/{phase} for ordered math learning.",
            "Ingest math lesson PDFs with metadata {\"curriculum_phase\":\"...\",\"teach_curriculum\":true} to persist training materials.",
        ]
    if domain == "economy":
        return [
            "Teach economy graph phases via POST /learn/curriculum/economy/phase/{phase}.",
            "Ingest economy lesson PDFs with metadata {\"curriculum_track\":\"economy\",\"curriculum_phase\":\"...\",\"teach_curriculum\":true}.",
        ]
    if missing:
        focus = ", ".join(missing[:4])
        return [
            f"Create a small lesson pack focused on: {focus}.",
            "Upload the lesson as PDF or text through ingest endpoints and verify relation coverage in semantic recall.",
        ]
    return ["Keep reinforcing this domain with mixed exercises and periodic recall checks."]


def build_primary_readiness_report(kg: Any) -> dict[str, object]:
    known = _known_concepts(kg)
    domains: list[dict[str, object]] = []
    total_required = 0
    total_hit = 0

    for domain, required in PRIMARY_GRADUATION_PROFILE.items():
        required_set = set(required)
        matched = sorted(required_set & known)
        missing = sorted(required_set - known)
        required_count = len(required_set)
        hit_count = len(matched)
        total_required += required_count
        total_hit += hit_count
        coverage = round(hit_count / max(1, required_count), 3)
        domains.append({
            "domain": domain,
            "status": _status_from_coverage(coverage),
            "coverage": coverage,
            "known_count": hit_count,
            "required_count": required_count,
            "known_concepts": matched,
            "missing_concepts": missing,
            "recommended_next_actions": _domain_recommendations(domain, missing),
        })

    overall = round(total_hit / max(1, total_required), 3)
    prioritized_gaps = sorted(
        domains,
        key=lambda item: (float(item["coverage"]), int(item["required_count"]) * -1),
    )

    return {
        "target": "primary_school_graduation",
        "overall_coverage": overall,
        "overall_status": _status_from_coverage(overall),
        "known_concept_count": len(known),
        "domains": domains,
        "priority_gaps": [
            {
                "domain": item["domain"],
                "coverage": item["coverage"],
                "missing_top": item["missing_concepts"][:5],
            }
            for item in prioritized_gaps[:3]
        ],
    }


def build_primary_weekly_plan(kg: Any, weeks: int = 6) -> dict[str, object]:
    report = build_primary_readiness_report(kg)
    domains = sorted(
        report.get("domains", []),
        key=lambda item: (float(item.get("coverage", 0.0)), -int(item.get("required_count", 0))),
    )
    weeks = max(1, min(int(weeks), 24))
    domain_count = len(domains) or 1

    weekly_plan: list[dict[str, object]] = []
    for idx in range(weeks):
        domain = domains[idx % domain_count] if domains else {
            "domain": "mathematics",
            "missing_concepts": [],
            "recommended_next_actions": [],
            "coverage": 1.0,
        }
        missing = list(domain.get("missing_concepts", []))
        focus_concepts = missing[: min(4, len(missing))] if missing else ["reinforcement", "mixed_practice"]
        domain_name = str(domain.get("domain", "general"))

        training_actions = [
            f"Prepare 1 short lesson text and 1 lesson PDF for {domain_name} covering: {', '.join(focus_concepts)}.",
            "Ingest lesson text via POST /ingest/texts or POST /ingest/documents.",
            "Ingest lesson PDF via POST /ingest/pdf and keep source_document for provenance.",
            "Re-run GET /learn/primary/readiness at end of week and compare coverage delta.",
        ]
        if domain_name == "mathematics":
            training_actions.insert(1, "If needed, unlock prerequisites using POST /learn/numeracy/basic and POST /learn/curriculum/phase/{phase}.")
        if domain_name == "economy":
            training_actions.insert(1, "Advance economy phases with POST /learn/curriculum/economy/phase/{phase} before graph-heavy topics.")

        weekly_plan.append({
            "week": idx + 1,
            "domain": domain_name,
            "focus_concepts": focus_concepts,
            "coverage_before": domain.get("coverage", 0.0),
            "status_before": domain.get("status", "missing"),
            "training_actions": training_actions,
        })

    return {
        "target": report.get("target"),
        "overall_status": report.get("overall_status"),
        "overall_coverage": report.get("overall_coverage"),
        "weeks": weeks,
        "weekly_plan": weekly_plan,
        "notes": [
            "Plan is generated from current readiness gaps and should be refreshed after each training cycle.",
            "Use artifacts/training_pdfs as persistent lesson history for replay.",
        ],
    }


def build_primary_drip_plan(
    kg: Any,
    cycles: int = 12,
    new_concepts_per_cycle: int = 3,
    reinforcement_concepts_per_cycle: int = 2,
) -> dict[str, object]:
    report = build_primary_readiness_report(kg)
    domains = sorted(
        report.get("domains", []),
        key=lambda item: (float(item.get("coverage", 0.0)), -int(item.get("required_count", 0))),
    )
    cycles = max(1, min(int(cycles), 500))
    new_n = max(1, min(int(new_concepts_per_cycle), 8))
    reinforce_n = max(0, min(int(reinforcement_concepts_per_cycle), 8))

    known_global = _known_concepts(kg)
    cycle_plan: list[dict[str, object]] = []
    domain_count = len(domains) or 1

    for idx in range(cycles):
        domain = domains[idx % domain_count] if domains else {
            "domain": "mathematics",
            "missing_concepts": [],
            "known_concepts": [],
            "coverage": 1.0,
            "status": "ready",
        }
        domain_name = str(domain.get("domain", "general"))
        missing = list(domain.get("missing_concepts", []))
        known_domain = list(domain.get("known_concepts", []))

        new_concepts = missing[:new_n]
        reinforcement_pool = known_domain if known_domain else sorted(known_global)
        reinforcement_concepts = reinforcement_pool[:reinforce_n]

        cycle_plan.append({
            "cycle": idx + 1,
            "domain": domain_name,
            "status_before": domain.get("status", "missing"),
            "coverage_before": domain.get("coverage", 0.0),
            "new_concepts": new_concepts,
            "reinforcement_concepts": reinforcement_concepts,
            "actions": [
                "Ingest short text snippets for each new concept.",
                "Ingest one compact PDF lesson for this cycle.",
                "Reinforce known concepts by re-adding concise examples and relations.",
            ],
        })

    return {
        "target": report.get("target"),
        "overall_status": report.get("overall_status"),
        "overall_coverage": report.get("overall_coverage"),
        "cycles": cycles,
        "new_concepts_per_cycle": new_n,
        "reinforcement_concepts_per_cycle": reinforce_n,
        "drip_plan": cycle_plan,
    }