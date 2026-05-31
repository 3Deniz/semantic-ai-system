import unittest

from core.conflict import detect_conflict
from core.knowledge_graph import KnowledgeGraph
from core.reasoning import Reasoner


class ReasoningTests(unittest.TestCase):
    def test_reasoner_infers_transitive_is_relation(self):
        graph = KnowledgeGraph()
        graph.add("cat", "is", "mammal", 0.9)
        graph.add("mammal", "is", "animal", 0.8)

        inferred = Reasoner(graph).infer()

        self.assertEqual(len(inferred), 1)
        s, r, o, confidence = inferred[0]
        self.assertEqual((s, r, o), ("cat", "is", "animal"))
        self.assertAlmostEqual(confidence, 0.72)

    def test_detect_conflict_handles_confidence_tuples(self):
        graph = KnowledgeGraph()
        graph.add("cat", "is", "mammal", 0.9)

        self.assertTrue(detect_conflict(graph, ("cat", "is_NOT", "mammal")))


if __name__ == "__main__":
    unittest.main()