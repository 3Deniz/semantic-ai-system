from fastapi import APIRouter, Query
import api.dependencies as deps

router = APIRouter(tags=["root"])


@router.get("/")
def root():
    return {"status": "semantic engine running"}


@router.get("/metrics")
def metrics():
    with deps._loop_artifact_lock:
        recent = list(deps._loop_artifacts)[-20:]
    thought_ok = sum(1 for r in recent if r.get("thought_generated"))
    visual_ok = sum(1 for r in recent if r.get("visualization_generated"))
    return {
        "nodes": len(deps.main.Q),
        "edges": len(deps.main.policy_counter),
        "inference": deps.get_inference_rate(),
        "cycles": deps.get_cycles(),
        "conflicts": deps.calculate_conflicts(),
        "jepa_trained": deps._jepa.is_trained,
        "jepa_samples": deps._jepa._trained_samples,
        "kg_edges": len(deps._kg.triples),
        "loop_thought_ok_20": thought_ok,
        "loop_visual_ok_20": visual_ok,
    }


@router.get("/loop/health")
def loop_health(limit: int = Query(default=20, ge=1, le=200)):
    with deps._loop_artifact_lock:
        reports = list(deps._loop_artifacts)[-limit:]
    thought_ok = sum(1 for item in reports if item.get("thought_generated"))
    visual_ok = sum(1 for item in reports if item.get("visualization_generated"))
    return {
        "count": len(reports),
        "thought_ok": thought_ok,
        "visualization_ok": visual_ok,
        "latest": reports[-1] if reports else None,
        "reports": reports,
    }
