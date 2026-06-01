from fastapi import APIRouter, Query, HTTPException
import api.dependencies as deps

router = APIRouter(tags=["economy"])


@router.post("/learn/curriculum/economy/phase/{phase}")
def learn_economy_curriculum_phase(phase: str, debug: bool = Query(default=False)):
    try:
        phase = str(phase).strip().lower()
        if phase not in deps.ECONOMY_CURRICULUM_PHASES:
            raise HTTPException(status_code=400, detail=f"Unknown economy curriculum phase: {phase}")
        completed = deps._track_completed_phases("economy")
        missing_prev = deps._track_missing_prerequisite_phases("economy", completed, phase)
        if missing_prev:
            raise HTTPException(status_code=409, detail={"error": "Prerequisite phases missing", "missing": missing_prev})
        completed_before = sorted(deps._track_completed_phases("economy"))
        phase_facts = deps._track_phase_facts("economy", phase)
        injected = deps._inject_track_phase("economy", phase, source_document="economy_graph_curriculum")
        completed_after = sorted(deps._track_completed_phases("economy"))
        response = {"ok": True, "track": "economy", "phase": phase, "taught": injected, "completed_phases": completed_after}
        if debug:
            response["debug"] = deps._curriculum_debug_payload(phase=phase, facts=phase_facts, completed_before=completed_before, completed_after=completed_after, extra={"mode": "curriculum_phase", "track": "economy"}, phase_metrics=deps.build_economy_phase_metrics(deps._kg))
        return response
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/learn/curriculum/economy/status")
def get_economy_curriculum_status():
    try:
        return deps.economy_curriculum_status(deps._kg)
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}
