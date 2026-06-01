from fastapi import APIRouter, Query, HTTPException
import api.dependencies as deps

router = APIRouter(tags=["primary"])


@router.get("/learn/primary/readiness")
def get_primary_readiness_status():
    try:
        return deps.build_primary_readiness_report(deps._kg)
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/learn/primary/plan")
def get_primary_weekly_plan(weeks: int = Query(default=6, ge=1, le=24)):
    try:
        return deps.build_primary_weekly_plan(deps._kg, weeks=weeks)
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/learn/primary/drip/plan")
def get_primary_drip_plan(
    cycles: int = Query(default=12, ge=1, le=500),
    new_concepts_per_cycle: int = Query(default=3, ge=1, le=8),
    reinforcement_concepts_per_cycle: int = Query(default=2, ge=0, le=8),
):
    try:
        return deps.build_primary_drip_plan(deps._kg, cycles=cycles, new_concepts_per_cycle=new_concepts_per_cycle, reinforcement_concepts_per_cycle=reinforcement_concepts_per_cycle)
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/learn/primary/abstraction/pending")
def get_primary_abstraction_pending(limit: int = Query(default=100, ge=1, le=5000)):
    try:
        items = deps._list_pending_abstractions(limit=limit)
        return {"count": len(items), "items": items}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.post("/learn/primary/abstraction/resolve")
def resolve_primary_abstraction_pending(
    limit: int = Query(default=25, ge=1, le=5000),
    reinforcement_confidence: float = Query(default=0.95, ge=0.1, le=1.0),
):
    try:
        result = deps._resolve_pending_abstractions(limit=limit, reinforcement_confidence=reinforcement_confidence)
        return {"ok": True, "reinforcement_confidence": float(reinforcement_confidence), **result}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.post("/learn/primary/drip/run")
def run_primary_drip(
    cycles: int = Query(default=12, ge=1, le=500),
    new_concepts_per_cycle: int = Query(default=3, ge=1, le=8),
    reinforcement_concepts_per_cycle: int = Query(default=2, ge=0, le=8),
    exposure_confidence: float = Query(default=0.6, ge=0.1, le=1.0),
    reinforcement_confidence: float = Query(default=0.95, ge=0.1, le=1.0),
    target_coverage: float | None = Query(default=None, ge=0.0, le=1.0),
    max_total_cycles: int | None = Query(default=None, ge=1, le=5000),
):
    try:
        readiness_before = deps.build_primary_readiness_report(deps._kg)
        injected_new = 0
        reinforced = 0
        executed_cycles = []
        stop_reason = "planned_cycles_completed"
        cycle_limit = max_total_cycles if max_total_cycles is not None else cycles
        cycle_limit = max(1, cycle_limit)
        cycle_index = 0
        while cycle_index < cycle_limit:
            current_readiness = deps.build_primary_readiness_report(deps._kg)
            if target_coverage is not None and float(current_readiness.get("overall_coverage", 0.0)) >= float(target_coverage):
                stop_reason = "target_coverage_reached"
                break
            plan = deps.build_primary_drip_plan(deps._kg, cycles=1, new_concepts_per_cycle=new_concepts_per_cycle, reinforcement_concepts_per_cycle=reinforcement_concepts_per_cycle)
            cycle = (plan.get("drip_plan") or [{}])[0]
            domain = str(cycle.get("domain", "general"))
            new_concepts = [str(c) for c in cycle.get("new_concepts", [])]
            reinforcement_concepts = [str(c) for c in cycle.get("reinforcement_concepts", [])]
            cycle_index += 1
            timestamp = deps.time.time()
            for concept in new_concepts:
                fact_meta = {"source_type": "primary_drip", "source_document": f"primary_drip_cycle_{cycle_index}", "timestamp": timestamp, "stage": "validated", "learning_mode": "exposure", "abstraction_pending": True}
                deps._kg.add(domain, "knows_concept", concept, float(exposure_confidence), fact_meta)
                deps._update_concept_space_embeddings_from_fact(domain, "knows_concept", concept, float(exposure_confidence), fact_meta)
                injected_new += 1
            for concept in reinforcement_concepts:
                fact_meta = {"source_type": "primary_drip", "source_document": f"primary_drip_cycle_{cycle_index}", "timestamp": timestamp, "stage": "validated", "learning_mode": "reinforcement", "abstraction_pending": False}
                deps._kg.add(domain, "knows_concept", concept, float(reinforcement_confidence), fact_meta)
                deps._update_concept_space_embeddings_from_fact(domain, "knows_concept", concept, float(reinforcement_confidence), fact_meta)
                reinforced += 1
            executed_cycles.append({"cycle": cycle_index, "domain": domain, "new_concepts": new_concepts, "reinforcement_concepts": reinforcement_concepts})
        if target_coverage is not None and cycle_index >= cycle_limit and stop_reason != "target_coverage_reached":
            stop_reason = "max_total_cycles_reached"
        readiness_after = deps.build_primary_readiness_report(deps._kg)
        delta = round(float(readiness_after.get("overall_coverage", 0.0)) - float(readiness_before.get("overall_coverage", 0.0)), 3)
        return {
            "ok": True, "mode": "continuous_drip",
            "requested": {"cycles": cycles, "new_concepts_per_cycle": new_concepts_per_cycle, "reinforcement_concepts_per_cycle": reinforcement_concepts_per_cycle, "exposure_confidence": exposure_confidence, "reinforcement_confidence": reinforcement_confidence, "target_coverage": target_coverage, "max_total_cycles": max_total_cycles},
            "applied": {"cycles": len(executed_cycles), "new_concepts_ingested": injected_new, "reinforcement_updates": reinforced},
            "target_reached": bool(target_coverage is not None and float(readiness_after.get("overall_coverage", 0.0)) >= float(target_coverage)),
            "stop_reason": stop_reason,
            "coverage": {"before": readiness_before.get("overall_coverage", 0.0), "after": readiness_after.get("overall_coverage", 0.0), "delta": delta},
            "executed_cycles": executed_cycles,
        }
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}
