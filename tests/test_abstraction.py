import unittest
from unittest.mock import MagicMock

from core.tms import LiteTMS
from core.knowledge_graph import KnowledgeGraph
from learning.concept_learning import ConceptLearner
from learning.rule_learning import RuleLearner
from learning.curriculum import CurriculumController, PrerequisiteNotMetError


class TestAbstractionLearning(unittest.TestCase):
    def setUp(self):
        self.tms = LiteTMS()

    def test_concept_learner_abstraction_level(self):
        self.tms.add_belief(("rain", "causes", "flood"), confidence=0.9)
        self.tms.add_belief(("storm", "causes", "flood"), confidence=0.85)

        learner = ConceptLearner(self.tms)
        concepts = learner.learn()

        self.assertGreaterEqual(len(concepts), 1)
        concept = next(c for c in concepts if c["pattern"] == "X causes flood")
        self.assertIn("abstraction_level", concept)
        self.assertGreaterEqual(concept["abstraction_level"], 0.6)

    def test_rule_learner_abstraction(self):
        self.tms.add_belief(("rain", "is", "weather"), confidence=0.9)
        self.tms.add_belief(("weather", "causes", "flood"), confidence=0.8)

        learner = RuleLearner(self.tms)
        rules = learner.learn_rules()

        self.assertGreaterEqual(len(rules), 1)
        rule = rules[0]
        self.assertIn("abstraction", rule)
        self.assertGreaterEqual(rule["abstraction"], 0.0)

    def test_abstraction_gate_stage0(self):
        ctrl = CurriculumController()
        ctrl.current_stage = 0
        self.assertFalse(ctrl.get_abstraction_gate())
        with self.assertRaises(PrerequisiteNotMetError):
            ctrl.check_prerequisite("abstraction")

    def test_abstraction_gate_stage2(self):
        ctrl = CurriculumController()
        ctrl.current_stage = 2
        self.assertTrue(ctrl.get_abstraction_gate())
        ctrl.check_prerequisite("abstraction")  # should not raise


class TestPromoteAbstractionToCurriculum(unittest.TestCase):
    def test_promote_abstraction_to_curriculum(self):
        tms = LiteTMS()
        tms.add_belief(("rain", "causes", "flood"), confidence=0.9)
        tms.add_belief(("storm", "causes", "flood"), confidence=0.95)

        concept_learner = ConceptLearner(tms)
        concepts = concept_learner.learn()

        kg = KnowledgeGraph()
        promoted = []
        for c in concepts:
            if c.get("abstraction_level", 0) >= 0.6:
                kg.add("curriculum", "knows_abstract_concept", c["pattern"], c["abstraction_level"])
                promoted.append(c["pattern"])

        self.assertGreaterEqual(len(promoted), 1)
        self.assertTrue(any(r == "knows_abstract_concept" for _s, r, _o, _c in kg.triples))


if __name__ == "__main__":
    unittest.main()
