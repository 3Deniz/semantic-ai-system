from __future__ import annotations

"""Layered memory system.

Layers
------
short_term  : last N states/events (deque, fast decay)
working     : currently active context (goal + state)
long_term   : semantic summaries of stable patterns
failure     : records of what went wrong and why
"""

from collections import Counter, deque
from typing import Any
import time


class LayeredMemory:
    EMOTION_LABELS = ("fear", "anger", "sadness", "surprise", "calm")

    def __init__(self, short_term_size: int = 20):
        self.short_term_size = short_term_size
        self._short_term = deque(maxlen=short_term_size)
        self._failure_memory: list[dict[str, Any]] = []
        self._long_term: list[dict[str, Any]] = []
        self._pattern_counter: Counter[tuple[frozenset[str], str, frozenset[str]]] = Counter()
        self._working_memory: dict[str, Any] = {"state": set(), "goal": None, "timestamp": None}
        self._episodic_memory: list[dict[str, Any]] = []

    @staticmethod
    def _normalize_state(state: set | list | tuple) -> set[str]:
        return {str(item).lower() for item in state}

    def record(self, state: set, action: str, reward: float, outcome: set, emotion: list[float] | None = None) -> None:
        state_set = self._normalize_state(state)
        outcome_set = self._normalize_state(outcome)
        entry = {
            "state": state_set,
            "action": action,
            "reward": float(reward),
            "outcome": outcome_set,
            "timestamp": time.time(),
            "emotion": emotion,
        }
        self._short_term.append(entry)
        self._episodic_memory.append(entry.copy())

        if reward < -1:
            self._failure_memory.append(entry.copy())

        pattern_key = (frozenset(state_set), action, frozenset(outcome_set))
        self._pattern_counter[pattern_key] += 1
        if self._pattern_counter[pattern_key] >= 3:
            summary = {
                "state": sorted(state_set),
                "action": action,
                "outcome": sorted(outcome_set),
                "count": self._pattern_counter[pattern_key],
            }
            for existing in self._long_term:
                if (
                    existing["state"] == summary["state"]
                    and existing["action"] == summary["action"]
                    and existing["outcome"] == summary["outcome"]
                ):
                    existing["count"] = summary["count"]
                    break
            else:
                self._long_term.append(summary)

    def get_recency_score(self, state: set) -> float:
        state_set = self._normalize_state(state)
        total = len(self._short_term)
        if total == 0:
            return 0.0

        for offset, entry in enumerate(reversed(self._short_term), start=1):
            if entry["state"] == state_set:
                return max(0.0, 1.0 - (offset - 1) / total)
        return 0.0

    def get_frequency_score(self, state: set) -> float:
        state_set = self._normalize_state(state)
        total = len(self._short_term)
        if total == 0:
            return 0.0
        hits = sum(1 for entry in self._short_term if entry["state"] == state_set)
        return min(1.0, hits / total)

    def get_failure_score(self, state: set) -> float:
        state_set = self._normalize_state(state)
        total = len(self._failure_memory)
        if total == 0:
            return 0.0
        hits = sum(1 for entry in self._failure_memory if entry["state"] == state_set)
        return min(1.0, hits / total)

    def get_similar_failures(self, state: set) -> list:
        state_set = self._normalize_state(state)
        similar = []
        for entry in self._failure_memory:
            overlap = sorted(state_set.intersection(entry["state"]))
            if overlap:
                enriched = dict(entry)
                enriched["overlap"] = overlap
                enriched["state"] = sorted(entry["state"])
                enriched["outcome"] = sorted(entry["outcome"])
                similar.append(enriched)
        similar.sort(key=lambda item: (-len(item["overlap"]), -item["timestamp"]))
        return similar

    def get_working_memory(self) -> dict:
        return {
            "state": sorted(self._working_memory["state"]),
            "goal": self._working_memory["goal"],
            "timestamp": self._working_memory["timestamp"],
        }

    def set_working_memory(self, state: set, goal: str) -> None:
        self._working_memory = {
            "state": self._normalize_state(state),
            "goal": goal,
            "timestamp": time.time(),
        }

    def get_long_term_patterns(self) -> list:
        return [dict(pattern) for pattern in self._long_term]

    @property
    def short_term(self) -> list:
        return [
            {
                **entry,
                "state": sorted(entry["state"]),
                "outcome": sorted(entry["outcome"]),
            }
            for entry in self._short_term
        ]

    @property
    def failure_memory(self) -> list:
        return [
            {
                **entry,
                "state": sorted(entry["state"]),
                "outcome": sorted(entry["outcome"]),
            }
            for entry in self._failure_memory
        ]

    @property
    def long_term(self) -> list:
        return self.get_long_term_patterns()

    def get_episodic_memory(self, limit: int = 50) -> list[dict]:
        episodes = list(self._episodic_memory)
        entries = []
        for entry in episodes[-limit:]:
            e = dict(entry)
            e["state"] = sorted(e["state"]) if isinstance(e.get("state"), (set, frozenset)) else e.get("state", [])
            e["outcome"] = sorted(e["outcome"]) if isinstance(e.get("outcome"), (set, frozenset)) else e.get("outcome", [])
            entries.append(e)
        return entries

    def get_episodes_by_emotion(self, emotion: str, limit: int = 20) -> list[dict]:
        emotion = emotion.lower()
        if emotion not in self.EMOTION_LABELS:
            return []
        emotion_idx = self.EMOTION_LABELS.index(emotion)
        matches = []
        for entry in reversed(self._episodic_memory):
            vec = entry.get("emotion")
            if vec is not None and len(vec) > emotion_idx and vec[emotion_idx] > 0.3:
                e = dict(entry)
                e["state"] = sorted(e["state"]) if isinstance(e.get("state"), (set, frozenset)) else e.get("state", [])
                e["outcome"] = sorted(e["outcome"]) if isinstance(e.get("outcome"), (set, frozenset)) else e.get("outcome", [])
                matches.append(e)
                if len(matches) >= limit:
                    break
        return matches

    def get_emotional_trend(self, n: int = 10) -> dict:
        recent = list(self._episodic_memory)[-n:]
        if not recent:
            return {"avg_vector": [0.0] * 5, "count": 0}
        valid = [e["emotion"] for e in recent if e.get("emotion") is not None]
        if not valid:
            return {"avg_vector": [0.0] * 5, "count": 0}
        dims = len(valid[0])
        avg = [sum(vec[i] for vec in valid) / len(valid) for i in range(dims)]
        return {"avg_vector": avg, "count": len(valid)}
