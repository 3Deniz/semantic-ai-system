from __future__ import annotations


class EmotionSpace:
    def __init__(self):
        self.fear = 0.0
        self.anger = 0.0
        self.sadness = 0.0
        self.surprise = 0.0
        self.calm = 1.0

    def from_state(self, state_set) -> EmotionSpace:
        state = {str(s).lower() for s in state_set}
        active = state & {"flood", "damage", "collapse", "crisis"}

        if "crisis" in active:
            self.fear = 1.0
        elif "collapse" in active:
            self.fear = 0.8
        elif "damage" in active:
            self.fear = 0.5
        elif "flood" in active:
            self.fear = 0.4
        elif "rain" in state:
            self.fear = 0.1
        else:
            self.fear = 0.0

        self.anger = 0.3 if "barrier" in state and "flood" in state else 0.0
        self.sadness = 0.4 if "damage" in state else (0.2 if "flood" in state else 0.0)
        self.surprise = 0.0
        self.calm = max(0.0, 1.0 - max(self.fear, self.anger, self.sadness))
        return self

    def update_from_jepa(self, surprise: float, state_risk: float) -> list[float]:
        self.surprise = min(1.0, self.surprise + surprise)
        self.calm = max(0.0, self.calm - surprise * 0.5)
        if surprise > 0.3 and state_risk > 0.5:
            self.fear = min(1.0, self.fear + surprise * state_risk)
        if surprise < 0.1 and state_risk < 0.2:
            self.calm = min(1.0, self.calm + 0.1)
        return self.to_vector()

    def from_surprise(self, surprise_val: float) -> EmotionSpace:
        self.update_from_jepa(surprise_val, self.fear)
        return self

    def blend_with_confidence(self, confidence: float) -> EmotionSpace:
        self.calm *= confidence
        return self

    def to_vector(self) -> list[float]:
        return [self.fear, self.anger, self.sadness, self.surprise, self.calm]

    def explain(self) -> str:
        parts = []
        if self.fear > 0.5:
            parts.append("fear")
        if self.anger > 0.2:
            parts.append("anger")
        if self.sadness > 0.2:
            parts.append("sadness")
        if self.surprise > 0.3:
            parts.append("surprise")
        if self.calm > 0.5:
            parts.append("calm")
        if not parts:
            parts.append("neutral")
        vector_str = ", ".join(f"{v:.2f}" for v in self.to_vector())
        return f"emotion={'+'.join(parts)} vector=[{vector_str}]"
