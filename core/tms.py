import time
import uuid

class LiteTMS:
    def __init__(self, decay_rate=0.95, min_confidence=0.3):
        self.beliefs = []
        self.candidates = []
        self.decay_rate = decay_rate
        self.min_confidence = min_confidence

    def _build_record(self, triple, confidence, metadata=None, *, valid=True, stage="active_belief",
                      review_status="approved", candidate_id=None, promoted_at=None):
        now = time.time()
        meta = dict(metadata or {})
        return {
            "id": candidate_id or str(uuid.uuid4()),
            "triple": triple,
            "confidence": confidence,
            "timestamp": now,
            "created": now,
            "valid": valid,
            "usage": 1,
            "importance": 0,
            "stage": stage,
            "review_status": review_status,
            "provenance": meta,
            "promoted_at": promoted_at,
        }

    def add_belief(self, triple, confidence, metadata=None):
        now = time.time()

        for belief in self.beliefs:
            if belief["triple"] == triple:
                belief["confidence"] = confidence
                belief["timestamp"] = now
                belief["valid"] = True
                belief["usage"] += 1
                belief["stage"] = "active_belief"
                belief["review_status"] = "approved"
                if metadata:
                    belief["provenance"] = dict(metadata)
                return

        self.beliefs.append(self._build_record(triple, confidence, metadata))

    def add_candidate_belief(self, triple, confidence, metadata=None):
        record = self._build_record(
            triple,
            confidence,
            metadata,
            valid=False,
            stage="candidate_knowledge",
            review_status="pending",
        )
        self.candidates.append(record)
        return record["id"]

    def get_candidate_beliefs(self, review_status=None):
        if review_status is None:
            return list(self.candidates)
        return [c for c in self.candidates if c["review_status"] == review_status]

    def get_candidate_belief(self, candidate_id):
        for candidate in self.candidates:
            if candidate["id"] == candidate_id:
                return candidate
        return None

    def promote_candidate_belief(self, candidate_id):
        candidate = self.get_candidate_belief(candidate_id)
        if candidate is None or candidate["review_status"] != "pending":
            return None

        candidate["review_status"] = "approved"
        candidate["stage"] = "validated_knowledge"
        candidate["promoted_at"] = time.time()

        promoted = {
            **candidate,
            "valid": True,
            "stage": "active_belief",
            "review_status": "approved",
        }
        self.beliefs.append(promoted)
        return promoted

    def reject_candidate_belief(self, candidate_id, reason=None):
        candidate = self.get_candidate_belief(candidate_id)
        if candidate is None or candidate["review_status"] != "pending":
            return None
        candidate["review_status"] = "rejected"
        candidate["stage"] = "rejected_candidate"
        if reason:
            candidate["provenance"]["review_reason"] = reason
        candidate["timestamp"] = time.time()
        return candidate

    def compute_importance(self, belief):
        age = time.time() - belief["created"]

        importance = (
            belief["confidence"] * 0.5 +
            belief["usage"] * 0.2 +
            min(age / 30, 1.0) * 0.3
        )

        # ✅ FIX: normalize
        return min(1.0, importance)

    def resolve_conflict(self, new_triple, new_conf):
        s_new, r_new, o_new = new_triple

        if "_NOT" in r_new:
            opposite = r_new.replace("_NOT", "")
        else:
            opposite = r_new + "_NOT"

        for belief in self.beliefs:
            s, r, o = belief["triple"]

            if s == s_new and o == o_new and r == opposite:
                if new_conf > belief["confidence"]:
                    belief["valid"] = False
                    return True
                return False

        return True

    def apply_decay(self):
        now = time.time()

        for belief in self.beliefs:
            if not belief["valid"]:
                continue

            belief["importance"] = self.compute_importance(belief)

            if belief["importance"] > 0.8:
                decay_factor = self.decay_rate ** ((now - belief["timestamp"]) / 20)
            else:
                decay_factor = self.decay_rate ** ((now - belief["timestamp"]) / 5)

            old_conf = belief["confidence"]
            belief["confidence"] *= decay_factor

            print(f"DECAY: {belief['triple']} {old_conf:.2f} → {belief['confidence']:.2f} (imp={belief['importance']:.2f})")

            if belief["confidence"] < self.min_confidence:
                belief["valid"] = False
                print(f"REMOVED: {belief['triple']}")

    def get_valid_triples(self):
        return [
            (b["triple"], b["confidence"])
            for b in self.beliefs if b["valid"]
        ]
