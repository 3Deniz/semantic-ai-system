from fastapi import APIRouter, Query, HTTPException
import api.dependencies as deps

router = APIRouter(tags=["memory"])


@router.get("/memory/episodic")
def memory_episodic(limit: int = Query(default=50, ge=1, le=500)):
    try:
        if deps._thought_loop is None:
            return {"episodes": [], "count": 0}
        episodes = deps._thought_loop.memory.get_episodic_memory(limit=limit)
        return {"episodes": episodes, "count": len(episodes)}
    except Exception:
        deps.logger.exception("Episodic memory request failed")
        return {"error": "Internal server error"}


@router.get("/memory/emotional_trend")
def memory_emotional_trend(n: int = Query(default=10, ge=1, le=200)):
    try:
        if deps._thought_loop is None:
            return {"avg_vector": [0.0] * 5, "timeline": [], "count": 0}
        episodes = deps._thought_loop.memory.get_episodic_memory(limit=n)
        timeline = []
        sum_vec = [0.0] * 5
        valid_count = 0
        for i, ep in enumerate(episodes):
            emotion = ep.get("emotion")
            if emotion and isinstance(emotion, (list, tuple)) and len(emotion) >= 5:
                timeline.append({"episode": i + 1, "fear": emotion[0], "anger": emotion[1], "sadness": emotion[2], "surprise": emotion[3], "calm": emotion[4]})
                for j in range(5):
                    sum_vec[j] += emotion[j]
                valid_count += 1
        avg_vector = [round(v / max(1, valid_count), 4) for v in sum_vec] if valid_count else [0.0] * 5
        return {"avg_vector": avg_vector, "timeline": timeline, "count": valid_count}
    except Exception:
        deps.logger.exception("Emotional trend request failed")
        return {"error": "Internal server error"}
