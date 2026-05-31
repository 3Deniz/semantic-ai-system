"""core/data_loader.py — Bulk knowledge and RL-transition data ingestion.

Supported file formats
----------------------
- .json  : {"facts": [...], "texts": [...], "transitions": [...]}
- .jsonl : one {"subject", "relation", "object", "confidence"} dict per line
- .csv   : columns: subject, relation, object, confidence (header required)
- .txt   : one natural-language statement per line (# lines ignored)

JSON schema
-----------
{
  "facts": [
    {"subject": "rain", "relation": "causes", "object": "flood", "confidence": 0.9}
  ],
  "texts": [
    "flood leads to damage 0.85",
    "barrier prevents flood and damage"
  ],
  "transitions": [
    {"state": ["rain"], "action": "barrier", "reward": 3.0, "next_state": []}
  ]
}
"""

import csv
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from core.parser import SemanticParser
from core.pdf_ingestion import PDFIngestion, PDFIngestionError


class DataLoader:
    """Ingest knowledge and RL transitions into TMS, KnowledgeGraph, and Q-table."""

    def __init__(self, tms=None, kg=None, parser: Optional[SemanticParser] = None, pdf_ingestion: Optional[PDFIngestion] = None):
        self.tms    = tms
        self.kg     = kg
        self.parser = parser or SemanticParser()
        self.pdf_ingestion = pdf_ingestion or PDFIngestion()
        self._seen_document_fingerprints: set[str] = set()

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def load_file(self, path: str) -> dict:
        """Load a file and ingest its contents. Returns ingestion stats."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Data file not found: {p}")

        ext = p.suffix.lower()
        if ext == ".json":
            return self._load_json(p)
        if ext in (".jsonl", ".ndjson"):
            return self._load_jsonl(p)
        if ext == ".csv":
            return self._load_csv(p)
        if ext == ".txt":
            return self._load_text(p)
        raise ValueError(f"Unsupported file format: {ext!r}")

    def _load_json(self, path: Path) -> dict:
        with open(path) as f:
            data = json.load(f)
        return self._ingest(data)

    def _load_jsonl(self, path: Path) -> dict:
        triples_added = 0
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            record = json.loads(line)
            if self.ingest_triple(record):
                triples_added += 1
        return {"triples": triples_added, "transitions": 0, "q_updates": 0}

    def _load_csv(self, path: Path) -> dict:
        """CSV must have a header row with at least: subject, relation, object."""
        triples_added = 0
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fact = {
                    "subject":    row.get("subject", "").strip(),
                    "relation":   row.get("relation", "").strip(),
                    "object":     row.get("object", "").strip(),
                    "confidence": float(row.get("confidence", 0.8) or 0.8),
                    "negation":   row.get("negation", "").lower() in ("1", "true", "yes"),
                }
                if self.ingest_triple(fact):
                    triples_added += 1
        return {"triples": triples_added, "transitions": 0, "q_updates": 0}

    def _load_text(self, path: Path) -> dict:
        lines = [
            l.strip()
            for l in path.read_text().splitlines()
            if l.strip() and not l.startswith("#")
        ]
        return self.ingest_texts(lines)

    # ------------------------------------------------------------------
    # Direct injection
    # ------------------------------------------------------------------

    def ingest_texts(self, texts: list[str]) -> dict:
        """Parse natural-language statements and inject the resulting triples."""
        return self.ingest_texts_with_context(texts)

    def ingest_texts_with_context(
        self,
        texts: list[str],
        *,
        source_document: Optional[str] = None,
        stage: str = "validated",
        metadata: Optional[dict] = None,
    ) -> dict:
        """Parse natural-language statements with provenance and stage metadata."""
        triples_added = 0
        candidate_ids = []
        for text in texts:
            context = dict(metadata or {})
            if source_document:
                context["source_document"] = source_document
            parsed = self.parser.parse(text, context=context)
            if not parsed:
                continue
            for triple_dict in parsed:
                if stage == "candidate":
                    candidate_id = self.ingest_candidate_triple(triple_dict)
                    if candidate_id:
                        candidate_ids.append(candidate_id)
                elif self.ingest_triple(triple_dict):
                    triples_added += 1
        return {
            "triples": triples_added,
            "transitions": 0,
            "q_updates": 0,
            "candidates": len(candidate_ids),
            "candidate_ids": candidate_ids,
        }

    def ingest_document(
        self,
        document: str,
        *,
        source_document: str = "inline_document",
        stage: str = "candidate",
        metadata: Optional[dict] = None,
    ) -> dict:
        """Split a document into paragraph/sentence chunks and ingest each sentence."""
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", document) if p.strip()]
        triples_added = 0
        candidate_ids = []
        sentences_processed = 0

        for paragraph_index, paragraph in enumerate(paragraphs):
            sentences = [
                s.strip()
                for s in re.split(r"(?<=[.!?])\s+|\n", paragraph)
                if s.strip()
            ]
            for sentence_index, sentence in enumerate(sentences):
                sentence_metadata = {
                    **(metadata or {}),
                    "source_document": source_document,
                    "paragraph_index": paragraph_index,
                    "sentence_index": sentence_index,
                    "stage": stage,
                }
                result = self.ingest_texts_with_context(
                    [sentence],
                    source_document=source_document,
                    stage=stage,
                    metadata=sentence_metadata,
                )
                triples_added += result.get("triples", 0)
                candidate_ids.extend(result.get("candidate_ids", []))
                sentences_processed += 1

        return {
            "documents": 1,
            "sentences": sentences_processed,
            "triples": triples_added,
            "transitions": 0,
            "q_updates": 0,
            "candidates": len(candidate_ids),
            "candidate_ids": candidate_ids,
        }

    def ingest_pdf_document(
        self,
        pdf_bytes: bytes,
        *,
        source_document: str = "uploaded.pdf",
        stage: str = "candidate",
        metadata: Optional[dict] = None,
        ingestion_run_id: Optional[str] = None,
        skip_if_duplicate: bool = True,
    ) -> dict:
        """Extract and ingest a PDF with page/paragraph/sentence provenance."""
        run_id = ingestion_run_id or f"run_{uuid.uuid4().hex[:12]}"
        fingerprint = hashlib.sha256(pdf_bytes).hexdigest()

        if skip_if_duplicate and fingerprint in self._seen_document_fingerprints:
            return {
                "documents": 0,
                "pages": 0,
                "sentences": 0,
                "triples": 0,
                "transitions": 0,
                "q_updates": 0,
                "candidates": 0,
                "candidate_ids": [],
                "skipped": 1,
                "failed": 0,
                "ingestion_run_id": run_id,
                "source_document": source_document,
                "fingerprint": fingerprint,
            }

        try:
            pages = self.pdf_ingestion.extract_pages_from_bytes(pdf_bytes)
        except PDFIngestionError:
            raise

        triples_added = 0
        candidate_ids = []
        sentences_processed = 0
        skipped = 0

        for page in pages:
            page_index = int(page.get("page_index", 0))
            page_text = str(page.get("text", ""))
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", page_text) if p.strip()]

            for paragraph_index, paragraph in enumerate(paragraphs):
                sentences = [
                    s.strip()
                    for s in re.split(r"(?<=[.!?])\s+|\n", paragraph)
                    if s.strip()
                ]

                for sentence_index, sentence in enumerate(sentences):
                    sentence_metadata = {
                        **(metadata or {}),
                        "source_document": source_document,
                        "source_type": "pdf",
                        "ingestion_run_id": run_id,
                        "page_index": page_index,
                        "paragraph_index": paragraph_index,
                        "sentence_index": sentence_index,
                        "chunk_id": f"p{page_index}_pg{paragraph_index}_s{sentence_index}",
                        "fingerprint": fingerprint,
                    }
                    result = self.ingest_texts_with_context(
                        [sentence],
                        source_document=source_document,
                        stage=stage,
                        metadata=sentence_metadata,
                    )
                    triples_added += result.get("triples", 0)
                    candidate_ids.extend(result.get("candidate_ids", []))
                    if result.get("triples", 0) == 0 and result.get("candidates", 0) == 0:
                        skipped += 1
                    sentences_processed += 1

        if skip_if_duplicate:
            self._seen_document_fingerprints.add(fingerprint)

        return {
            "documents": 1,
            "pages": len(pages),
            "sentences": sentences_processed,
            "triples": triples_added,
            "transitions": 0,
            "q_updates": 0,
            "candidates": len(candidate_ids),
            "candidate_ids": candidate_ids,
            "skipped": skipped,
            "failed": 0,
            "ingestion_run_id": run_id,
            "source_document": source_document,
            "fingerprint": fingerprint,
        }

    def ingest_seed_knowledge(self) -> dict:
        """Inject the built-in domain seed knowledge for flood/disaster management.

        Also warm-starts the Q-table with curated transition examples so that
        critical states (crisis, flood+damage, damage+collapse) get non-zero
        Q-values even before any episodes are run.
        """
        return self._ingest({"facts": _DOMAIN_SEED_FACTS, "transitions": _DOMAIN_SEED_TRANSITIONS})

    def ingest_transitions(self, transitions: list[dict]) -> int:
        """Warm-start the Q-table from labeled transition examples.

        Each transition must have:
            state      : list[str]
            action     : str
            reward     : float
            next_state : list[str]

        Returns the number of Q-table updates applied.
        """
        try:
            import main as _main
            from config import ACTIONS, ALPHA, GAMMA
        except ImportError:
            return 0

        updates = 0
        for t in transitions:
            state      = tuple(sorted(t.get("state", [])))
            action     = t.get("action", "none")
            reward     = float(t.get("reward", 0))
            next_state = tuple(sorted(t.get("next_state", [])))

            if action not in ACTIONS:
                continue

            best_future = max(_main.Q.get((next_state, a), 0.0) for a in ACTIONS)
            old_q = _main.Q.get((state, action), 0.0)
            _main.Q[(state, action)] = old_q + ALPHA * (reward + GAMMA * best_future - old_q)
            updates += 1

        return updates

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ingest(self, data: dict) -> dict:
        triples_added    = 0
        transitions_done = 0
        q_updates        = 0

        for fact in data.get("facts", []):
            if self.ingest_triple(fact):
                triples_added += 1

        texts = data.get("texts", [])
        if texts:
            r = self.ingest_texts(texts)
            triples_added += r.get("triples", 0)

        transitions = data.get("transitions", [])
        if transitions:
            q_updates = self.ingest_transitions(transitions)
            transitions_done = len(transitions)

        return {
            "triples":     triples_added,
            "transitions": transitions_done,
            "q_updates":   q_updates,
        }

    def _prepare_fact(self, fact: dict) -> Optional[tuple[tuple[str, str, str], float, dict]]:
        subject    = str(fact.get("subject", "")).strip()
        relation   = str(fact.get("relation", "")).strip()
        obj        = str(fact.get("object", "")).strip()
        confidence = float(fact.get("confidence", 0.8))
        negation   = bool(fact.get("negation", False))

        if not subject or not relation or not obj:
            return None

        if negation:
            relation = relation + "_NOT"

        metadata = {
            k: v for k, v in fact.items()
            if k not in {"subject", "relation", "object", "confidence", "negation"}
        }
        metadata.setdefault("stage", "validated")
        metadata.setdefault("timestamp", time.time())
        return (subject, relation, obj), confidence, metadata

    def ingest_triple(self, fact: dict) -> bool:
        """Validate and inject a single triple dict into TMS and KG."""
        prepared = self._prepare_fact(fact)
        if prepared is None:
            return False
        triple, confidence, metadata = prepared

        if self.tms is not None:
            if not self.tms.resolve_conflict(triple, confidence):
                return False
            self.tms.add_belief(triple, confidence, metadata)

        if self.kg is not None:
            subject, relation, obj = triple
            self.kg.add(subject, relation, obj, confidence, metadata)

        return True

    def ingest_candidate_triple(self, fact: dict) -> Optional[str]:
        prepared = self._prepare_fact({**fact, "stage": "candidate"})
        if prepared is None or self.tms is None:
            return None
        triple, confidence, metadata = prepared
        metadata["stage"] = "candidate"
        return self.tms.add_candidate_belief(triple, confidence, metadata)

    def get_review_queue(self) -> list[dict]:
        if self.tms is None:
            return []
        return self.tms.get_candidate_beliefs(review_status="pending")

    def promote_candidate(self, candidate_id: str) -> bool:
        if self.tms is None:
            return False
        candidate = self.tms.get_candidate_belief(candidate_id)
        if candidate is None or candidate["review_status"] != "pending":
            return False
        if not self.tms.resolve_conflict(candidate["triple"], candidate["confidence"]):
            return False
        promoted = self.tms.promote_candidate_belief(candidate_id)
        if promoted is None:
            return False
        if self.kg is not None:
            s, r, o = promoted["triple"]
            self.kg.add(s, r, o, promoted["confidence"], promoted["provenance"])
        return True

    def reject_candidate(self, candidate_id: str, reason: Optional[str] = None) -> bool:
        if self.tms is None:
            return False
        return self.tms.reject_candidate_belief(candidate_id, reason) is not None


# ---------------------------------------------------------------------------
# Built-in seed knowledge for the flood / disaster-management domain
# ---------------------------------------------------------------------------

_DOMAIN_SEED_FACTS: list[dict] = [
    # Causal escalation chain
    {"subject": "rain",     "relation": "causes",   "object": "flood",    "confidence": 0.90},
    {"subject": "flood",    "relation": "causes",   "object": "damage",   "confidence": 0.75},
    {"subject": "damage",   "relation": "causes",   "object": "collapse", "confidence": 0.60},
    {"subject": "collapse", "relation": "causes",   "object": "crisis",   "confidence": 0.55},
    # Long-range escalation
    {"subject": "flood",    "relation": "leads_to", "object": "crisis",   "confidence": 0.50},
    {"subject": "rain",     "relation": "leads_to", "object": "damage",   "confidence": 0.45},
    # Mitigations
    {"subject": "barrier",  "relation": "prevents", "object": "flood",    "confidence": 0.85},
    {"subject": "barrier",  "relation": "prevents", "object": "damage",   "confidence": 0.70},
    {"subject": "release",  "relation": "reduces",  "object": "flood",    "confidence": 0.65},
    {"subject": "evacuate", "relation": "prevents", "object": "crisis",   "confidence": 0.90},
    {"subject": "evacuate", "relation": "prevents", "object": "collapse", "confidence": 0.80},
    # State classifications
    {"subject": "flood",    "relation": "is",       "object": "risk",      "confidence": 0.95},
    {"subject": "crisis",   "relation": "is",       "object": "high_risk", "confidence": 0.95},
    {"subject": "collapse", "relation": "is",       "object": "danger",    "confidence": 0.90},
    {"subject": "damage",   "relation": "requires", "object": "repair",    "confidence": 0.80},
    # Action prerequisites
    {"subject": "barrier",  "relation": "requires", "object": "flood",    "confidence": 0.80},
    {"subject": "release",  "relation": "requires", "object": "flood",    "confidence": 0.70},
    # Risk amplification
    {"subject": "rain",     "relation": "increases", "object": "flood_risk",    "confidence": 0.85},
    {"subject": "flood",    "relation": "increases", "object": "damage_risk",   "confidence": 0.75},
    {"subject": "collapse", "relation": "increases", "object": "crisis_chance", "confidence": 0.65},
]

# ---------------------------------------------------------------------------
# Built-in Q-table warm-start transitions for critical / under-visited states
# ---------------------------------------------------------------------------

_DOMAIN_SEED_TRANSITIONS: list[dict] = [
    # Critical states that rarely appear during early training episodes
    {"state": ["crisis"],                      "action": "evacuate", "reward": 5.0, "next_state": []},
    {"state": ["crisis", "rain"],              "action": "evacuate", "reward": 5.0, "next_state": []},
    {"state": ["crisis", "collapse"],          "action": "evacuate", "reward": 5.0, "next_state": ["evacuated"]},
    {"state": ["crisis", "collapse", "flood"], "action": "evacuate", "reward": 5.0, "next_state": ["evacuated"]},
    # Compound threat states
    {"state": ["damage", "flood"],             "action": "barrier",  "reward": 3.0, "next_state": ["damage"]},
    {"state": ["damage", "flood", "rain"],     "action": "barrier",  "reward": 3.0, "next_state": ["rain"]},
    {"state": ["collapse", "damage"],          "action": "evacuate", "reward": 4.0, "next_state": ["evacuated"]},
    {"state": ["collapse", "damage", "flood"], "action": "evacuate", "reward": 5.0, "next_state": ["evacuated"]},
    # Rare 4-way compound state: all major threats simultaneously
    {"state": ["collapse", "crisis", "damage", "flood"], "action": "evacuate", "reward": 6.0, "next_state": []},
    # 3-way subsets not yet covered
    {"state": ["collapse", "crisis", "damage"],          "action": "evacuate", "reward": 5.5, "next_state": []},
    {"state": ["collapse", "crisis", "flood"],           "action": "evacuate", "reward": 5.5, "next_state": []},
    {"state": ["crisis",   "damage",  "flood"],          "action": "evacuate", "reward": 5.0, "next_state": []},
    # Safe baseline
    {"state": [],                              "action": "none",     "reward": 1.2, "next_state": []},
    {"state": ["evacuated"],                   "action": "none",     "reward": 1.2, "next_state": []},
]
