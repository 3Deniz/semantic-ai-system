from __future__ import annotations

from typing import Any


ECONOMY_CURRICULUM_PHASES = (
    "foundations",
    "demand_supply",
    "elasticity",
    "cost_revenue_profit",
    "market_structures",
    "macro_graphs",
    "policy_shocks",
)


def _kg_objects_for_relation(kg: Any, relation: str, subjects: set[str] | None = None) -> set[str]:
    values: set[str] = set()
    if kg is None:
        return values
    subject_filter = subjects or {"economy_curriculum"}
    for s, r, o, _c in getattr(kg, "triples", []):
        if str(s).lower() in subject_filter and str(r).lower() == relation:
            values.add(str(o))
    return values


def get_completed_economy_phases(kg: Any) -> set[str]:
    return _kg_objects_for_relation(kg, "completed_economy_phase", {"economy_curriculum"})


def missing_economy_prerequisite_phases(completed: set[str], target_phase: str) -> list[str]:
    if target_phase not in ECONOMY_CURRICULUM_PHASES:
        return []
    idx = ECONOMY_CURRICULUM_PHASES.index(target_phase)
    required = ECONOMY_CURRICULUM_PHASES[:idx]
    return [phase for phase in required if phase not in completed]


def economy_curriculum_phase_facts(phase: str) -> list[dict]:
    if phase not in ECONOMY_CURRICULUM_PHASES:
        return []

    facts: list[dict] = [{
        "subject": "economy_curriculum",
        "relation": "completed_economy_phase",
        "object": phase,
        "confidence": 1.0,
        "source_type": "curriculum",
        "source_document": "economy_graph_curriculum",
    }]

    if phase == "foundations":
        facts.extend([
            {
                "subject": "economics",
                "relation": "knows_concept",
                "object": concept,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "economy_graph_curriculum",
            }
            for concept in ("scarcity", "choice", "opportunity_cost", "incentives", "ceteris_paribus", "equilibrium")
        ])

    if phase == "demand_supply":
        facts.extend([
            {
                "subject": "economics",
                "relation": "knows_concept",
                "object": concept,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "economy_graph_curriculum",
            }
            for concept in ("demand", "supply", "price", "quantity", "market", "shift", "movement")
        ])
        facts.extend([
            {
                "subject": "demand",
                "relation": relation,
                "object": obj,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "economy_graph_curriculum",
            }
            for relation, obj in (
                ("interacts_with", "supply"),
                ("is_measured_by", "price_quantity_graph"),
                ("shifts_when", "income_changes"),
            )
        ])

    if phase == "elasticity":
        facts.extend([
            {
                "subject": "economics",
                "relation": "knows_concept",
                "object": concept,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "economy_graph_curriculum",
            }
            for concept in ("elasticity", "price_elasticity", "income_elasticity", "cross_price_elasticity", "sensitivity")
        ])
        facts.append({
            "subject": "elasticity",
            "relation": "measures",
            "object": "responsiveness_to_price_changes",
            "confidence": 1.0,
            "source_type": "curriculum",
            "source_document": "economy_graph_curriculum",
        })

    if phase == "cost_revenue_profit":
        for concept in ("fixed_cost", "variable_cost", "total_cost", "revenue", "profit", "marginal_cost", "marginal_revenue"):
            facts.append({
                "subject": "economics",
                "relation": "knows_concept",
                "object": concept,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "economy_graph_curriculum",
            })

    if phase == "market_structures":
        for concept in ("perfect_competition", "monopoly", "oligopoly", "monopolistic_competition", "market_power"):
            facts.append({
                "subject": "economics",
                "relation": "knows_concept",
                "object": concept,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "economy_graph_curriculum",
            })

    if phase == "macro_graphs":
        for concept in ("ad_as", "aggregate_demand", "aggregate_supply", "gdp", "inflation", "unemployment", "interest_rate"):
            facts.append({
                "subject": "economics",
                "relation": "knows_concept",
                "object": concept,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "economy_graph_curriculum",
            })

    if phase == "policy_shocks":
        for concept in ("monetary_policy", "fiscal_policy", "tax", "subsidy", "tariff", "regulation", "expectations"):
            facts.append({
                "subject": "economics",
                "relation": "knows_concept",
                "object": concept,
                "confidence": 1.0,
                "source_type": "curriculum",
                "source_document": "economy_graph_curriculum",
            })
        facts.append({
            "subject": "policy",
            "relation": "shifts",
            "object": "demand_or_supply",
            "confidence": 1.0,
            "source_type": "curriculum",
            "source_document": "economy_graph_curriculum",
        })

    return facts


def build_economy_phase_metrics(kg: Any) -> list[dict[str, object]]:
    completed = get_completed_economy_phases(kg)
    snapshot = _kg_objects_for_relation(kg, "knows_concept", {"economics"})
    phase_knowledge = {
        "foundations": len(snapshot & {"scarcity", "choice", "opportunity_cost", "incentives", "ceteris_paribus", "equilibrium"}),
        "demand_supply": len(snapshot & {"demand", "supply", "price", "quantity", "market", "shift", "movement"}),
        "elasticity": len(snapshot & {"elasticity", "price_elasticity", "income_elasticity", "cross_price_elasticity", "sensitivity"}),
        "cost_revenue_profit": len(snapshot & {"fixed_cost", "variable_cost", "total_cost", "revenue", "profit", "marginal_cost", "marginal_revenue"}),
        "market_structures": len(snapshot & {"perfect_competition", "monopoly", "oligopoly", "monopolistic_competition", "market_power"}),
        "macro_graphs": len(snapshot & {"ad_as", "aggregate_demand", "aggregate_supply", "gdp", "inflation", "unemployment", "interest_rate"}),
        "policy_shocks": len(snapshot & {"monetary_policy", "fiscal_policy", "tax", "subsidy", "tariff", "regulation", "expectations"}),
    }

    metrics: list[dict[str, object]] = []
    for phase in ECONOMY_CURRICULUM_PHASES:
        metrics.append({
            "phase": phase,
            "completed": phase in completed,
            "missing_prerequisites": missing_economy_prerequisite_phases(completed, phase),
            "knowledge_count": int(phase_knowledge.get(phase, 0)),
        })
    return metrics


def economy_curriculum_status(kg: Any) -> dict[str, object]:
    completed = sorted(get_completed_economy_phases(kg))
    missing = [phase for phase in ECONOMY_CURRICULUM_PHASES if phase not in completed]
    phase_metrics = build_economy_phase_metrics(kg)
    return {
        "curriculum": {
            "completed": completed,
            "missing": missing,
            "total_phases": len(ECONOMY_CURRICULUM_PHASES),
            "progress": round(len(completed) / max(1, len(ECONOMY_CURRICULUM_PHASES)), 3),
            "phase_metrics": phase_metrics,
        },
        "economy": {
            "known_concepts": sorted(_kg_objects_for_relation(kg, "knows_concept", {"economics"})),
        },
    }