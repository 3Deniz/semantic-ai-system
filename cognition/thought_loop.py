from __future__ import annotations

"""Deliberative Thought Loop.

Pipeline
--------
  Perception   → parse and embed state in 6 spaces
  Memory       → retrieve relevant past context
  Intent       → compute active goals
  Conflict     → resolve tensions between action candidates
  Simulation   → simulate outcomes for top 2 candidate actions
  Decision     → select best action
  Feedback     → write outcome to memory, update JEPA

Each call to `think(state)` returns a full ThoughtTrace:
{
  "state": list,
  "spaces": dict,         # 6-space embedding
  "memory_context": dict,
  "intent": list,         # ranked goals
  "dominant_goal": str,
  "tensions": list,
  "resolution": str,
  "candidates": dict,     # top actions + scores
  "action": str,
  "confidence": float,
  "jepa_surprise": float, # mismatch between predicted and actual latent
  "explanation": list     # human-readable explanation lines
}
"""

import ast
import logging
from collections import deque
from typing import Any, Callable

import numpy as np

from cognition.conflict_resolver import ConflictResolver
from cognition.emotion_space import EmotionSpace
from cognition.intent import IntentEngine
from cognition.layered_memory import LayeredMemory
from cognition.multispace_embedding import MultiSpaceEmbedding


# Minimum reward advantage over the conflict-resolved action needed to override it
SIMULATION_OVERRIDE_THRESHOLD = 0.2


