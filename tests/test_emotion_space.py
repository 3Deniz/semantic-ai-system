import unittest

from cognition.emotion_space import EmotionSpace


class TestEmotionSpace(unittest.TestCase):
    def test_from_state_threat(self):
        es = EmotionSpace().from_state({"crisis"})
        self.assertGreaterEqual(es.fear, 1.0)
        self.assertLessEqual(es.calm, 0.1)

    def test_from_state_positive(self):
        es = EmotionSpace().from_state({"safe", "clear"})
        self.assertEqual(es.fear, 0.0)
        self.assertGreater(es.calm, 0.5)

    def test_from_surprise_updates_surprise_and_calm(self):
        es = EmotionSpace().from_state({"rain"})
        before = es.to_vector()
        es.from_surprise(0.6)
        after = es.to_vector()
        self.assertGreater(after[3], before[3])
        self.assertLess(after[4], before[4])

    def test_blend_with_confidence(self):
        es = EmotionSpace().from_state({"clear"})
        calm_before = es.calm
        es.blend_with_confidence(0.5)
        self.assertAlmostEqual(es.calm, calm_before * 0.5, places=6)

    def test_explain_contains_labels(self):
        es = EmotionSpace().from_state({"damage"})
        text = es.explain()
        self.assertIn("emotion=", text)
        self.assertIn("vector=[", text)

    def test_jepa_emotion_delta(self):
        es = EmotionSpace().from_state({"flood"})
        pre = es.to_vector()
        es.update_from_jepa(0.7, 0.8)
        post = es.to_vector()
        delta = [abs(post[i] - pre[i]) for i in range(5)]
        self.assertEqual(len(delta), 5)
        self.assertTrue(any(d > 0 for d in delta))


if __name__ == "__main__":
    unittest.main()
