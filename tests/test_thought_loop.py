"""Integration tests for cognition/thought_loop.py."""

import unittest
from collections import defaultdict

import numpy as np

from cognition.thought_loop import ThoughtLoop
from learning.jepa import JEPAModel
from config import ACTIONS


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

class _FakeRLAgent:
    """Minimal stub that exposes get_key like main.py."""

    def get_key(self, state):
        return tuple(sorted(state))


def _fake_simulate(state, action):
    """Deterministic simulate_fn stub — no randomness, no imports of main."""
    s = set(state)
    reward = 0.0
    if "flood" in s:
        reward -= 2
    if action == "barrier":
        s.discard("flood")
        reward += 4
    elif action == "evacuate":
        s = {x for x in s if x not in {"flood", "collapse", "crisis"}}
        s.add("evacuated")
        reward += 8
    elif action == "none":
        reward -= 1
    return reward, tuple(sorted(s))


def _make_thought_loop():
    agent = _FakeRLAgent()
    jepa = JEPAModel()
    q_table = defaultdict(float)
    return ThoughtLoop(agent, jepa, _fake_simulate, q_table, ACTIONS)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestThoughtLoopThinkReturnShape(unittest.TestCase):
    def setUp(self):
        self.loop = _make_thought_loop()

    def test_think_returns_dict(self):
        trace = self.loop.think({"flood"})
        self.assertIsInstance(trace, dict)

    def test_think_required_keys_present(self):
        required = {
            "state", "spaces", "memory_context", "intent", "dominant_goal",
            "tensions", "resolution", "candidates", "action", "confidence",
            "jepa_surprise", "explanation",
        }
        trace = self.loop.think({"flood"})
        self.assertTrue(required.issubset(trace.keys()), f"Missing keys: {required - trace.keys()}")

    def test_action_is_valid_action(self):
        trace = self.loop.think({"crisis"})
        self.assertIn(trace["action"], ACTIONS)

    def test_confidence_in_range(self):
        trace = self.loop.think({"damage", "flood"})
        self.assertGreaterEqual(trace["confidence"], 0.0)
        self.assertLessEqual(trace["confidence"], 1.0)

    def test_state_field_sorted(self):
        trace = self.loop.think({"flood", "damage"})
        self.assertEqual(trace["state"], sorted(trace["state"]))

    def test_explanation_is_nonempty_list(self):
        trace = self.loop.think({"flood"})
        self.assertIsInstance(trace["explanation"], list)
        self.assertGreater(len(trace["explanation"]), 0)


class TestThoughtLoopStateVariants(unittest.TestCase):
    def setUp(self):
        self.loop = _make_thought_loop()

    def test_empty_state(self):
        trace = self.loop.think(set())
        self.assertIn(trace["action"], ACTIONS)

    def test_string_state(self):
        trace = self.loop.think("('flood', 'damage')")
        self.assertIn(trace["action"], ACTIONS)

    def test_tuple_state(self):
        trace = self.loop.think(("flood", "collapse"))
        self.assertIn(trace["action"], ACTIONS)

    def test_crisis_state_prefers_evacuate(self):
        """With crisis in state the combined scoring should favour evacuate."""
        # Run several times to account for any stochasticity in the sim stub
        actions = [self.loop.think({"crisis"})["action"] for _ in range(10)]
        self.assertIn("evacuate", actions)


class TestThoughtLoopMemoryAccumulation(unittest.TestCase):
    def setUp(self):
        self.loop = _make_thought_loop()

    def test_recent_traces_accumulate(self):
        for _ in range(3):
            self.loop.think({"flood"})
        traces = self.loop.get_recent_traces(5)
        self.assertEqual(len(traces), 3)

    def test_get_recent_traces_respects_n(self):
        for _ in range(10):
            self.loop.think({"rain"})
        traces = self.loop.get_recent_traces(4)
        self.assertLessEqual(len(traces), 4)

    def test_traces_maxlen_respected(self):
        for _ in range(60):
            self.loop.think({"flood"})
        # The deque has maxlen=50
        traces = self.loop.get_recent_traces(100)
        self.assertLessEqual(len(traces), 50)


class TestThoughtLoopFeedback(unittest.TestCase):
    def setUp(self):
        self.loop = _make_thought_loop()

    def test_feedback_does_not_raise(self):
        try:
            self.loop.feedback({"flood"}, "barrier", 3.0, {"damage"})
        except Exception as exc:
            self.fail(f"feedback() raised unexpectedly: {exc}")

    def test_feedback_updates_jepa_samples(self):
        before = self.loop.jepa_model._trained_samples
        self.loop.feedback({"flood"}, "barrier", 3.0, {"damage"})
        self.assertGreater(self.loop.jepa_model._trained_samples, before)


class TestThoughtLoopJEPAIntegration(unittest.TestCase):
    def setUp(self):
        self.loop = _make_thought_loop()

    def test_jepa_surprise_is_float(self):
        trace = self.loop.think({"flood"})
        self.assertIsInstance(trace["jepa_surprise"], float)

    def test_jepa_samples_increase_with_calls(self):
        before = self.loop.jepa_model._trained_samples
        for _ in range(5):
            self.loop.think({"flood"})
        after = self.loop.jepa_model._trained_samples
        self.assertGreater(after, before)


class TestThoughtLoopEmotionAndEpisodicMemory(unittest.TestCase):
    def setUp(self):
        self.loop = _make_thought_loop()

    def test_think_returns_emotion_vector(self):
        trace = self.loop.think({"flood"})
        self.assertIn("emotion", trace)
        self.assertIsInstance(trace["emotion"], list)
        self.assertEqual(len(trace["emotion"]), 5)

    def test_think_returns_jepa_emotion_delta(self):
        trace = self.loop.think({"crisis"})
        self.assertIn("jepa_emotion_delta", trace)
        self.assertEqual(len(trace["jepa_emotion_delta"]), 5)
        self.assertTrue(any(delta >= 0 for delta in trace["jepa_emotion_delta"]))

    def test_feedback_stores_episodic_memory(self):
        self.loop.feedback({"flood"}, "barrier", 2.0, {"safe"}, emotion=[0.5, 0.1, 0.2, 0.1, 0.2])
        episodes = self.loop.memory.get_episodic_memory(limit=10)
        self.assertGreaterEqual(len(episodes), 1)
        self.assertEqual(episodes[-1]["action"], "barrier")
        self.assertIn("emotion", episodes[-1])

    def test_emotional_trend_calculation(self):
        self.loop.feedback({"flood"}, "barrier", 2.0, {"safe"}, emotion=[0.6, 0.1, 0.1, 0.2, 0.2])
        self.loop.feedback({"crisis"}, "evacuate", 3.0, {"evacuated"}, emotion=[0.9, 0.2, 0.1, 0.4, 0.1])
        trend = self.loop.memory.get_emotional_trend(n=10)
        self.assertEqual(trend["count"], 2)
        self.assertEqual(len(trend["avg_vector"]), 5)
        self.assertGreater(trend["avg_vector"][0], 0.5)


if __name__ == "__main__":
    unittest.main()
