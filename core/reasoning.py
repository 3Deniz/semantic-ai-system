class Reasoner:
    def __init__(self, graph, max_depth=5):
        self.graph = graph
        self.max_depth = max_depth

    def infer(self):
        inferred = []
        existing = set((s, r, o) for (s, r, o, _) in self.graph.triples)
        seen = set()

        for (s1, r1, o1, c1) in self.graph.triples:
            for (s2, r2, o2, c2) in self.graph.triples:

                if o1 == s2:

                    # ✅ SADECE güvenli chaining
                    if r1 == "is" and r2 == "is":
                        # transitive: A is B, B is C → A is C
                        key = (s1, "is", o2)
                        if key not in existing and key not in seen:
                            seen.add(key)
                            inferred.append((s1, "is", o2, min(c1, c2) * 0.9))

                    # ✅ ALL OTHER CHAINS BLOKLANIYOR
                    # çünkü semantic olarak yanlış olabilir

        return inferred
