from collections import defaultdict


class RuleLearner:

    def __init__(self, tms):
        self.tms = tms
        self.rules = []

    def learn_rules(self):
        triples = [
            belief for belief in self.tms.beliefs
            if belief["valid"]
        ]

        subject_counts = defaultdict(int)
        for b in triples:
            subject_counts[b["triple"][0]] += 1

        for b1 in triples:
            for b2 in triples:

                s1, r1, o1 = b1["triple"]
                s2, r2, o2 = b2["triple"]

                if o1 == s2:

                    if r1 == "is":

                        weight = (b1["confidence"] + b2["confidence"]) / 2

                        premise_abstraction = min(1.0, 1.0 / max(1, subject_counts.get(s1, 1)))
                        conclusion_abstraction = min(1.0, 1.0 / max(1, subject_counts.get(s2, 1)))
                        abstraction = (premise_abstraction + conclusion_abstraction) / 2.0

                        new_rule = {
                            "if": (r1, o1),
                            "then": (r2, o2),
                            "weight": weight,
                            "usage": 1,
                            "abstraction": abstraction,
                            "context": {s1, s2},
                        }

                        self._add_or_update_rule(new_rule)

        self._soft_prune()

        return self.rules

    def _add_or_update_rule(self, new_rule):
        for r in self.rules:
            if r["if"] == new_rule["if"] and r["then"] == new_rule["then"]:
                r["usage"] += 1
                r["weight"] = (r["weight"] + new_rule["weight"]) / 2
                r["abstraction"] = (r["abstraction"] + new_rule["abstraction"]) / 2.0
                r["context"] = r["context"] | new_rule.get("context", set())
                return

        self.rules.append(new_rule)

    def _soft_prune(self):
        self.rules = [
            r for r in self.rules
            if not (r["weight"] < 0.3 and r["usage"] < 2)
        ]

    def apply_rules(self, graph, max_abstraction: float | None = None):
        inferred = []

        for (s, r, o, c) in graph.triples:

            for rule in self.rules:

                if max_abstraction is not None and rule.get("abstraction", 1.0) > max_abstraction:
                    continue

                r_if, o_if = rule["if"]
                r_then, o_then = rule["then"]

                if r == r_if and o == o_if:

                    new_conf = c * rule["weight"]

                    new_triple = (s, r_then, o_then, new_conf)

                    if new_triple not in graph.triples:
                        inferred.append(new_triple)

        return inferred
