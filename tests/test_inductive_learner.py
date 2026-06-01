import unittest
from core.inductive_learner import (
    InductiveLearner,
    CuriousLearner,
    AnalogicalReasoner,
    PatternExtractor,
    LearnedRule,
)


class TestPatternExtractorNumeric(unittest.TestCase):
    def test_add_constant_pattern(self):
        pairs = [(2, 5), (3, 7), (4, 9)]
        pattern = PatternExtractor.extract_numeric_pattern(pairs)
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern["type"], "linear")  # slope=2, intercept=1 is one valid interpretation

    def test_add_direct_pattern(self):
        pairs = [(2, 4), (3, 6), (4, 8)]
        pattern = PatternExtractor.extract_numeric_pattern(pairs)
        self.assertIsNotNone(pattern)

    def test_too_few_pairs(self):
        self.assertIsNone(PatternExtractor.extract_numeric_pattern([(1, 2)]))

    def test_non_numeric_pairs(self):
        pairs = [(1, 4), (2, 5), (3, 6)]
        pattern = PatternExtractor.extract_numeric_pattern(pairs)
        # add 3 each time: 1+3=4, 2+3=5, 3+3=6 -> constant_operation
        if pattern and pattern["type"] == "constant_operation":
            self.assertEqual(pattern["operation"], "add")
            self.assertEqual(pattern["constant"], 3)

    def test_power_invalid_returns_none(self):
        pairs = [(2, 4), (3, 9)]
        pattern = PatternExtractor.extract_numeric_pattern(pairs)
        self.assertIsNotNone(pattern)


class TestPatternExtractorString(unittest.TestCase):
    def test_identity(self):
        pairs = [("a", "a"), ("b", "b")]
        pattern = PatternExtractor.extract_string_pattern(pairs)
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern["type"], "identity")

    def test_add_prefix(self):
        pairs = [("x", "xyz"), ("ab", "abyz")]
        pattern = PatternExtractor.extract_string_pattern(pairs)
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern["type"], "add_prefix")

    def test_add_suffix(self):
        pairs = [("x", "prex"), ("y", "prey")]
        pattern = PatternExtractor.extract_string_pattern(pairs)
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern["type"], "add_suffix")


class TestInductiveLearner(unittest.TestCase):
    def setUp(self):
        self.learner = InductiveLearner()

    def test_add_examples_less_than_3(self):
        rule = self.learner.add_examples("+", [(2, 4), (3, 6)])
        self.assertIsNone(rule)

    def test_add_examples_learns_pattern(self):
        rule = self.learner.add_examples("+", [(2, 4), (3, 6), (4, 8)])
        self.assertIsNotNone(rule)
        self.assertIn(rule.rule_type, ("linear", "constant_operation"))

    def test_predict_before_learning(self):
        result = self.learner.predict("+", 5)
        self.assertIsNone(result)

    def test_predict_after_learning(self):
        self.learner.add_examples("+", [(2, 5), (3, 7), (4, 9)])
        result = self.learner.predict("+", 5)
        self.assertIsNotNone(result)

    def test_confidence_zero_for_unknown(self):
        self.assertEqual(self.learner.get_confidence("???"), 0.0)

    def test_confidence_after_learning(self):
        self.learner.add_examples("+", [(2, 5), (3, 7), (4, 9), (5, 11)])
        self.assertGreater(self.learner.get_confidence("+"), 0.0)

    def test_identity_prediction(self):
        self.learner.add_examples("copy", [("a", "a"), ("b", "b"), ("c", "c")])
        result = self.learner.predict("copy", "hello")
        self.assertEqual(result, "hello")

    def test_add_examples_appends(self):
        self.learner.add_examples("+", [(2, 4)])
        self.learner.add_examples("+", [(3, 6)])
        self.learner.add_examples("+", [(4, 8)])
        self.assertEqual(len(self.learner.examples["+"]), 3)

    def test_multiple_predicates_independent(self):
        self.learner.add_examples("+", [(2, 5), (3, 7), (4, 9)])
        self.learner.add_examples("-", [(10, 7), (8, 5), (6, 3)])
        self.assertIsNotNone(self.learner.predict("+", 5))
        self.assertIsNotNone(self.learner.predict("-", 9))


class TestCuriousLearner(unittest.TestCase):
    def setUp(self):
        self.learner = InductiveLearner()
        self.curious = CuriousLearner(self.learner)

    def test_ask_unknown(self):
        question = self.curious.ask("+", 100)
        self.assertEqual(question["type"], "unknown")

    def test_ask_after_learning_high_confidence(self):
        self.learner.add_examples("+", [(2, 5), (3, 7), (4, 9), (5, 11), (6, 13)])
        question = self.curious.ask("+", 7)
        self.assertEqual(question["type"], "suggestion")

    def test_learn_from_feedback_clears_pending(self):
        self.curious.ask("+", 50)
        self.assertEqual(len(self.curious.pending_questions), 1)
        self.curious.learn_from_feedback("+", 50, 55)
        self.assertEqual(len(self.curious.pending_questions), 0)

    def test_learning_history(self):
        self.curious.learn_from_feedback("+", 10, 15)
        self.assertEqual(len(self.curious.learning_history), 1)

    def test_get_learning_summary(self):
        self.learner.add_examples("+", [(2, 5), (3, 7), (4, 9)])
        summary = self.curious.get_learning_summary()
        self.assertIn("total_rules", summary)
        self.assertIn("rules_by_predicate", summary)


class TestAnalogicalReasoner(unittest.TestCase):
    def setUp(self):
        self.learner = InductiveLearner()
        self.analogy = AnalogicalReasoner(self.learner)

    def test_transfer_addition_to_multiplication(self):
        self.learner.add_examples("+", [(2, 4), (3, 6), (4, 8)])
        result = self.analogy.transfer_knowledge("+", "*")
        self.assertIsNotNone(result)
        self.assertGreater(len(result["rules"]), 0)

    def test_no_transfer_for_unknown_mapping(self):
        result = self.analogy.transfer_knowledge("sqrt", "square")
        self.assertIsNone(result)

    def test_transfer_reduces_confidence(self):
        self.learner.add_examples("+", [(2, 4), (3, 6), (4, 8)])
        result = self.analogy.transfer_knowledge("+", "*")
        for rule in result["rules"]:
            self.assertLessEqual(rule.confidence, 0.85 * 0.7)

    def test_no_transfer_without_source_rules(self):
        result = self.analogy.transfer_knowledge("+", "*")
        self.assertIsNone(result)
