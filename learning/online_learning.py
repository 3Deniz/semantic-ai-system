class OnlineLearner:
    def __init__(self, tms):
        self.tms = tms

    def apply_feedback(self, triple, feedback, emotion: list[float] | None = None):
        for belief in self.tms.beliefs:
            if belief["triple"] == triple and belief["valid"]:

                old_conf = belief["confidence"]
                correct_boost = 0.1
                wrong_penalty = 0.2

                if emotion is not None and len(emotion) >= 3:
                    _fear, anger, _sadness = emotion[0], emotion[1], emotion[2]
                    if anger > 0.2:
                        wrong_penalty = min(0.5, wrong_penalty + anger * 0.2)
                    if _fear > 0.4:
                        correct_boost = max(0.05, correct_boost - _fear * 0.1)

                if feedback == "correct":
                    belief["confidence"] = min(1.0, belief["confidence"] + correct_boost)
                elif feedback == "wrong":
                    belief["confidence"] = max(0.0, belief["confidence"] - wrong_penalty)

                print(f"UPDATED: {triple} {old_conf} -> {belief['confidence']}")

                if belief["confidence"] < self.tms.min_confidence:
                    belief["valid"] = False
                    print(f"REMOVED: {triple}")
