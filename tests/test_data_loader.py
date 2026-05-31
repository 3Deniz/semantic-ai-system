"""Integration tests for core/data_loader.py."""

import json
import os
import tempfile
import unittest

from core.data_loader import DataLoader, _DOMAIN_SEED_FACTS, _DOMAIN_SEED_TRANSITIONS
from core.knowledge_graph import KnowledgeGraph
from core.tms import LiteTMS


class _FakePDFIngestion:
    def __init__(self, pages):
        self._pages = pages

    def extract_pages_from_bytes(self, _pdf_bytes):
        return list(self._pages)


def _make_loader():
    tms = LiteTMS()
    kg = KnowledgeGraph()
    return DataLoader(tms=tms, kg=kg), tms, kg


class TestDataLoaderIngestTriple(unittest.TestCase):
    def setUp(self):
        self.loader, self.tms, self.kg = _make_loader()

    def test_valid_triple_added_to_kg(self):
        fact = {"subject": "rain", "relation": "causes", "object": "flood", "confidence": 0.9}
        result = self.loader.ingest_triple(fact)
        self.assertTrue(result)
        self.assertEqual(len(self.kg.triples), 1)

    def test_negated_triple_uses_not_suffix(self):
        fact = {"subject": "barrier", "relation": "causes", "object": "flood", "confidence": 0.8, "negation": True}
        self.loader.ingest_triple(fact)
        relations = [r for (_, r, _, _) in self.kg.triples]
        self.assertIn("causes_NOT", relations)

    def test_missing_fields_returns_false(self):
        self.assertFalse(self.loader.ingest_triple({"subject": "rain"}))
        self.assertFalse(self.loader.ingest_triple({}))

    def test_default_confidence(self):
        fact = {"subject": "flood", "relation": "causes", "object": "damage"}
        self.loader.ingest_triple(fact)
        for (_, _, _, conf) in self.kg.triples:
            self.assertAlmostEqual(conf, 0.8)


class TestDataLoaderIngestTexts(unittest.TestCase):
    def setUp(self):
        self.loader, self.tms, self.kg = _make_loader()

    def test_single_parseable_sentence(self):
        result = self.loader.ingest_texts(["rain causes flood 0.9"])
        self.assertGreaterEqual(result["triples"], 1)
        self.assertEqual(result["transitions"], 0)

    def test_unparseable_sentences_skipped(self):
        result = self.loader.ingest_texts(["", "???", "rain causes flood"])
        self.assertGreaterEqual(result["triples"], 1)  # at least the last one

    def test_multiple_sentences(self):
        sentences = [
            "rain causes flood 0.9",
            "flood causes damage 0.75",
            "barrier prevents flood",
        ]
        result = self.loader.ingest_texts(sentences)
        self.assertGreaterEqual(result["triples"], 3)

    def test_candidate_texts_are_staged_without_touching_kg(self):
        result = self.loader.ingest_texts_with_context(
            ["rain causes flood 0.9"],
            source_document="doc-1",
            stage="candidate",
        )
        self.assertEqual(result["triples"], 0)
        self.assertEqual(result["candidates"], 1)
        self.assertEqual(len(self.kg.triples), 0)
        self.assertEqual(len(self.tms.get_candidate_beliefs("pending")), 1)


class TestDataLoaderCandidateWorkflow(unittest.TestCase):
    def setUp(self):
        self.loader, self.tms, self.kg = _make_loader()

    def test_promote_candidate_adds_triple_to_kg(self):
        candidate_id = self.loader.ingest_candidate_triple({
            "subject": "rain",
            "relation": "causes",
            "object": "flood",
            "confidence": 0.9,
            "source_document": "doc-2",
        })
        self.assertTrue(self.loader.promote_candidate(candidate_id))
        self.assertEqual(len(self.kg.triples), 1)
        self.assertEqual(self.tms.get_candidate_belief(candidate_id)["review_status"], "approved")
        metadata = self.kg.get_metadata("rain", "causes", "flood")
        self.assertEqual(metadata["source_document"], "doc-2")

    def test_reject_candidate_marks_review_status(self):
        candidate_id = self.loader.ingest_candidate_triple({
            "subject": "rain",
            "relation": "causes",
            "object": "flood",
        })
        self.assertTrue(self.loader.reject_candidate(candidate_id, "duplicate"))
        candidate = self.tms.get_candidate_belief(candidate_id)
        self.assertEqual(candidate["review_status"], "rejected")
        self.assertEqual(candidate["provenance"]["review_reason"], "duplicate")

    def test_ingest_document_tracks_sentence_positions(self):
        result = self.loader.ingest_document(
            "Rain causes flood. Flood causes damage.",
            source_document="doc-3",
            stage="candidate",
        )
        self.assertEqual(result["documents"], 1)
        self.assertEqual(result["candidates"], 2)
        candidates = self.tms.get_candidate_beliefs("pending")
        self.assertEqual(candidates[0]["provenance"]["source_document"], "doc-3")
        self.assertIn("sentence_index", candidates[0]["provenance"])