class ThoughtLoop:
    def __init__(self, rl_agent, jepa_model, simulate_fn: Callable, q_table, actions):
        self.rl_agent = rl_agent
        self.jepa_model = jepa_model
        self.simulate_fn = simulate_fn
        self.q_table = q_table
        self.actions = list(actions)
        self.memory = LayeredMemory()
        self.intent_engine = IntentEngine(self.memory)
        self.embedding = MultiSpaceEmbedding(self.memory)
        self.conflict_resolver = ConflictResolver(self.intent_engine)
        self.emotion_space = EmotionSpace()
        self._recent_traces = deque(maxlen=50)

    def think(self, state) -> dict:
        state_set = self._coerce_state(state)
        spaces = self.embedding.embed(state_set)
        intent = self.intent_engine.compute_goals(state_set)
        dominant_goal = intent[0]["goal"] if intent else "task_completion"
        self.memory.set_working_memory(state_set, dominant_goal)

        memory_context = {
            "working": self.memory.get_working_memory(),
            "similar_failures": self.memory.get_similar_failures(state_set)[:3],
            "long_term_patterns": self.memory.get_long_term_patterns()[-5:],
        }

        key = self._state_key(state_set)
        raw_q = {action: float(self.q_table.get((key, action), 0.0)) for action in self.actions}
        raw_sim = {action: self._estimate_sim_score(state_set, action) for action in self.actions}
        raw_jepa = {action: self._estimate_jepa_score(state_set, action) for action in self.actions}

        q_scores = self._normalize_scores(raw_q)
        sim_scores = self._normalize_scores(raw_sim)
        jepa_scores = self._normalize_scores(raw_jepa)
        sources = {
            action: {"q": q_scores[action], "sim": sim_scores[action], "jepa": jepa_scores[action]}
            for action in self.actions
        }
        combined = {
            action: float(0.4 * q_scores[action] + 0.35 * sim_scores[action] + 0.25 * jepa_scores[action])
            for action in self.actions
        }

        resolution = self.conflict_resolver.resolve(state_set, combined, sources)
        top_actions = [action for action, _ in sorted(combined.items(), key=lambda item: item[1], reverse=True)[:2]]
        simulation_review = {
            action: self._simulate_candidate(state_set, action)
            for action in top_actions
        }

        final_action = resolution["action"]
        best_projection = simulation_review.get(final_action, {}).get("avg_reward", float("-inf"))
        for action, result in simulation_review.items():
            if result["avg_reward"] > best_projection + SIMULATION_OVERRIDE_THRESHOLD:
                final_action = action
                best_projection = result["avg_reward"]

        reward, next_state = self.simulate_fn(tuple(sorted(state_set)), final_action)
        next_state_set = self._coerce_state(next_state)
        state_vec = self._state_to_vec(state_set)
        actual_next_vec = self._state_to_vec(next_state_set)
        surprise = self._compute_jepa_surprise(state_vec, self._action_idx(final_action), actual_next_vec)

        confidence = resolution["confidence"]
        if final_action in simulation_review:
            confidence = min(1.0, max(confidence, 0.5 + max(0.0, simulation_review[final_action]["avg_reward"]) / 10.0))

        risk_level = float(sum(spaces.get("risk", [0.0]))) / max(1, len(spaces.get("risk", [1.0])))
        pre_jepa_emotion = self.emotion_space.from_state(state_set).to_vector()
        self.emotion_space.update_from_jepa(surprise, risk_level)
        self.emotion_space.blend_with_confidence(confidence)
        emotion_vec = self.emotion_space.to_vector()
        jepa_emotion_delta = [abs(emotion_vec[i] - pre_jepa_emotion[i]) for i in range(5)]
        spaces["emotion"] = emotion_vec
        self.feedback(state_set, final_action, reward, next_state_set, emotion=emotion_vec)

        ordered_candidates = {
            action: {
                "score": round(combined[action], 4),
                "q": round(q_scores[action], 4),
                "sim": round(sim_scores[action], 4),
                "jepa": round(jepa_scores[action], 4),
                "projected_reward": round(simulation_review.get(action, {}).get("avg_reward", raw_sim[action]), 4),
            }
            for action, _ in sorted(combined.items(), key=lambda item: item[1], reverse=True)[:3]
        }

        trace = {
            "state": sorted(state_set),
            "spaces": spaces,
            "memory_context": memory_context,
            "intent": intent,
            "dominant_goal": dominant_goal,
            "tensions": resolution["tensions"],
            "resolution": resolution["resolution"],
            "candidates": ordered_candidates,
            "action": final_action,
            "confidence": float(round(confidence, 4)),
            "jepa_surprise": float(round(surprise, 4)),
            "emotion": emotion_vec,
            "jepa_emotion_delta": [round(d, 4) for d in jepa_emotion_delta],
            "explanation": [],
        }
        trace["explanation"] = self._build_explanation(trace)
        self._recent_traces.append(trace)
        return trace

    def feedback(self, state: set, action: str, reward: float, next_state: set, emotion: list[float] | None = None) -> None:
        self.memory.record(state, action, reward, next_state, emotion=emotion)
        self.memory.set_working_memory(next_state, self.intent_engine.dominant_goal(next_state))
        try:
            state_vec = self._state_to_vec(state)
            next_vec = self._state_to_vec(next_state)
            self.jepa_model.update(state_vec, self._action_idx(action), next_vec)
        except Exception:
            logging.getLogger(__name__).exception("JEPA update failed in feedback()")

    def get_recent_traces(self, n: int = 5) -> list:
        return list(self._recent_traces)[-n:]

    def _estimate_sim_score(self, state: set[str], action: str, samples: int = 3) -> float:
        rewards = [self.simulate_fn(tuple(sorted(state)), action)[0] for _ in range(samples)]
        return float(sum(rewards) / max(1, samples))

    def _simulate_candidate(self, state: set[str], action: str, samples: int = 3) -> dict[str, Any]:
        rewards = []
        next_states = []
        for _ in range(samples):
            reward, next_state = self.simulate_fn(tuple(sorted(state)), action)
            rewards.append(float(reward))
            next_states.append(sorted(self._coerce_state(next_state)))
        return {
            "avg_reward": float(sum(rewards) / max(1, len(rewards))),
            "next_states": next_states,
        }

    def _estimate_jepa_score(self, state: set[str], action: str) -> float:
        try:
            return float(self.jepa_model.predict_score(self._state_to_vec(state), self._action_idx(action)))
        except Exception:
            return 0.0

    def _compute_jepa_surprise(self, state_vec, action_idx, actual_next_vec) -> float:
        try:
            ctx = self.jepa_model._encode_ctx(state_vec, action_idx)
            pred = self.jepa_model._predict(ctx)
            target = self.jepa_model._encode_target(actual_next_vec)
            return float(np.linalg.norm(pred - target) / max(1, len(target)))
        except Exception:
            return 0.0

    def _build_explanation(self, trace: dict) -> list[str]:
        lines = [
            f"Dominant goal: {trace['dominant_goal']}",
            f"Resolved action: {trace['action']} (confidence={trace['confidence']:.2f})",
            f"Resolution: {trace['resolution']}",
        ]
        if trace["tensions"]:
            first = trace["tensions"][0]
            lines.append(
                f"Primary tension on {first['action']} between {first['between'][0]} and {first['between'][1]} (Δ={first['delta']:.2f})"
            )
        else:
            lines.append("Sources were broadly aligned")

        top_candidates = list(trace["candidates"].items())[:2]
        for action, info in top_candidates:
            lines.append(
                f"Candidate {action}: score={info['score']:.2f}, projected_reward={info['projected_reward']:.2f}"
            )
        lines.append(f"JEPA surprise: {trace['jepa_surprise']:.2f}")
        lines.append(f"Emotion: {self.emotion_space.explain()}")
        if "jepa_emotion_delta" in trace:
            delta = trace["jepa_emotion_delta"]
            max_delta = max(delta) if delta else 0
            lines.append(f"JEPA-emotion delta: {max_delta:.4f}")
        return lines

    def _state_key(self, state: set[str]):
        if hasattr(self.rl_agent, "get_key"):
            return self.rl_agent.get_key(state)
        return tuple(sorted(state))

    def _action_idx(self, action: str) -> int:
        return self.actions.index(action)

    @staticmethod
    def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
        values = list(scores.values())
        if not values:
            return {}
        low = min(values)
        high = max(values)
        if abs(high - low) < 1e-9:
            fill = 0.5 if high != 0 else 0.0
            return {key: float(fill) for key in scores}
        return {key: float((value - low) / (high - low)) for key, value in scores.items()}

    @staticmethod
    def _coerce_state(state) -> set[str]:
        if isinstance(state, set):
            return {str(item).lower() for item in state}
        if isinstance(state, str):
            text = state.strip()
            if not text or text == "()":
                return set()
            try:
                parsed = ast.literal_eval(text)
            except Exception:
                parsed = [part.strip(" (){}[]'\"") for part in text.split(",")]
            if isinstance(parsed, str):
                parsed = [parsed]
            return {str(item).lower() for item in parsed if str(item)}
        return {str(item).lower() for item in state}

    @staticmethod
    def _state_to_vec(state_set) -> np.ndarray:
        state = ThoughtLoop._coerce_state(state_set)
        return np.array([
            float("flood" in state),
            float("collapse" in state),
            float("crisis" in state),
            float("damage" in state),
            float("barrier" in state),
            float("evacuated" in state),
            min(1.0, len(state) / 6.0),
        ], dtype=np.float32)
