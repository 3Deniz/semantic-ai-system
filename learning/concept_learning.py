from collections import defaultdict


class ConceptLearner:

    def __init__(self, tms):
        self.tms = tms

    def learn(self):
        pattern_counts = defaultdict(int)
        subject_sets = defaultdict(set)

        for belief in self.tms.beliefs:
            if not belief["valid"]:
                continue

            s, r, o = belief["triple"]

            key = (r, o)
            pattern_counts[key] += 1
            subject_sets[key].add(s)

        concepts = []

        for (r, o), count in pattern_counts.items():

            if count >= 2:
                unique_subjects = len(subject_sets[(r, o)])
                abstraction_level = min(1.0, unique_subjects / max(1, count))

                concepts.append({
                    "pattern": f"X {r} {o}",
                    "support": count,
                    "abstraction_level": abstraction_level,
                })

        return concepts
