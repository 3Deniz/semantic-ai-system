from __future__ import annotations

"""Multi-space state embedding.

Each state is projected into 6 independent spaces, each capturing a different
cognitive aspect of the same situation.

Spaces
------
risk     : immediate threat level             [flood, collapse, crisis, damage]
goal     : active priorities / urgency        [survival, stability, risk_reduction, consistency, task]
memory   : how strongly this resembles past   [computed from LayeredMemory similarity]
attention: salience / what to focus on        [dominant threat, novelty]
self     : self-model status                  [confidence, overload, novelty_surprise]
semantic : abstract relation to known triples [from KG belief count]
"""

from typing import Any

from cognition.emotion_space import EmotionSpace
from cognition.layered_memory import LayeredMemory
from cognition.intent import IntentEngine


class MultiSpaceEmbedding:
    def __init__(self, memory: LayeredMemory = None, kg: Any = None):
        self.memory = memory
        self.kg = kg
        self._intent_engine = IntentEngine(memory)
        self._emotion_space = EmotionSpace()

    @staticmethod
    def _normalize_state(state_set: set | list | tuple) -> set[str]:
        return {str(item).lower() for item in state_set}

    def embed(self, state_set: set) -> dict:
        state = self._normalize_state(state_set)
        threat_weights = {"flood": 1.0 / 4.0, "collapse": 3.0 / 4.0, "crisis": 1.0, "damage": 2.0 / 4.0}
        risk = [
            float(threat_weights["flood"] if "flood" in state else 0.0),
            float(threat_weights["collapse"] if "collapse" in state else 0.0),
            float(threat_weights["crisis"] if "crisis" in state else 0.0),
            float(threat_weights["damage"] if "damage" in state else 0.0),
        ]

        goal = [float(value) for value in self._intent_engine.intent_vector(state)]

        if self.memory is not None:
            memory = [
                float(self.memory.get_recency_score(state)),
                float(self.memory.get_frequency_score(state)),
                float(self.memory.get_failure_score(state)),
            ]
            context_load = min(1.0, len(self.memory.short_term) / max(1, self.memory.short_term_size))
        else:
            memory = [0.0, 0.0, 0.0]
            context_load = 0.0

        known_tokens = {"rain", "flood", "damage", "collapse", "crisis", "barrier", "evacuated", "release", "injury"}
        known_ratio = sum(1 for token in state if token in known_tokens) / max(1, len(state)) if state else 1.0
        confidence = min(1.0, 0.5 * known_ratio + 0.25 * memory[0] + 0.25 * memory[1])
        active_threats = sum(1 for token in ("flood", "damage", "collapse", "crisis") if token in state)
        overload = min(1.0, active_threats / 3.0) if active_threats > 2 else min(1.0, active_threats / 4.0)
        surprise = max(0.0, 1.0 - confidence)
        self_space = [float(confidence), float(overload), float(surprise)]

        attention = [
            float(min(1.0, active_threats / 3.0)),
            float(surprise),
            float(context_load),
        ]

        belief_count = len(getattr(self.kg, "triples", [])) if self.kg is not None else 0
        belief_density = min(1.0, belief_count / 20.0)
        tms = getattr(self.kg, "tms", None) if self.kg is not None else None
        if tms is None and self.kg is not None and hasattr(self.kg, "beliefs"):
            tms = self.kg
        conflict_count = 0
        if tms is not None and hasattr(tms, "beliefs"):
            belief_map = {}
            for belief in getattr(tms, "beliefs", []):
                triple = belief.get("triple", ())
                if len(triple) < 3:
                    continue
                s, r, o = triple[:3]
                key = (s, o)
                opposite = r.replace("_NOT", "") if "_NOT" in r else f"{r}_NOT"
                if (key, opposite) in belief_map:
                    conflict_count += 1
                belief_map[(key, r)] = True
        elif self.kg is not None:
            conflict_count = int(getattr(self.kg, "conflict_count", 0))
        semantic = [float(belief_density), float(min(1.0, conflict_count / 10.0))]

        emotion = self._emotion_space.from_state(state).to_vector()

        return {
            "risk": risk,
            "goal": goal,
            "memory": memory,
            "attention": attention,
            "self": self_space,
            "semantic": semantic,
            "emotion": emotion,
        }

    def flatten(self, spaces: dict) -> list[float]:
        flat: list[float] = []
        for key in ("risk", "goal", "memory", "attention", "self", "semantic", "emotion"):
            flat.extend(float(value) for value in spaces.get(key, []))
        return flat
