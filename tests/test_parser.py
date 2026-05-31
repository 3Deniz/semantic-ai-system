import unittest

from core.parser import SemanticParser


class SemanticParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = SemanticParser()

    # ------------------------------------------------------------------
    # Existing contracts (must not regress)
    # ------------------------------------------------------------------

    def test_parse_normalizes_and_extracts_confidence(self):
        triples = self.parser.parse("Cats are animals 0.9")

        self.assertEqual(len(triples), 1)
        triple = triples[0]
        self.assertEqual(triple["subject"], "cat")
        self.assertEqual(triple["relation"], "is")
        self.assertEqual(triple["object"], "animal")
        self.assertAlmostEqual(triple["confidence"], 0.9)

    def test_parse_marks_negation(self):
        triples = self.parser.parse("Cats are not animals 0.8")

        self.assertEqual(len(triples), 1)
        self.assertTrue(triples[0]["negation"])

    # ------------------------------------------------------------------
    # New relation-verb vocabulary
    # ------------------------------------------------------------------

    def test_causes_relation(self):
        triples = self.parser.parse("rain causes flood 0.9")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["subject"],  "rain")
        self.assertEqual(triples[0]["relation"], "causes")
        self.assertEqual(triples[0]["object"],   "flood")
        self.assertAlmostEqual(triples[0]["confidence"], 0.9)

    def test_prevents_relation(self):
        triples = self.parser.parse("barrier prevents flood")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["relation"], "prevents")

    def test_leads_to_relation(self):
        triples = self.parser.parse("flood leads to damage 0.75")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["relation"], "leads_to")
        self.assertEqual(triples[0]["object"],   "damage")

    def test_reduces_relation(self):
        triples = self.parser.parse("release reduces flood")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["relation"], "reduces")

    def test_requires_relation(self):
        triples = self.parser.parse("barrier requires flood")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["relation"], "requires")

    def test_improves_relation_maps_to_increases(self):
        triples = self.parser.parse("attention improves performance")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["relation"], "increases")

    def test_enhances_relation_maps_to_increases(self):
        triples = self.parser.parse("focus enhances results")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["relation"], "increases")

    def test_dependency_based_on_pattern(self):
        triples = self.parser.parse("model is based on attention")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["relation"], "depends_on")

    def test_dependency_uses_pattern(self):
        triples = self.parser.parse("encoder uses memory and context")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["relation"], "uses")
        self.assertEqual(len(triples), 2)

    def test_dependency_contains_pattern(self):
        triples = self.parser.parse("transformer consists of layers")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["relation"], "contains")

    # ------------------------------------------------------------------
    # Compound objects
    # ------------------------------------------------------------------

    def test_compound_object(self):
        triples = self.parser.parse("flood causes damage and collapse 0.8")
        self.assertIsNotNone(triples)
        self.assertEqual(len(triples), 2)
        objects = {t["object"] for t in triples}
        self.assertIn("damage",   objects)
        self.assertIn("collapse", objects)

    # ------------------------------------------------------------------
    # Structured patterns
    # ------------------------------------------------------------------

    def test_if_then_pattern(self):
        triples = self.parser.parse("if flood then barrier")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["subject"],  "flood")
        self.assertEqual(triples[0]["relation"], "implies")
        self.assertEqual(triples[0]["object"],   "barrier")

    def test_when_pattern(self):
        triples = self.parser.parse("when crisis, evacuate")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["subject"],  "crisis")
        self.assertEqual(triples[0]["relation"], "implies")

    def test_arrow_pattern(self):
        triples = self.parser.parse("rain → flood")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["relation"], "leads_to")

    def test_chained_arrow_produces_multiple_triples(self):
        """rain → flood → crisis should yield two triples."""
        triples = self.parser.parse("rain → flood → crisis")
        self.assertIsNotNone(triples)
        self.assertEqual(len(triples), 2)
        self.assertEqual(triples[0]["subject"], "rain")
        self.assertEqual(triples[0]["object"],  "flood")
        self.assertEqual(triples[1]["subject"], "flood")
        self.assertEqual(triples[1]["object"],  "crisis")

    def test_does_not_negation_strips_auxiliary(self):
        """'barrier does not cause crisis' must not leave 'doe' in subject."""
        triples = self.parser.parse("barrier does not cause crisis")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["subject"],  "barrier")
        self.assertTrue(triples[0]["negation"])

    def test_trailing_confidence_qualifier_stripped(self):
        """'flood causes crisis 0.95 high' should parse with conf=0.95, obj='crisis'."""
        triples = self.parser.parse("flood causes crisis 0.95 high")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["object"],     "crisis")
        self.assertAlmostEqual(triples[0]["confidence"], 0.95)

    def test_parse_attaches_provenance_context(self):
        triples = self.parser.parse(
            "rain causes flood 0.9",
            context={"source_document": "encyclopedia", "paragraph_index": 2},
        )
        self.assertEqual(triples[0]["source_document"], "encyclopedia")
        self.assertEqual(triples[0]["paragraph_index"], 2)
        self.assertEqual(triples[0]["source_text"], "rain causes flood 0.9")
        self.assertEqual(triples[0]["extraction_method"], "rule_based_free_text")

    # ------------------------------------------------------------------
    # parse_bulk
    # ------------------------------------------------------------------

    def test_parse_bulk(self):
        statements = [
            "rain causes flood 0.9",
            "barrier prevents flood 0.85",
            "flood causes damage and collapse 0.75",
        ]
        triples = self.parser.parse_bulk(statements)
        # 1 + 1 + 2 = 4 triples
        self.assertEqual(len(triples), 4)

    def test_parse_bulk_skips_unparseable(self):
        statements = ["", "???", "rain causes flood 0.9"]
        triples = self.parser.parse_bulk(statements)
        self.assertEqual(len(triples), 1)

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_returns_none_for_empty_string(self):
        self.assertIsNone(self.parser.parse(""))

    def test_default_confidence(self):
        triples = self.parser.parse("flood causes damage")
        self.assertAlmostEqual(triples[0]["confidence"], 0.8)

    def test_trailing_numeric_object_is_not_treated_as_confidence(self):
        triples = self.parser.parse("2_plus_3 is 5")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["subject"], "2_plus_3")
        self.assertEqual(triples[0]["relation"], "is")
        self.assertEqual(triples[0]["object"], "5")
        self.assertAlmostEqual(triples[0]["confidence"], 0.8)

    def test_spacy_path_can_be_selected_when_enabled(self):
        parser = SemanticParser(enable_spacy_dep=True)

        def _fake_spacy(_text, _confidence):
            return [{
                "subject": "model",
                "relation": "depends_on",
                "object": "attention",
                "negation": False,
                "confidence": 0.8,
            }]

        parser._parse_spacy_dependency = _fake_spacy
        triples = parser.parse("random text")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["relation"], "depends_on")
        self.assertEqual(triples[0]["extraction_method"], "spacy_dependency")

    def test_spacy_fallback_to_rule_based_when_unavailable(self):
        parser = SemanticParser(enable_spacy_dep=True)
        parser._spacy_checked = True
        parser._spacy_nlp = None
        triples = parser.parse("rain causes flood")
        self.assertIsNotNone(triples)
        self.assertEqual(triples[0]["relation"], "causes")


if __name__ == "__main__":
    unittest.main()