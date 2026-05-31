from __future__ import annotations

"""Intent and goal system.

Goals (priority order)
----------------------
1. survival       — avoid crisis/collapse (highest)
2. stability      — reduce ongoing threats
3. risk_reduction — prevent escalation
4. consistency    — maintain known-good patterns
5. task_completion— complete current action plan (lowest)

IntentEngine produces a ranked list of active goals and an intent_vector
that downstream conflict resolution can use.
"""

from cognition.layered_memory import LayeredMemory


class IntentEngine:
    GOAL_ORDER = ["survival", "stability", "risk_reduction", "consistency", "task_completion"]

    def __init__(self, memory: LayeredMemory = None):
        self.memory = memory

    @staticmethod
    def _normalize_state(state: set | list | tuple) -> set[str]:
        return {str(item).lower() for item in state}

    def compute_goals(self, state: set, emotion: list[float] | None = None) -> list[dict]:
        state_set = self._normalize_state(state)
        failure_boost = self.memory.get_failure_score(state_set) if self.memory else 0.0
        has_major = "crisis" in state_set or "collapse" in state_set
        has_mid = "flood" in state_set or "damage" in state_set
        is_clear = not ({"rain", "flood", "damage", "collapse", "crisis"} & state_set)

        scores = {
            "survival": 1.0 if has_major else (0.3 if has_mid else 0.0),
            "stability": 1.0 if has_mid and not has_major else (0.5 if "rain" in state_set else 0.0),
            "risk_reduction": 0.8 if has_mid else (0.3 if "rain" in state_set else 0.0),
            "consistency": 0.8 if is_clear else 0.3,
            "task_completion": 0.5,
        }

        if failure_boost > 0:
            scores["survival"] = min(1.0, scores["survival"] + 0.2 * failure_boost)
            scores["risk_reduction"] = min(1.0, scores["risk_reduction"] + 0.3 * failure_boost)

        if emotion is not None and len(emotion) >= 5:
            fear, anger, _sadness, _surprise, _calm = emotion[:5]
            if fear > 0.5:
                scores["survival"] = min(1.0, scores["survival"] + fear * 0.3)
            if anger > 0.2:
                scores["risk_reduction"] = min(1.0, scores["risk_reduction"] + anger * 0.2)
            if _sadness > 0.3:
                scores["task_completion"] = max(0.0, scores["task_completion"] - _sadness * 0.3)

        reasons = {
            "survival": "crisis/collapse pressure" if has_major else ("threat history raises caution" if has_mid else "no immediate existential threat"),
            "stability": "ongoing damage or flood present" if has_mid and not has_major else ("rain suggests mild instability" if "rain" in state_set else "stable conditions"),
            "risk_reduction": "prevent escalation from active hazard" if has_mid else ("rain could escalate" if "rain" in state_set else "little escalation risk"),
            "consistency": "maintain known-good calm state" if is_clear else "preserve coherence while handling threats",
            "task_completion": "background drive to keep acting",
        }
        if failure_boost > 0:
            reasons["survival"] += f"; failure memory boost={failure_boost:.2f}"
            reasons["risk_reduction"] += f"; failure memory boost={failure_boost:.2f}"

        ranked = [
            {"goal": goal, "score": float(scores[goal]), "reason": reasons[goal]}
            for goal in self.GOAL_ORDER
        ]
        ranked.sort(key=lambda item: (-item["score"], self.GOAL_ORDER.index(item["goal"])))
        return ranked

    def dominant_goal(self, state: set) -> str:
        goals = self.compute_goals(state)
        return goals[0]["goal"] if goals else "task_completion"

    def intent_vector(self, state: set) -> list[float]:
        ranked = self.compute_goals(state)
        lookup = {item["goal"]: item["score"] for item in ranked}
        return [float(lookup[goal]) for goal in self.GOAL_ORDER]