class TestDataLoaderPdfIngestion(unittest.TestCase):
    def setUp(self):
        pages = [
            {"page_index": 0, "text": "Rain causes flood. Flood causes damage."},
            {"page_index": 1, "text": "Barrier prevents flood."},
        ]
        self.loader, self.tms, self.kg = _make_loader()
        self.loader.pdf_ingestion = _FakePDFIngestion(pages)

    def test_ingest_pdf_document_creates_candidates_with_pdf_provenance(self):
        result = self.loader.ingest_pdf_document(
            b"fake-pdf",
            source_document="doc.pdf",
            stage="candidate",
        )
        self.assertEqual(result["documents"], 1)
        self.assertEqual(result["pages"], 2)
        self.assertGreaterEqual(result["candidates"], 3)

        candidates = self.tms.get_candidate_beliefs("pending")
        self.assertGreaterEqual(len(candidates), 3)
        provenance = candidates[0]["provenance"]
        self.assertEqual(provenance["source_type"], "pdf")
        self.assertEqual(provenance["source_document"], "doc.pdf")
        self.assertIn("page_index", provenance)
        self.assertIn("paragraph_index", provenance)
        self.assertIn("sentence_index", provenance)
        self.assertIn("chunk_id", provenance)
        self.assertIn("ingestion_run_id", provenance)

    def test_ingest_pdf_document_skips_duplicate_fingerprint(self):
        first = self.loader.ingest_pdf_document(b"same-pdf", source_document="dup.pdf", stage="candidate")
        second = self.loader.ingest_pdf_document(b"same-pdf", source_document="dup.pdf", stage="candidate")
        self.assertEqual(first["documents"], 1)
        self.assertEqual(second["documents"], 0)
        self.assertEqual(second["skipped"], 1)


class TestDataLoaderIngestSeedKnowledge(unittest.TestCase):
    def setUp(self):
        self.loader, self.tms, self.kg = _make_loader()

    def test_seed_injects_all_facts(self):
        result = self.loader.ingest_seed_knowledge()
        self.assertEqual(result["triples"], len(_DOMAIN_SEED_FACTS))

    def test_kg_populated_after_seed(self):
        self.loader.ingest_seed_knowledge()
        self.assertGreater(len(self.kg.triples), 0)


class TestDataLoaderLoadFile(unittest.TestCase):
    def setUp(self):
        self.loader, self.tms, self.kg = _make_loader()

    def test_load_json_file(self):
        data = {
            "facts": [
                {"subject": "rain", "relation": "causes", "object": "flood", "confidence": 0.9}
            ]
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            result = self.loader.load_file(path)
            self.assertEqual(result["triples"], 1)
        finally:
            os.unlink(path)

    def test_load_jsonl_file(self):
        lines = [
            '{"subject":"flood","relation":"causes","object":"damage","confidence":0.75}\n',
            '{"subject":"damage","relation":"causes","object":"collapse","confidence":0.6}\n',
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.writelines(lines)
            path = f.name
        try:
            result = self.loader.load_file(path)
            self.assertEqual(result["triples"], 2)
        finally:
            os.unlink(path)

    def test_load_csv_file(self):
        content = "subject,relation,object,confidence\nrain,causes,flood,0.9\nflood,causes,damage,0.75\n"
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            result = self.loader.load_file(path)
            self.assertEqual(result["triples"], 2)
        finally:
            os.unlink(path)

    def test_load_txt_file(self):
        content = "# comment\nrain causes flood 0.9\nbarrier prevents flood\n"
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            result = self.loader.load_file(path)
            self.assertGreaterEqual(result["triples"], 2)
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.loader.load_file("/nonexistent/path/data.json")

    def test_unsupported_extension_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            path = f.name
        try:
            with self.assertRaises(ValueError):
                self.loader.load_file(path)
        finally:
            os.unlink(path)


class TestDataLoaderCompoundSeedTransitions(unittest.TestCase):
    """Verify the new compound-state seed transitions are present."""

    def _state_key(self, state_list):
        return tuple(sorted(state_list))

    def test_four_way_compound_transition_present(self):
        keys = {self._state_key(t["state"]) for t in _DOMAIN_SEED_TRANSITIONS}
        self.assertIn(self._state_key(["collapse", "crisis", "damage", "flood"]), keys)

    def test_three_way_collapse_crisis_damage_present(self):
        keys = {self._state_key(t["state"]) for t in _DOMAIN_SEED_TRANSITIONS}
        self.assertIn(self._state_key(["collapse", "crisis", "damage"]), keys)

    def test_three_way_collapse_crisis_flood_present(self):
        keys = {self._state_key(t["state"]) for t in _DOMAIN_SEED_TRANSITIONS}
        self.assertIn(self._state_key(["collapse", "crisis", "flood"]), keys)

    def test_three_way_crisis_damage_flood_present(self):
        keys = {self._state_key(t["state"]) for t in _DOMAIN_SEED_TRANSITIONS}
        self.assertIn(self._state_key(["crisis", "damage", "flood"]), keys)

    def test_compound_transitions_recommend_evacuate(self):
        for t in _DOMAIN_SEED_TRANSITIONS:
            state_key = self._state_key(t["state"])
            if "crisis" in t["state"] and len(t["state"]) >= 3:
                self.assertEqual(t["action"], "evacuate",
                                 f"Expected evacuate for state {t['state']}")


if __name__ == "__main__":
    unittest.main()
