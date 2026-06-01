from fastapi import APIRouter, Query, HTTPException
import api.dependencies as deps
from api.models.requests import StateRequest, SimulateRequest

router = APIRouter(tags=["think"])


@router.post("/think")
def think(req: StateRequest):
    try:
        trace = deps._thought_loop.think(set(deps.parse_state(req.state)))
        trace["thought_path"] = deps._build_thought_path(trace)
        return trace
    except Exception:
        deps.logger.exception("Think request failed")
        return {"error": "Internal server error"}


@router.get("/thought_trace")
def thought_trace(n: int = Query(default=5, ge=1, le=20)):
    try:
        return {"traces": deps._thought_loop.get_recent_traces(n)}
    except Exception:
        deps.logger.exception("Thought trace request failed")
        return {"error": "Internal server error"}


@router.post("/decision")
def decision(req: StateRequest):
    try:
        base_scores, best, diagnostics = deps.hybrid_decision(req.state, return_diagnostics=True)
        deps._record_loop_artifacts(req.state, best, base_scores, thought_trace=diagnostics.get("thought_trace"))
        return {"state": req.state, "action": best, "scores": base_scores}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.post("/simulate")
def simulate(req: SimulateRequest):
    try:
        n = min(req.steps or 10, deps.MAX_SIMULATE_STEPS)
        trajectory = []
        current = req.state
        for _ in range(n):
            scores, action, diagnostics = deps.hybrid_decision(current, return_diagnostics=True)
            deps._record_loop_artifacts(current, action, scores, thought_trace=diagnostics.get("thought_trace"))
            reward, next_state = deps.simulate_outcome(current, action)
            trajectory.append({"state": current, "action": action, "reward": round(reward, 3), "next_state": str(next_state)})
            current = str(next_state)
        return {"trajectory": trajectory, "steps": len(trajectory)}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/explain")
def explain(state: str = Query(..., max_length=500, description="State tuple string, e.g. ('flood','damage')")):
    try:
        explanation = []
        s = state.lower()
        if "crisis" in s: explanation.append("High risk crisis detected")
        if "collapse" in s: explanation.append("Structural collapse risk")
        if "flood" in s: explanation.append("Flood risk present")
        if not explanation: explanation.append("Stable state")
        rule_scores = deps.evaluate_actions(state)
        sim_scores, _ = deps.plan_actions(state)
        jepa_scores = deps.evaluate_actions_jepa(state)
        base_scores, best_action, diagnostics = deps.hybrid_decision(state, return_diagnostics=True)
        deps._record_loop_artifacts(state, best_action, base_scores, thought_trace=diagnostics.get("thought_trace"))
        return {
            "state": state, "explanation": explanation, "scores": rule_scores,
            "simulation": sim_scores, "jepa": jepa_scores, "base_scores": base_scores,
            "best_action": best_action, "trap": deps.detect_trap(sim_scores), "risk": deps.calculate_risk(state),
        }
    except Exception:
        deps.logger.exception("Explain request failed")
        return {"error": "Internal server error"}


@router.get("/graph")
def graph():
    try:
        nodes = set()
        edges = []
        for state, actions in deps.main.policy_counter.items():
            s = str(state)
            nodes.add(s)
            for a in actions:
                node = f"{s}:{a}"
                nodes.add(node)
                edges.append({"source": s, "target": node})
        return {"nodes": list(nodes), "edges": edges}
    except Exception:
        print("GRAPH ERROR: ")
        return {"nodes": [], "edges": []}


@router.get("/debug/emotion/jepa")
def debug_emotion_jepa():
    try:
        from cognition.emotion_space import EmotionSpace
        results = []
        test_states = [
            ("clear", set()), ("rain", {"rain"}), ("flood", {"flood"}),
            ("flood,damage", {"flood", "damage"}), ("crisis", {"crisis"}),
        ]
        for label, state in test_states:
            spaces = deps._thought_loop.embedding.embed(state) if deps._thought_loop and hasattr(deps._thought_loop, "embedding") else {}
            risk = sum(spaces.get("risk", [0.0])) / max(1, len(spaces.get("risk", [1.0]))) if spaces else 0.0
            for surprise in [0.0, 0.2, 0.5, 0.8]:
                es2 = EmotionSpace()
                es2.from_state(state)
                es2.update_from_jepa(surprise, risk)
                post_vec = es2.to_vector()
                results.append({"state": label, "surprise": surprise, "risk": round(risk, 4), "emotion": [round(v, 4) for v in post_vec]})
        return {"test_sequence": results, "count": len(results)}
    except Exception:
        deps.logger.exception("Debug emotion/jepa failed")
        return {"error": "Internal server error"}
