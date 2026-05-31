from __future__ import annotations

"""Conflict resolution for the deliberative thought loop.

A ConflictResolver takes a set of candidate actions with their multi-source
scores and resolves tensions between competing goals:

  - immediate intervention vs. waiting
  - safe choice vs. fast choice
  - past experience vs. current observation
  - rule-based reasoning vs. intuition (JEPA)

Resolution strategy
-------------------
1. Identify dominant goal from IntentEngine
2. For each action, compute tension score = |score_A - score_B| across score sources
3. If tension > threshold → deliberate (weight by goal)
4. Output: resolved action + explanation of which tension was resolved and how
"""

from cognition.intent import IntentEngine


class ConflictResolver:
    def __init__(self, intent_engine: IntentEngine):
        self.intent_engine = intent_engine

    def resolve(self, state: set, scores: dict, sources: dict, emotion: list[float] | None = None) -> dict:
        dominant_goal = self.intent_engine.dominant_goal(state)
        tensions = self._detect_tensions(sources)
        weighted_scores = self._apply_goal_weighting(scores, dominant_goal, emotion)

        ranked = sorted(weighted_scores.items(), key=lambda item: item[1], reverse=True)
        action, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        action_tension = sum(item["delta"] for item in tensions if item["action"] == action)
        confidence = max(0.0, min(1.0, 0.55 + (top_score - second_score) - 0.1 * action_tension))

        if tensions:
            resolution = f"Resolved {len(tensions)} tension(s) in favor of {dominant_goal}"
        else:
            resolution = f"Low tension; followed dominant goal {dominant_goal}"

        return {
            "action": action,
            "confidence": float(confidence),
            "tensions": tensions,
            "resolution": resolution,
        }

    def _detect_tensions(self, sources: dict) -> list[dict]:
        tensions = []
        pairs = (("q", "sim"), ("q", "jepa"), ("sim", "jepa"))
        for action, action_sources in sources.items():
            for left, right in pairs:
                if left not in action_sources or right not in action_sources:
                    continue
                delta = abs(float(action_sources[left]) - float(action_sources[right]))
                if delta > 0.5:
                    tensions.append({
                        "action": action,
                        "between": [left, right],
                        "delta": float(delta),
                        "values": {left: float(action_sources[left]), right: float(action_sources[right])},
                    })
        return tensions

    def _apply_goal_weighting(self, scores: dict, goal: str, emotion: list[float] | None = None) -> dict:
        goal_boosts = {
            "survival": {"evacuate": 0.35, "barrier": 0.1, "release": 0.05, "none": -0.2},
            "stability": {"barrier": 0.3, "release": 0.2, "evacuate": 0.1, "none": -0.1},
            "risk_reduction": {"barrier": 0.25, "release": 0.25, "evacuate": 0.05, "none": -0.1},
            "consistency": {"none": 0.2, "barrier": 0.1, "release": -0.05, "evacuate": -0.1},
            "task_completion": {"barrier": 0.05, "release": 0.05, "evacuate": 0.0, "none": 0.1},
        }
        boosts = goal_boosts.get(goal, {})
        if emotion is not None and len(emotion) >= 3:
            fear, _anger, _sadness = emotion[0], emotion[1], emotion[2]
            if fear > 0.5:
                boosts["evacuate"] = boosts.get("evacuate", 0.0) + fear * 0.2
                boosts["none"] = boosts.get("none", 0.0) - fear * 0.15
        return {action: float(score + boosts.get(action, 0.0)) for action, score in scores.items()}
