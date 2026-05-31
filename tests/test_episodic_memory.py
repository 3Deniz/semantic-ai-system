import unittest

from cognition.layered_memory import LayeredMemory


class TestEpisodicMemory(unittest.TestCase):
    def setUp(self):
        self.memory = LayeredMemory(short_term_size=3)

    def test_record_with_emotion(self):
        self.memory.record({"flood"}, "barrier", 1.0, {"safe"}, emotion=[0.6, 0.0, 0.2, 0.1, 0.3])
        episodes = self.memory.get_episodic_memory()
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["action"], "barrier")
        self.assertEqual(episodes[0]["emotion"][0], 0.6)

    def test_get_episodic_memory_limit(self):
        for i in range(6):
            self.memory.record({f"s{i}"}, "none", float(i), {"o"}, emotion=[0.0, 0.0, 0.0, 0.0, 1.0])
        episodes = self.memory.get_episodic_memory(limit=3)
        self.assertEqual(len(episodes), 3)

    def test_get_episodes_by_emotion(self):
        self.memory.record({"flood"}, "barrier", 1.0, {"safe"}, emotion=[0.8, 0.1, 0.0, 0.0, 0.1])
        self.memory.record({"clear"}, "none", 0.1, {"clear"}, emotion=[0.0, 0.0, 0.0, 0.0, 0.9])
        fear_episodes = self.memory.get_episodes_by_emotion("fear", limit=10)
        self.assertEqual(len(fear_episodes), 1)
        self.assertEqual(fear_episodes[0]["action"], "barrier")

    def test_get_emotional_trend(self):
        self.memory.record({"a"}, "none", 0.0, {"b"}, emotion=[0.6, 0.0, 0.0, 0.2, 0.2])
        self.memory.record({"c"}, "none", 0.0, {"d"}, emotion=[0.4, 0.2, 0.0, 0.0, 0.4])
        trend = self.memory.get_emotional_trend(n=5)
        self.assertEqual(trend["count"], 2)
        self.assertEqual(len(trend["avg_vector"]), 5)
        self.assertGreater(trend["avg_vector"][0], 0.4)

    def test_episodic_memory_limit_parameter(self):
        for i in range(12):
            self.memory.record({f"state_{i}"}, "none", 0.0, {"ok"}, emotion=[0.1, 0.1, 0.1, 0.1, 0.6])
        episodes = self.memory.get_episodic_memory(limit=5)
        self.assertEqual(len(episodes), 5)


if __name__ == "__main__":
    unittest.main()
