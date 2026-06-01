"""
Inductive Learning Module - Pattern extraction from examples.
Learns general rules from specific examples like a child would.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum


class OperationType(Enum):
    ADDITION = "+"
    SUBTRACTION = "-"
    MULTIPLICATION = "*"
    DIVISION = "/"
    POWER = "^"


@dataclass
class LearnedRule:
    """Represents a rule learned from examples."""
    predicate: str
    rule_type: str
    pattern: Any
    confidence: float
    examples_used: int
    description: str


class PatternExtractor:
    """Extracts mathematical patterns from example pairs."""

    @staticmethod
    def extract_numeric_pattern(pairs: List[Tuple[float, float]]) -> Optional[Dict]:
        """Extract pattern from numeric examples.

        Example: [(2,5), (3,7), (4,9)] -> {"operation": "add", "constant": 3}
        """
        if len(pairs) < 2:
            return None

        subjects = [p[0] for p in pairs]
        objects = [p[1] for p in pairs]

        # Try to find linear relationship: y = a*x + b
        x_mean = sum(subjects) / len(subjects)
        y_mean = sum(objects) / len(objects)

        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(subjects, objects))
        denominator = sum((x - x_mean) ** 2 for x in subjects)

        if denominator != 0:
            slope = numerator / denominator
            intercept = y_mean - slope * x_mean

            is_linear = all(
                abs(y - (slope * x + intercept)) < 0.0001
                for x, y in zip(subjects, objects)
            )

            if is_linear:
                return {
                    "type": "linear",
                    "slope": slope,
                    "intercept": intercept,
                    "formula": f"y = {slope} * x + {intercept}",
                }

        # Try to find constant operation
        operations = [
            ("add", lambda x, y: y - x),
            ("multiply", lambda x, y: y / x if x != 0 else None),
            ("power", lambda x, y: None),
        ]

        for op_name, op_func in operations:
            constants = []
            valid = True

            for x, y in pairs:
                const = op_func(x, y)
                if const is None:
                    valid = False
                    break
                constants.append(const)

            if valid and len(set(constants)) == 1:
                return {
                    "type": "constant_operation",
                    "operation": op_name,
                    "constant": constants[0],
                    "formula": f"y = x {op_name} {constants[0]}",
                }

        return None

    @staticmethod
    def extract_string_pattern(pairs: List[Tuple[str, str]]) -> Optional[Dict]:
        """Extract pattern from string examples."""
        subjects = [p[0] for p in pairs]
        objects = [p[1] for p in pairs]

        # Check for identity
        if all(s == o for s, o in pairs):
            return {"type": "identity", "formula": "x = y"}

        # Check for prefix addition
        if all(o.startswith(s) for s, o in pairs):
            suffixes = [o[len(s):] for s, o in pairs]
            if len(set(suffixes)) == 1:
                return {
                    "type": "add_prefix",
                    "prefix": suffixes[0],
                    "formula": f"y = x + '{suffixes[0]}'",
                }

        # Check for suffix addition
        if all(o.endswith(s) for s, o in pairs):
            prefixes = [o[: -len(s)] if len(o) > len(s) else "" for s, o in pairs]
            if len(set(prefixes)) == 1:
                return {
                    "type": "add_suffix",
                    "suffix": prefixes[0],
                    "formula": f"y = '{prefixes[0]}' + x",
                }

        return None


class InductiveLearner:
    """Learns patterns from examples.

    Like a child: sees examples, infers rules, makes predictions.
    """

    def __init__(self):
        self.rules: Dict[str, List[LearnedRule]] = defaultdict(list)
        self.examples: Dict[str, List[Tuple]] = defaultdict(list)
        self.pattern_extractor = PatternExtractor()

    def add_examples(self, predicate: str, examples: List[Tuple]) -> Optional[LearnedRule]:
        """Add examples and try to learn a pattern.

        Args:
            predicate: The relation (e.g., "+", "knows_capital")
            examples: List of (subject, object) pairs

        Returns:
            LearnedRule if pattern found, None otherwise.
        """
        self.examples[predicate].extend(examples)

        # Need at least 3 examples to learn a pattern
        if len(self.examples[predicate]) < 3:
            return None

        all_pairs = self.examples[predicate]
        is_numeric = all(
            isinstance(s, (int, float)) and isinstance(o, (int, float))
            for s, o in all_pairs
        )

        pattern = None
        if is_numeric:
            pattern = self.pattern_extractor.extract_numeric_pattern(all_pairs)
        else:
            pattern = self.pattern_extractor.extract_string_pattern(all_pairs)

        if pattern:
            rule = LearnedRule(
                predicate=predicate,
                rule_type=pattern["type"],
                pattern=pattern,
                confidence=0.85 if len(all_pairs) >= 5 else 0.7,
                examples_used=len(all_pairs),
                description=pattern.get("formula", "Pattern learned"),
            )
            self.rules[predicate].append(rule)
            return rule

        return None

    def predict(self, predicate: str, subject: Any) -> Optional[Any]:
        """Predict object using learned rules.

        Args:
            predicate: The relation
            subject: Input value

        Returns:
            Predicted object or None if no rule applies.
        """
        rules = self.rules.get(predicate, [])

        for rule in rules:
            pattern = rule.pattern

            if rule.rule_type == "linear":
                return pattern["slope"] * subject + pattern["intercept"]

            elif rule.rule_type == "constant_operation":
                op = pattern["operation"]
                const = pattern["constant"]

                if op == "add":
                    return subject + const
                elif op == "multiply":
                    return subject * const

            elif rule.rule_type == "identity":
                return subject

            elif rule.rule_type == "add_prefix":
                return str(subject) + pattern["prefix"]

            elif rule.rule_type == "add_suffix":
                return pattern["suffix"] + str(subject)

        return None

    def get_confidence(self, predicate: str) -> float:
        """Returns confidence level for a predicate."""
        rules = self.rules.get(predicate, [])
        if not rules:
            return 0.0
        return max(r.confidence for r in rules)


class CuriousLearner:
    """Active learner that asks questions when uncertain.

    Like a curious child: "I don't know, can you teach me?"
    """

    def __init__(self, inductive_learner: InductiveLearner):
        self.learner = inductive_learner
        self.pending_questions: List[Dict] = []
        self.learning_history: List[Dict] = []

    def ask(self, predicate: str, subject: Any) -> Dict:
        """Ask about an unknown or uncertain fact.

        Returns a question object that can be presented to user.
        """
        prediction = self.learner.predict(predicate, subject)
        confidence = self.learner.get_confidence(predicate)

        if prediction is None:
            question = {
                "type": "unknown",
                "predicate": predicate,
                "subject": subject,
                "question": f"What is {subject} {predicate} ? Please give me an example.",
                "needs_example": True,
            }
            self.pending_questions.append(question)
            return question

        elif confidence < 0.8:
            question = {
                "type": "confirmation",
                "predicate": predicate,
                "subject": subject,
                "prediction": prediction,
                "confidence": confidence,
                "question": f"Is {subject} {predicate} {prediction} correct?",
                "needs_confirmation": True,
            }
            self.pending_questions.append(question)
            return question

        else:
            return {
                "type": "suggestion",
                "predicate": predicate,
                "subject": subject,
                "suggestion": prediction,
                "confidence": confidence,
                "message": f"I think {subject} {predicate} {prediction}",
            }

    def learn_from_feedback(self, predicate: str, subject: Any, correct_object: Any):
        """Learn from user feedback."""
        self.learner.add_examples(predicate, [(subject, correct_object)])

        self.learning_history.append({
            "predicate": predicate,
            "subject": subject,
            "learned_object": correct_object,
            "timestamp": None,
        })

        self.pending_questions = [
            q
            for q in self.pending_questions
            if not (q.get("predicate") == predicate and q.get("subject") == subject)
        ]

    def get_learning_summary(self) -> Dict:
        """Returns summary of what has been learned."""
        return {
            "total_rules": sum(len(rules) for rules in self.learner.rules.values()),
            "rules_by_predicate": {
                pred: [rule.description for rule in rules]
                for pred, rules in self.learner.rules.items()
            },
            "examples_learned": len(self.learning_history),
            "pending_questions": len(self.pending_questions),
        }


class AnalogicalReasoner:
    """Learns by analogy - mapping known concepts to new domains.

    Example: If child knows addition, can infer multiplication as repeated addition.
    """

    def __init__(self, learner: InductiveLearner, config_path: str = "config/analogy_map.json"):
        self.learner = learner
        self.analogy_map = self._load_analogy_map(config_path)

    def _load_analogy_map(self, config_path: str) -> dict:
        """Load analogy mappings from JSON config file."""
        path = Path(config_path)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return {tuple(k.split(',')): v for k, v in data.items()}
            except Exception:
                pass
        return {}

    def save_analogy_map(self, config_path: str = "config/analogy_map.json"):
        """Save current analogy map to JSON config file."""
        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {','.join(k): v for k, v in self.analogy_map.items()}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def transfer_knowledge(self, source_predicate: str, target_predicate: str) -> Optional[Dict]:
        """Transfer knowledge from source to target using analogy.

        Args:
            source_predicate: Known concept (e.g., "+")
            target_predicate: New concept to learn (e.g., "*")

        Returns:
            Transferred rules or None if no analogy found.
        """
        analogy_key = (source_predicate, target_predicate)
        reverse_key = (target_predicate, source_predicate)

        analogy = self.analogy_map.get(analogy_key) or self.analogy_map.get(reverse_key)

        if not analogy:
            return None

        source_rules = self.learner.rules.get(source_predicate, [])
        if not source_rules:
            return None

        transferred_rules = []

        for rule in source_rules:
            transferred = self._transform_rule(rule, analogy, source_predicate, target_predicate)
            if transferred:
                transferred_rules.append(transferred)

        return {
            "source": source_predicate,
            "target": target_predicate,
            "rules": transferred_rules,
            "explanation": analogy["explanation"],
        }

    def _transform_rule(self, rule: LearnedRule, analogy: Dict, source_predicate: str, target_predicate: str) -> Optional[LearnedRule]:
        """Transform a rule from source to target domain."""
        pattern = rule.pattern.copy()

        old_op, new_op = analogy["operator"]

        if rule.rule_type == "constant_operation":
            if pattern.get("operation") == old_op:
                pattern["operation"] = new_op

        return LearnedRule(
            predicate=target_predicate,
            rule_type=rule.rule_type,
            pattern=pattern,
            confidence=rule.confidence * 0.7,
            examples_used=rule.examples_used,
            description=f"[Analogy from {source_predicate}] {pattern.get('formula', '')}",
        )
