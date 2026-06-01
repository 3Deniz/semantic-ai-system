from fastapi import APIRouter, Query, HTTPException, status
import api.dependencies as deps
from api.models.requests import MathRequest

router = APIRouter(tags=["curriculum"])


@router.get("/curriculum/status")
def curriculum_status():
    try:
        concepts = deps._concept_learner.learn()
        concept_count = len(concepts)
        return deps._curriculum.get_status_report(concept_count)
    except Exception:
        deps.logger.exception("Curriculum status request failed")
        return {"error": "Internal server error"}


@router.post("/curriculum/reset")
def curriculum_reset():
    try:
        deps._curriculum.reset()
        return {"ok": True, "curriculum": deps._curriculum.get_status_report(0)}
    except Exception:
        deps.logger.exception("Curriculum reset request failed")
        return {"error": "Internal server error"}


@router.post("/math/calculate")
def math_calculate(req: MathRequest):
    try:
        deps._curriculum.check_prerequisite("arithmetic")
    except deps.PrerequisiteNotMetError as exc:
        raise deps.HTTPException(status_code=deps.status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    try:
        op = req.operation.strip().lower()
        if op == "add":
            result = req.a + req.b
        elif op == "subtract":
            result = req.a - req.b
        elif op == "multiply":
            result = req.a * req.b
        elif op == "divide":
            if req.b == 0:
                raise deps.HTTPException(status_code=deps.status.HTTP_400_BAD_REQUEST, detail="Division by zero.")
            result = req.a / req.b
        else:
            raise deps.HTTPException(status_code=deps.status.HTTP_400_BAD_REQUEST, detail=f"Unknown operation '{op}'. Supported: add, subtract, multiply, divide.")
        return {"operation": op, "a": req.a, "b": req.b, "result": result}
    except deps.HTTPException:
        raise
    except Exception:
        deps.logger.exception("Math calculate request failed")
        return {"error": "Internal server error"}


@router.post("/learn/process")
def learn_process():
    try:
        concepts = deps._concept_learner.learn()
        concept_count = len(concepts)
        recent_errors = list(deps._jepa_recent_errors)
        result = deps._curriculum.evaluate_progression(concept_count, recent_errors)
        return {
            "concept_count": concept_count,
            "avg_jepa_error": round(result["avg_jepa_error"], 6) if result["avg_jepa_error"] is not None else None,
            "stage_advanced": result["advanced"],
            "blocked": result["blocked"],
            "reason": result["reason"],
            "curriculum": deps._curriculum.get_status_report(concept_count),
        }
    except Exception:
        deps.logger.exception("Learn process request failed")
        return {"error": "Internal server error"}


@router.post("/learn/abstraction/trigger")
def learn_abstraction_trigger():
    try:
        concepts = deps._concept_learner.learn()
        rules = deps._rule_learner.learn_rules()
        promoted = 0
        promoted_items = []
        for c in concepts:
            if c.get("abstraction_level", 0) >= 0.6:
                pattern = c["pattern"]
                fact_meta = {
                    "source_type": "abstraction_promotion",
                    "source_document": "abstraction_trigger",
                    "timestamp": deps.time.time(), "stage": "validated",
                    "teaching_kind": "rule", "abstraction_pending": False,
                }
                deps._kg.add("curriculum", "knows_abstract_concept", pattern, min(1.0, c["abstraction_level"]), fact_meta)
                deps._update_concept_space_embeddings_from_fact("curriculum", "knows_abstract_concept", pattern, min(1.0, c["abstraction_level"]), fact_meta)
                promoted += 1
                promoted_items.append({"pattern": pattern, "abstraction_level": c["abstraction_level"]})
        return {"promoted": promoted, "promoted_items": promoted_items, "concept_count": len(concepts), "rule_count": len(rules)}
    except Exception:
        deps.logger.exception("Abstraction trigger failed")
        return {"error": "Internal server error"}


@router.post("/learn/numeracy/basic")
def learn_numeracy_basic(debug: bool = Query(default=False)):
    try:
        completed_before = sorted(deps.get_completed_phases(deps._kg))
        injected = 0
        debug_facts = []
        for phase in ("letters", "digits", "operations", "real_numbers"):
            phase_facts = deps.curriculum_phase_facts(phase)
            injected += deps._inject_curriculum_phase(phase, source_document="math_foundation_curriculum")
            if debug:
                debug_facts.extend(phase_facts)
        for fact in deps.basic_numeracy_facts():
            try:
                deps._kg.add(fact["subject"], fact["relation"], fact["object"], float(fact.get("confidence", 1.0)), {
                    "source_type": fact.get("source_type", "curriculum"),
                    "source_document": fact.get("source_document", "numeracy_basic"),
                    "timestamp": deps.time.time(), "stage": "validated",
                })
                injected += 1
                if debug:
                    debug_facts.append(fact)
            except Exception:
                continue
        completed = sorted(deps.get_completed_phases(deps._kg))
        response = {"ok": True, "taught": injected, "scope": ["digits", "symbols", "integer", "decimal", "fraction", "real"], "completed_phases": completed}
        if debug:
            response["debug"] = deps._curriculum_debug_payload(phase="basic", facts=debug_facts, completed_before=completed_before, completed_after=completed, extra={"mode": "numeracy_basic"})
        return response
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.post("/learn/curriculum/phase/{phase}")
def learn_curriculum_phase(phase: str, debug: bool = Query(default=False)):
    try:
        phase = str(phase).strip().lower()
        if phase not in deps.CURRICULUM_PHASES:
            raise deps.HTTPException(status_code=400, detail=f"Unknown phase: {phase}")
        completed = deps.get_completed_phases(deps._kg)
        missing_prev = deps.missing_prerequisite_phases(completed, phase)
        if missing_prev:
            raise deps.HTTPException(status_code=409, detail={"error": "Prerequisite phases missing", "missing": missing_prev})
        completed_before = sorted(deps.get_completed_phases(deps._kg))
        phase_facts = deps.curriculum_phase_facts(phase)
        injected = deps._inject_curriculum_phase(phase, source_document="math_foundation_curriculum")
        completed_after = sorted(deps.get_completed_phases(deps._kg))
        response = {"ok": True, "phase": phase, "taught": injected, "completed_phases": completed_after}
        if debug:
            response["debug"] = deps._curriculum_debug_payload(phase=phase, facts=phase_facts, completed_before=completed_before, completed_after=completed_after, extra={"mode": "curriculum_phase"})
        return response
    except deps.HTTPException:
        raise
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/learn/bootstrap/plan")
def get_learning_bootstrap_plan():
    try:
        return {"model": "concept_tensor", "notes": [
            "A concept is the weighted composition of its representations across spaces.",
            "Not every concept must exist in every space.",
            "Higher-level spaces should be enabled only after prerequisite spaces stabilize.",
        ], "stages": deps.SPACE_BOOTSTRAP_PLAN, "active_defaults": list(deps.DEFAULT_SPACES)}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.post("/learn/reset")
def reset_learning_state(confirm: bool = Query(default=False), mode: str = Query(default="soft", pattern="^(soft|hard|full)$"), include_archives: bool = Query(default=False)):
    try:
        if not confirm:
            raise deps.HTTPException(status_code=400, detail="Pass confirm=true to reset learning state.")
        result = deps._reset_learning_state(include_archives=include_archives, mode=mode)
        return {"ok": True, "mode": mode, "reset": result}
    except deps.HTTPException:
        raise
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/learn/curriculum/status")
def get_curriculum_status():
    try:
        completed = sorted(deps.get_completed_phases(deps._kg))
        missing = [phase for phase in deps.CURRICULUM_PHASES if phase not in completed]
        snapshot = deps.get_numeracy_snapshot(deps._kg)
        phase_metrics = deps._build_curriculum_phase_metrics()
        return {
            "curriculum": {
                "completed": completed, "missing": missing,
                "total_phases": len(deps.CURRICULUM_PHASES),
                "progress": round(len(completed) / max(1, len(deps.CURRICULUM_PHASES)), 3),
                "phase_metrics": phase_metrics,
            },
            "numeracy": {
                "known_digits": sorted(snapshot.get("digits", set())),
                "known_symbols": sorted(snapshot.get("symbols", set())),
                "known_concepts": sorted(snapshot.get("concepts", set())),
            },
        }
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}
