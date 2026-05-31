import unittest

from core.knowledge_graph import KnowledgeGraph
from core.tms import LiteTMS
from core.space_relations import SpaceRelationsBuilder


class _DummyThoughtLoop:
    class _Memory:
        def get_working_memory(self):
            return {"state": ["flood"], "goal": "survival", "timestamp": 0.0}

        def get_similar_failures(self, _state):
            return [{"overlap": ["flood"], "timestamp": 0.0}]

    class _Intent:
        def compute_goals(self, _state):
            return [
                {"goal": "survival", "score": 1.0, "reason": "critical"},
                {"goal": "stability", "score": 0.7, "reason": "mid"},
            ]

    class _Embedding:
        def embed(self, _state):
            return {
                "attention": [0.9, 0.4, 0.2],
                "self": [0.8, 0.3, 0.2],
            }

    def __init__(self):
        self.memory = self._Memory()
        self.intent_engine = self._Intent()
        self.embedding = self._Embedding()


class TestSpaceRelationsBuilder(unittest.TestCase):
    def setUp(self):
        self.kg = KnowledgeGraph()
        self.tms = LiteTMS()
        self.kg.add("rain", "causes", "flood", 0.9, {"source_document": "doc.pdf", "page_index": 1})
        self.kg.add("flood", "causes", "damage", 0.8, {"source_document": "doc.pdf", "page_index": 2})
        self.tms.add_belief(("rain", "causes", "flood"), 0.9, {"source_document": "doc.pdf"})
        self.builder = SpaceRelationsBuilder(self.kg, self.tms, _DummyThoughtLoop())

    def test_build_includes_all_requested_spaces(self):
        result = self.builder.build(query="flood", include_spaces=["semantic", "memory", "goal", "risk", "attention", "self"])
        self.assertIn("spaces", result)
        for space in ("semantic", "memory", "goal", "risk", "attention", "self"):
            self.assertIn(space, result["spaces"])

    def test_build_contains_semantic_edges(self):
        result = self.builder.build(query="flood", include_spaces=["semantic"], max_depth=2)
        edges = result["edges"]
        self.assertTrue(any(e["space"] == "semantic" for e in edges))
        self.assertTrue(any(e["relation_type"] == "causes" for e in edges))

    def test_build_honors_max_edges(self):
        result = self.builder.build(query="flood", include_spaces=["semantic", "goal", "risk"], max_edges=50)
        self.assertLessEqual(len(result["edges"]), 50)


if __name__ == "__main__":
    unittest.main()
