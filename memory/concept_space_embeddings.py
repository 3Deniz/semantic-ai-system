from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

from memory.embeddings import embed_text


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class ConceptSpaceEmbeddings:
    """Persistent per-concept, per-space embedding store.

    Store shape:
    {
      "concept": {
        "created_at": float,
        "spaces": {
          "semantic": {
            "vector": [..],
            "updates": int,
            "last_confidence": float,
            "updated_at": float,
            "last_relation": str
          }
        }
      }
    }
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {}
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self._data = loaded
            else:
                self._data = {}
        except Exception:
            self._data = {}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._data, ensure_ascii=True, indent=2), encoding="utf-8")

    @staticmethod
    def _fact_vector(*, concept: str, space: str, subject: str, relation: str, obj: str, confidence: float) -> list[float]:
        text = f"space={space} concept={concept} subject={subject} relation={relation} object={obj}"
        base = embed_text(text, dimensions=8)
        # Append confidence and a fixed bias to keep numeric scale stable.
        return [*base, float(confidence), 1.0]

    def update_from_fact(
        self,
        *,
        concept: str,
        spaces: list[str],
        subject: str,
        relation: str,
        obj: str,
        confidence: float,
    ) -> None:
        concept_key = str(concept).strip().lower()
        if not concept_key:
            return

        now = float(time.time())
        with self._lock:
            entry = self._data.setdefault(concept_key, {"created_at": now, "spaces": {}})
            space_map = entry.setdefault("spaces", {})

            for space in spaces:
                if not space:
                    continue
                vector = self._fact_vector(
                    concept=concept_key,
                    space=space,
                    subject=str(subject),
                    relation=str(relation),
                    obj=str(obj),
                    confidence=float(confidence),
                )
                current = space_map.get(space)
                if current is None:
                    space_map[space] = {
                        "vector": vector,
                        "updates": 1,
                        "last_confidence": float(confidence),
                        "updated_at": now,
                        "last_relation": str(relation),
                    }
                    continue

                prev_vec = [float(v) for v in current.get("vector", [])]
                updates = int(current.get("updates", 1))
                if len(prev_vec) != len(vector):
                    merged = vector
                else:
                    # Running average update for stable, persistent representation.
                    merged = [((pv * updates) + nv) / (updates + 1) for pv, nv in zip(prev_vec, vector)]

                current["vector"] = merged
                current["updates"] = updates + 1
                current["last_confidence"] = float(confidence)
                current["updated_at"] = now
                current["last_relation"] = str(relation)

            self._save()

    def get_concept(self, concept: str) -> dict[str, object]:
        key = str(concept).strip().lower()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return {"concept": key, "spaces": {}, "space_differences": []}

            spaces = item.get("spaces", {}) if isinstance(item, dict) else {}
            diffs: list[dict[str, object]] = []
            space_names = sorted(spaces.keys())
            for i, left in enumerate(space_names):
                for right in space_names[i + 1:]:
                    l_vec = [float(v) for v in spaces[left].get("vector", [])]
                    r_vec = [float(v) for v in spaces[right].get("vector", [])]
                    if not l_vec or not r_vec or len(l_vec) != len(r_vec):
                        continue
                    l1 = sum(abs(a - b) for a, b in zip(l_vec, r_vec)) / len(l_vec)
                    diffs.append({
                        "left_space": left,
                        "right_space": right,
                        "cosine_similarity": round(_cosine_similarity(l_vec, r_vec), 6),
                        "l1_distance": round(float(l1), 6),
                    })

            return {
                "concept": key,
                "created_at": item.get("created_at"),
                "spaces": spaces,
                "space_differences": diffs,
            }
