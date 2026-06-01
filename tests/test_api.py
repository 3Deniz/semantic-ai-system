"""Integration tests for api.py endpoints.

Uses FastAPI's TestClient (backed by httpx) to exercise each endpoint without
starting a real server.  The lifespan hook (RL training, JEPA warm-start, KG
load) is intentionally **not** triggered here — tests import the ``app``
object after monkey-patching the global singletons to avoid the 5 000-episode
RL training cost and file I/O side-effects.
"""

import os
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

# ---------------------------------------------------------------------------
# Patch heavy startup dependencies BEFORE importing api
# ---------------------------------------------------------------------------

# Prevent real RL training in main.train()
_mock_main = MagicMock()
_mock_main.Q = defaultdict(float)
_mock_main.policy_counter = {}
_mock_main.get_key = lambda state: tuple(sorted(state)) if not isinstance(state, str) else state
sys.modules.setdefault("main", _mock_main)

import api  # noqa: E402  — must come after mock injection
from fastapi.testclient import TestClient  # noqa: E402

# Replace the module-level singletons with lightweight real instances so that
# endpoints exercise actual logic without touching disk or trained weights.
from core.knowledge_graph import KnowledgeGraph  # noqa: E402
from core.tms import LiteTMS  # noqa: E402
from core.parser import SemanticParser  # noqa: E402
from core.data_loader import DataLoader  # noqa: E402
from memory.concept_space_embeddings import ConceptSpaceEmbeddings  # noqa: E402
from learning.jepa import JEPAModel  # noqa: E402
from cognition.thought_loop import ThoughtLoop  # noqa: E402
from config import ACTIONS  # noqa: E402


def _make_client():
    """Build a TestClient without triggering the lifespan startup hook."""
    # Wire fresh singletons
    api._kg = KnowledgeGraph()
    api._tms = LiteTMS()
    api._parser = SemanticParser()
    api._jepa = JEPAModel()

    def _fake_simulate(state, action):
        s = set(state) if not isinstance(state, str) else set()
        reward = 4.0 if action == "barrier" else 0.0
        return reward, tuple(sorted(s))

    api._thought_loop = ThoughtLoop(
        _mock_main, api._jepa, _fake_simulate, _mock_main.Q, ACTIONS
    )
    temp_root = Path(tempfile.mkdtemp())
    api._concept_space_embeddings = ConceptSpaceEmbeddings(temp_root / "concept_space_embeddings.json")
    api._data_loader = None  # reset lazy loader so it picks up fresh kg/tms
    return TestClient(api.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestRootEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_root_returns_200(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)

    def test_root_has_status_key(self):
        r = self.client.get("/")
        self.assertIn("status", r.json())


class TestMetricsEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_metrics_returns_200(self):
        r = self.client.get("/metrics")
        self.assertEqual(r.status_code, 200)

    def test_metrics_has_required_keys(self):
        data = self.client.get("/metrics").json()
        for key in ("nodes", "edges", "inference", "cycles", "conflicts",
                    "jepa_trained", "jepa_samples", "kg_edges"):
            self.assertIn(key, data, f"Missing key: {key}")

    def test_metrics_jepa_trained_is_bool(self):
        data = self.client.get("/metrics").json()
        self.assertIsInstance(data["jepa_trained"], bool)

    def test_metrics_kg_edges_reflects_kg(self):
        api._kg.add("flood", "causes", "damage", 0.9)
        data = self.client.get("/metrics").json()
        self.assertGreaterEqual(data["kg_edges"], 1)


class TestGraphEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_graph_returns_200(self):
        r = self.client.get("/graph")
        self.assertEqual(r.status_code, 200)

    def test_graph_has_nodes_and_edges(self):
        data = self.client.get("/graph").json()
        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        self.assertIsInstance(data["nodes"], list)
        self.assertIsInstance(data["edges"], list)


class TestExplainEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_explain_flood_state(self):
        r = self.client.get("/explain", params={"state": "flood"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("explanation", data)
        self.assertIn("best_action", data)

    def test_explain_missing_state_returns_422(self):
        r = self.client.get("/explain")
        self.assertEqual(r.status_code, 422)

    def test_explain_state_too_long_returns_422(self):
        r = self.client.get("/explain", params={"state": "x" * 501})
        self.assertEqual(r.status_code, 422)


class TestDecisionEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_decision_returns_200(self):
        r = self.client.post("/decision", json={"state": "flood"})
        self.assertEqual(r.status_code, 200)

    def test_decision_has_action_and_scores(self):
        data = self.client.post("/decision", json={"state": "flood"}).json()
        self.assertIn("action", data)
        self.assertIn("scores", data)

    def test_decision_action_is_valid(self):
        data = self.client.post("/decision", json={"state": "flood"}).json()
        self.assertIn(data["action"], ACTIONS)

    def test_decision_requires_state_field(self):
        r = self.client.post("/decision", json={})
        self.assertEqual(r.status_code, 422)


class TestLoopHealthEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_loop_health_returns_200(self):
        r = self.client.get("/loop/health")
        self.assertEqual(r.status_code, 200)

    def test_decision_generates_thought_and_visual_artifacts(self):
        self.client.post("/decision", json={"state": "flood"})
        data = self.client.get("/loop/health").json()
        self.assertGreaterEqual(data["count"], 1)
        latest = data.get("latest") or {}
        self.assertTrue(latest.get("thought_generated"))
        self.assertTrue(latest.get("visualization_generated"))


class TestSimulateEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_simulate_returns_200(self):
        r = self.client.post("/simulate", json={"state": "flood", "steps": 3})
        self.assertEqual(r.status_code, 200)

    def test_simulate_trajectory_length_capped(self):
        data = self.client.post("/simulate", json={"state": "flood", "steps": 200}).json()
        self.assertLessEqual(data["steps"], api.MAX_SIMULATE_STEPS)

    def test_simulate_trajectory_has_expected_fields(self):
        data = self.client.post("/simulate", json={"state": "flood", "steps": 2}).json()
        for step in data["trajectory"]:
            self.assertIn("state", step)
            self.assertIn("action", step)
            self.assertIn("reward", step)
            self.assertIn("next_state", step)


class TestThinkEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_think_returns_200(self):
        r = self.client.post("/think", json={"state": "flood"})
        self.assertEqual(r.status_code, 200)

    def test_think_response_has_action(self):
        data = self.client.post("/think", json={"state": "flood"}).json()
        self.assertIn("action", data)
        self.assertIn(data["action"], ACTIONS)

    def test_think_response_has_thought_path(self):
        data = self.client.post("/think", json={"state": "flood"}).json()
        self.assertIn("thought_path", data)
        self.assertIsInstance(data["thought_path"], list)
        self.assertGreater(len(data["thought_path"]), 0)

    def test_thought_path_stages_have_expected_keys(self):
        data = self.client.post("/think", json={"state": "flood"}).json()
        for step in data["thought_path"]:
            self.assertIn("stage", step)
            self.assertIn("detail", step)


class TestThoughtTraceEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_thought_trace_returns_200(self):
        # run at least one think call to populate traces
        self.client.post("/think", json={"state": "flood"})
        r = self.client.get("/thought_trace")
        self.assertEqual(r.status_code, 200)

    def test_thought_trace_has_traces_key(self):
        self.client.post("/think", json={"state": "flood"})
        data = self.client.get("/thought_trace").json()
        self.assertIn("traces", data)

    def test_thought_trace_n_limit_respected(self):
        for _ in range(5):
            self.client.post("/think", json={"state": "flood"})
        data = self.client.get("/thought_trace", params={"n": 3}).json()
        self.assertLessEqual(len(data["traces"]), 3)


class TestSemanticAssertEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_assert_triple_returns_ok(self):
        r = self.client.post("/semantic/assert", json={
            "subject": "rain", "relation": "causes", "obj": "flood", "confidence": 0.9
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("ok"))

    def test_asserted_triple_appears_in_kg(self):
        self.client.post("/semantic/assert", json={
            "subject": "rain", "relation": "causes", "obj": "flood", "confidence": 0.9
        })
        self.assertGreaterEqual(len(api._kg.triples), 1)


class TestSemanticBeliefsEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_beliefs_returns_200(self):
        r = self.client.get("/semantic/beliefs")
        self.assertEqual(r.status_code, 200)

    def test_beliefs_has_count_key(self):
        data = self.client.get("/semantic/beliefs").json()
        self.assertIn("count", data)

    def test_asserted_belief_appears(self):
        self.client.post("/semantic/assert", json={
            "subject": "flood", "relation": "causes", "obj": "damage", "confidence": 0.8
        })
        data = self.client.get("/semantic/beliefs").json()
        self.assertGreaterEqual(data["count"], 1)


class TestSemanticInferEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_infer_returns_200(self):
        r = self.client.post("/semantic/infer")
        self.assertEqual(r.status_code, 200)

    def test_infer_returns_new_triples_count(self):
        # Seed two transitive triples then infer
        api._kg.add("A", "is", "B", 1.0)
        api._kg.add("B", "is", "C", 1.0)
        data = self.client.post("/semantic/infer").json()
        self.assertIn("new_triples", data)
        self.assertGreaterEqual(data["new_triples"], 0)


class TestSemanticConceptsEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_concepts_returns_200(self):
        r = self.client.get("/semantic/concepts")
        self.assertEqual(r.status_code, 200)

    def test_concepts_has_concepts_key(self):
        data = self.client.get("/semantic/concepts").json()
        self.assertIn("concepts", data)


class TestSemanticRelationsEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_relations_requires_query_or_state(self):
        r = self.client.get("/semantic/relations")
        self.assertEqual(r.status_code, 400)

    def test_relations_with_query_returns_200(self):
        api._kg.add("rain", "causes", "flood", 0.9, {"source_document": "doc.pdf"})
        r = self.client.get("/semantic/relations", params={"query": "flood"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        self.assertTrue(any(edge.get("space") == "semantic" for edge in data["edges"]))

    def test_relations_include_spaces_filter(self):
        r = self.client.get(
            "/semantic/relations",
            params={"query": "flood", "include_spaces": "risk,goal"},
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(set(data["spaces"]), {"risk", "goal"})


class TestSemanticSearchAndRecallEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def _teach_numeracy(self):
        r = self.client.post("/learn/numeracy/basic")
        self.assertEqual(r.status_code, 200)

    def _teach_calculus_phase(self):
        self._teach_numeracy()
        r = self.client.post("/learn/curriculum/phase/calculus")
        self.assertEqual(r.status_code, 200)

    def _teach_logarithm_phase(self):
        self._teach_calculus_phase()
        r = self.client.post("/learn/curriculum/phase/logarithms")
        self.assertEqual(r.status_code, 200)

    def _teach_economy_foundations(self):
        r = self.client.post("/learn/curriculum/economy/phase/foundations")
        self.assertEqual(r.status_code, 200)

    def test_semantic_search_returns_200(self):
        api._kg.add("rain", "causes", "flood", 0.9, {"source_type": "pdf", "source_document": "doc.pdf"})
        r = self.client.get("/semantic/search", params={"query": "flood"})
        self.assertEqual(r.status_code, 200)

    def test_semantic_search_has_scored_facts(self):
        api._kg.add("flood", "causes", "damage", 0.8, {"source_type": "pdf", "source_document": "doc.pdf"})
        data = self.client.get("/semantic/search", params={"query": "flood"}).json()
        self.assertIn("facts", data)
        self.assertGreaterEqual(data["count"], 1)
        first = data["facts"][0]
        self.assertIn("score", first)
        self.assertIn("ranking", first)
        self.assertIn("source_quality", first["ranking"])

    def test_semantic_recall_returns_facts_and_relations_graph(self):
        api._kg.add("rain", "causes", "flood", 0.9, {"source_type": "pdf", "source_document": "doc.pdf"})
        r = self.client.get("/semantic/recall", params={"query": "flood"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("facts", data)
        self.assertIn("relations_graph", data)
        self.assertIn("nodes", data["relations_graph"])
        self.assertIn("edges", data["relations_graph"])

    def test_semantic_recall_supports_space_filter(self):
        r = self.client.get(
            "/semantic/recall",
            params={"query": "flood", "include_spaces": "semantic,risk"},
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(set(data["relations_graph"]["spaces"]), {"semantic", "risk"})

    def test_semantic_recall_can_expand_graph_with_fact_entities(self):
        api._kg.add("attention", "causes", "focus", 0.9, {"source_type": "pdf"})
        api._kg.add("focus", "leads_to", "performance", 0.8, {"source_type": "pdf"})
        api._kg.add("performance", "improves", "results", 0.7, {"source_type": "pdf"})

        base = self.client.get(
            "/semantic/recall",
            params={"query": "attention", "include_spaces": "semantic", "expand_with_facts": "false"},
        ).json()
        expanded = self.client.get(
            "/semantic/recall",
            params={"query": "attention", "include_spaces": "semantic", "expand_with_facts": "true"},
        ).json()

        self.assertGreaterEqual(len(expanded["relations_graph"].get("edges", [])), len(base["relations_graph"].get("edges", [])))

    def test_semantic_search_supports_arithmetic_queries(self):
        self._teach_numeracy()
        api._kg.add("2_plus_3", "be", "5", 0.95, {"source_type": "pdf", "source_document": "math.pdf"})
        data = self.client.get("/semantic/search", params={"query": "2+3"}).json()
        self.assertGreaterEqual(data.get("count", 0), 1)
        top = data.get("facts", [])[0]
        self.assertEqual(top.get("triple", [None])[0], "plus_2_3")

    def test_semantic_search_blocks_arithmetic_without_foundation(self):
        data = self.client.get("/semantic/search", params={"query": "2+3", "limit": 3}).json()
        self.assertGreaterEqual(data.get("count", 0), 1)
        top = data.get("facts", [])[0]
        self.assertEqual(top.get("triple", ["", "", ""])[1], "requires_learning")

    def test_semantic_search_unknown_turkish_concept_returns_no_facts(self):
        api._kg.add("tv", "used_for", "eglence", 0.95, {"source_type": "pdf", "source_document": "media.pdf"})

        unknown = self.client.get("/semantic/search", params={"query": "elektromanyetik dalga"}).json()
        known = self.client.get("/semantic/search", params={"query": "tv"}).json()

        self.assertEqual(unknown.get("count", 0), 0)
        self.assertGreaterEqual(known.get("count", 0), 1)
        self.assertFalse(bool(unknown.get("policy", {}).get("should_answer", True)))
        self.assertTrue(bool(known.get("policy", {}).get("should_answer", False)))

    def test_semantic_search_rejects_tokenless_unknown_query(self):
        data = self.client.get("/semantic/search", params={"query": "???!!!", "limit": 3}).json()
        self.assertEqual(data.get("count", 0), 0)
        self.assertEqual(data.get("policy", {}).get("reason"), "no_lexical_tokens")

    def test_semantic_recall_includes_arithmetic_space_edges(self):
        self._teach_numeracy()
        data = self.client.get(
            "/semantic/recall",
            params={"query": "7-4", "include_spaces": "arithmetic"},
        ).json()
        graph = data.get("relations_graph", {})
        self.assertEqual(set(graph.get("spaces", [])), {"arithmetic"})
        self.assertTrue(any(edge.get("space") == "arithmetic" for edge in graph.get("edges", [])))
        self.assertTrue(any(edge.get("relation_type") == "equals" for edge in graph.get("edges", [])))

    def test_semantic_search_supports_multiplication_and_division_queries(self):
        self._teach_numeracy()
        times = self.client.get("/semantic/search", params={"query": "6*7", "limit": 3}).json()
        divide = self.client.get("/semantic/search", params={"query": "20/5", "limit": 3}).json()

        self.assertGreaterEqual(times.get("count", 0), 1)
        self.assertGreaterEqual(divide.get("count", 0), 1)
        self.assertEqual(times["facts"][0]["triple"], ["multiply_6_7", "equals", "42"])
        self.assertEqual(divide["facts"][0]["triple"], ["divide_20_5", "equals", "4"])

    def test_semantic_recall_contains_arithmetic_space_for_multiplication(self):
        self._teach_numeracy()
        data = self.client.get(
            "/semantic/recall",
            params={"query": "9x8", "include_spaces": "arithmetic", "max_edges": 100},
        ).json()
        graph = data.get("relations_graph", {})
        self.assertTrue(any(edge.get("space") == "arithmetic" for edge in graph.get("edges", [])))
        self.assertTrue(any(edge.get("relation_type") == "models_expression" for edge in graph.get("edges", [])))

    def test_semantic_search_supports_multi_step_and_parentheses(self):
        self._teach_numeracy()
        chain = self.client.get("/semantic/search", params={"query": "2+3-1", "limit": 3}).json()
        paren = self.client.get("/semantic/search", params={"query": "(2+3)*4", "limit": 3}).json()

        self.assertEqual(chain["facts"][0]["triple"], ["minus_plus_2_3_1", "equals", "4"])
        self.assertEqual(paren["facts"][0]["triple"], ["multiply_plus_2_3_4", "equals", "20"])

    def test_semantic_search_returns_carry_trace_for_addition(self):
        self._teach_numeracy()
        data = self.client.get("/semantic/search", params={"query": "44+17", "limit": 3}).json()
        top = data["facts"][0]
        self.assertEqual(top["triple"], ["plus_44_17", "equals", "61"])
        trace = top.get("provenance", {}).get("solution_trace", [])
        self.assertTrue(any("carry" in str(step).lower() for step in trace))

    def test_semantic_search_supports_derivative_and_integral(self):
        self._teach_calculus_phase()
        derivative = self.client.get("/semantic/search", params={"query": "d/dx x^3 + 2*x", "limit": 3}).json()
        integral = self.client.get("/semantic/search", params={"query": "integral 2*x dx", "limit": 3}).json()

        self.assertEqual(derivative["facts"][0]["triple"], ["x^3 + 2*x", "derivative", "3*x^2 + 2"])
        self.assertEqual(integral["facts"][0]["triple"], ["2*x", "integral", "x^2 + C"])
        self.assertIn("solution_trace", derivative["facts"][0]["provenance"])

    def test_semantic_search_supports_detailed_integral_trace(self):
        self._teach_calculus_phase()
        data = self.client.get(
            "/semantic/search",
            params={"query": "integral 6*x^5 - 3*x^3 + 8*x - 11 dx", "limit": 3},
        ).json()
        top = data["facts"][0]
        self.assertEqual(top["triple"], ["6*x^5 - 3*x^3 + 8*x - 11", "integral", "x^6 - 0.75*x^4 + 4*x^2 - 11*x + C"])
        trace = top["provenance"].get("solution_trace", [])
        self.assertGreaterEqual(len(trace), 6)
        self.assertTrue(any("Term 1" in step for step in trace))
        self.assertTrue(any("Term 4" in step for step in trace))

    def test_semantic_search_supports_variable_specific_derivative(self):
        self._teach_calculus_phase()
        derivative_y = self.client.get(
            "/semantic/search",
            params={"query": "d/dy y^2 + 3*y", "limit": 3},
        ).json()
        top = derivative_y["facts"][0]
        self.assertEqual(top["triple"], ["y^2 + 3*y", "derivative", "2*y + 3"])
        self.assertEqual(top["provenance"].get("variable"), "y")

    def test_semantic_search_supports_trig_and_exponential_rules(self):
        self._teach_calculus_phase()
        trig = self.client.get("/semantic/search", params={"query": "d/dx sin(x)", "limit": 3}).json()
        expo = self.client.get("/semantic/search", params={"query": "integral exp(x) dx", "limit": 3}).json()

        self.assertEqual(trig["facts"][0]["triple"], ["sin(x)", "derivative", "cos(x)"])
        self.assertEqual(expo["facts"][0]["triple"], ["exp(x)", "integral", "exp(x) + C"])

    def test_semantic_search_supports_logarithms(self):
        blocked = self.client.get("/semantic/search", params={"query": "log 1000", "limit": 3}).json()
        self.assertEqual(blocked["facts"][0]["triple"][1], "requires_learning")

        self._teach_logarithm_phase()
        log_base_10 = self.client.get("/semantic/search", params={"query": "log 1000", "limit": 3}).json()
        log_base_e = self.client.get("/semantic/search", params={"query": "ln(e)", "limit": 3}).json()
        derivative_ln = self.client.get("/semantic/search", params={"query": "d/dx ln(x)", "limit": 3}).json()
        integral_one_over_x = self.client.get("/semantic/search", params={"query": "integral 1/x dx", "limit": 3}).json()

        self.assertEqual(log_base_10["facts"][0]["triple"], ["log_10(1000)", "logarithm", "3"])
        self.assertEqual(log_base_e["facts"][0]["triple"], ["log_e(2.718281828459045)", "logarithm", "1"])
        self.assertEqual(derivative_ln["facts"][0]["triple"], ["ln(x)", "derivative", "1/(x)"])
        self.assertEqual(integral_one_over_x["facts"][0]["triple"], ["1/x", "integral", "ln|x| + C"])

    def test_semantic_recall_contains_calculus_space_edges(self):
        self._teach_calculus_phase()
        data = self.client.get(
            "/semantic/recall",
            params={"query": "d/dx x^2", "include_spaces": "calculus", "max_edges": 100},
        ).json()
        graph = data.get("relations_graph", {})
        self.assertEqual(set(graph.get("spaces", [])), {"calculus"})
        self.assertTrue(any(edge.get("space") == "calculus" for edge in graph.get("edges", [])))
        self.assertTrue(any(edge.get("relation_type") == "produces" for edge in graph.get("edges", [])))

    def test_semantic_recall_expands_concept_queries_to_all_spaces(self):
        self._teach_calculus_phase()
        data = self.client.get(
            "/semantic/recall",
            params={"query": "logarithm", "include_spaces": "risk", "max_edges": 120},
        ).json()
        graph = data.get("relations_graph", {})
        self.assertEqual(set(graph.get("spaces", [])), set(api.DEFAULT_SPACES))

    def test_semantic_search_blocks_arithmetic_before_numeracy_learning(self):
        data = self.client.get("/semantic/search", params={"query": "44+17", "limit": 3}).json()
        self.assertGreaterEqual(data.get("count", 0), 1)
        top = data.get("facts", [])[0]
        self.assertEqual(top.get("triple", [None, None])[1], "requires_learning")

    def test_learn_numeracy_endpoint_enables_arithmetic(self):
        taught = self.client.post("/learn/numeracy/basic")
        self.assertEqual(taught.status_code, 200)
        payload = taught.json()
        self.assertTrue(payload.get("ok"))
        self.assertGreaterEqual(payload.get("taught", 0), 10)

        data = self.client.get("/semantic/search", params={"query": "44+17", "limit": 3}).json()
        top = data.get("facts", [])[0]
        self.assertEqual(top.get("triple"), ["plus_44_17", "equals", "61"])

    def test_calculus_derivative_available_and_correct(self):
        result = self.client.get("/semantic/search", params={"query": "d/dx x^2", "limit": 3}).json()
        self.assertGreaterEqual(result.get("count", 0), 1)
        self.assertEqual(result["facts"][0]["triple"], ["x^2", "derivative", "2*x"])

        self._teach_calculus_phase()
        unlocked = self.client.get("/semantic/search", params={"query": "d/dx x^2", "limit": 3}).json()
        self.assertEqual(unlocked["facts"][0]["triple"], ["x^2", "derivative", "2*x"])

    def test_curriculum_phase_order_and_status_endpoint(self):
        bad_order = self.client.post("/learn/curriculum/phase/calculus")
        self.assertEqual(bad_order.status_code, 409)

        self.client.post("/learn/curriculum/phase/letters")
        self.client.post("/learn/curriculum/phase/digits")
        self.client.post("/learn/curriculum/phase/operations")
        self.client.post("/learn/curriculum/phase/real_numbers")
        ok = self.client.post("/learn/curriculum/phase/calculus")
        self.assertEqual(ok.status_code, 200)

        status = self.client.get("/learn/curriculum/status")
        self.assertEqual(status.status_code, 200)
        payload = status.json()
        self.assertIn("curriculum", payload)
        self.assertIn("completed", payload["curriculum"])
        self.assertIn("calculus", payload["curriculum"]["completed"])
        self.assertIn("phase_metrics", payload["curriculum"])
        self.assertEqual(len(payload["curriculum"]["phase_metrics"]), 6)
        self.assertTrue(any(item["phase"] == "calculus" and item["completed"] for item in payload["curriculum"]["phase_metrics"]))

    def test_curriculum_phase_debug_mode_returns_taught_facts(self):
        r = self.client.post("/learn/curriculum/phase/letters?debug=true")
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertIn("debug", payload)
        self.assertEqual(payload["debug"]["mode"], "curriculum_phase")
        self.assertGreater(len(payload["debug"]["taught_facts"]), 0)
        self.assertEqual(payload["debug"]["completed_before"], [])

    def test_economy_curriculum_phase_order_and_status_endpoint(self):
        bad_order = self.client.post("/learn/curriculum/economy/phase/elasticity")
        self.assertEqual(bad_order.status_code, 409)

        self.client.post("/learn/curriculum/economy/phase/foundations")
        self.client.post("/learn/curriculum/economy/phase/demand_supply")
        ok = self.client.post("/learn/curriculum/economy/phase/elasticity")
        self.assertEqual(ok.status_code, 200)

        status = self.client.get("/learn/curriculum/economy/status")
        self.assertEqual(status.status_code, 200)
        payload = status.json()
        self.assertIn("economy", payload)
        self.assertIn("phase_metrics", payload["curriculum"])
        self.assertEqual(len(payload["curriculum"]["phase_metrics"]), len(api.ECONOMY_CURRICULUM_PHASES))
        self.assertTrue(any(item["phase"] == "elasticity" and item["completed"] for item in payload["curriculum"]["phase_metrics"]))
        self.assertIn("demand", payload["economy"]["known_concepts"])

    def test_numeracy_basic_debug_mode_returns_taught_facts(self):
        r = self.client.post("/learn/numeracy/basic?debug=true")
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertIn("debug", payload)
        self.assertEqual(payload["debug"]["mode"], "numeracy_basic")
        self.assertGreater(len(payload["debug"]["taught_facts"]), 0)


class TestPrimaryReadinessEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_primary_readiness_returns_expected_shape(self):
        r = self.client.get("/learn/primary/readiness")
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertEqual(payload["target"], "primary_school_graduation")
        self.assertIn("overall_coverage", payload)
        self.assertIn("domains", payload)
        self.assertTrue(any(item.get("domain") == "mathematics" for item in payload["domains"]))
        self.assertTrue(any(item.get("domain") == "economy" for item in payload["domains"]))

    def test_primary_readiness_coverage_improves_after_teaching(self):
        baseline = self.client.get("/learn/primary/readiness").json()

        self.client.post("/learn/numeracy/basic")
        self.client.post("/learn/curriculum/economy/phase/foundations")
        self.client.post("/learn/curriculum/economy/phase/demand_supply")

        updated = self.client.get("/learn/primary/readiness").json()
        self.assertGreater(updated.get("overall_coverage", 0.0), baseline.get("overall_coverage", 0.0))

    def test_primary_weekly_plan_endpoint_returns_requested_weeks(self):
        r = self.client.get("/learn/primary/plan", params={"weeks": 4})
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertEqual(payload.get("weeks"), 4)
        self.assertEqual(len(payload.get("weekly_plan", [])), 4)
        self.assertIn("training_actions", payload["weekly_plan"][0])

    def test_primary_drip_plan_returns_requested_cycles(self):
        r = self.client.get(
            "/learn/primary/drip/plan",
            params={"cycles": 5, "new_concepts_per_cycle": 2, "reinforcement_concepts_per_cycle": 1},
        )
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertEqual(payload.get("cycles"), 5)
        self.assertEqual(len(payload.get("drip_plan", [])), 5)
        self.assertIn("new_concepts", payload["drip_plan"][0])
        self.assertIn("reinforcement_concepts", payload["drip_plan"][0])

    def test_primary_drip_run_improves_coverage(self):
        baseline = self.client.get("/learn/primary/readiness").json()
        r = self.client.post(
            "/learn/primary/drip/run",
            params={"cycles": 6, "new_concepts_per_cycle": 3, "reinforcement_concepts_per_cycle": 2},
        )
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("mode"), "continuous_drip")
        self.assertGreaterEqual(payload.get("applied", {}).get("new_concepts_ingested", 0), 1)

        updated = self.client.get("/learn/primary/readiness").json()
        self.assertGreater(updated.get("overall_coverage", 0.0), baseline.get("overall_coverage", 0.0))

    def test_primary_drip_run_stops_when_target_coverage_reached(self):
        r = self.client.post(
            "/learn/primary/drip/run",
            params={
                "cycles": 1,
                "target_coverage": 0.15,
                "max_total_cycles": 50,
                "new_concepts_per_cycle": 3,
                "reinforcement_concepts_per_cycle": 1,
            },
        )
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload.get("target_reached"))
        self.assertEqual(payload.get("stop_reason"), "target_coverage_reached")
        self.assertGreaterEqual(payload.get("coverage", {}).get("after", 0.0), 0.15)

    def test_primary_drip_run_supports_staged_confidence_learning(self):
        first = self.client.post(
            "/learn/primary/drip/run",
            params={
                "cycles": 1,
                "new_concepts_per_cycle": 1,
                "reinforcement_concepts_per_cycle": 0,
                "exposure_confidence": 0.45,
            },
        )
        self.assertEqual(first.status_code, 200)
        first_payload = first.json()
        self.assertEqual(first_payload.get("requested", {}).get("exposure_confidence"), 0.45)

        before_max = max(
            float(c)
            for _s, r, _o, c in api._kg.triples
            if str(r).lower() == "knows_concept"
        )
        pending_before = any(
            bool(api._kg.get_metadata(s, r, o).get("abstraction_pending"))
            for s, r, o, _c in api._kg.triples
            if str(r).lower() == "knows_concept"
        )
        self.assertTrue(pending_before)

        second = self.client.post(
            "/learn/primary/drip/run",
            params={
                "cycles": 1,
                "new_concepts_per_cycle": 1,
                "reinforcement_concepts_per_cycle": 1,
                "exposure_confidence": 0.45,
                "reinforcement_confidence": 0.95,
            },
        )
        self.assertEqual(second.status_code, 200)
        after_max = max(
            float(c)
            for _s, r, _o, c in api._kg.triples
            if str(r).lower() == "knows_concept"
        )
        self.assertGreater(after_max, before_max)
        pending_after = any(
            bool(api._kg.get_metadata(s, r, o).get("abstraction_pending"))
            for s, r, o, _c in api._kg.triples
            if str(r).lower() == "knows_concept"
        )
        self.assertTrue(pending_after)
        resolved_after = any(
            api._kg.get_metadata(s, r, o).get("abstraction_pending") is False
            for s, r, o, _c in api._kg.triples
            if str(r).lower() == "knows_concept"
        )
        self.assertTrue(resolved_after)

    def test_abstraction_pending_list_and_resolve(self):
        seed = self.client.post(
            "/ingest",
            json={
                "facts": [
                    {
                        "subject": "science",
                        "relation": "knows_concept",
                        "object": "aci",
                        "confidence": 0.9,
                        "teaching_kind": "concept_seed",
                    }
                ],
                "stage": "validated",
                "source_document": "pending_seed_demo.txt",
            },
        )
        self.assertEqual(seed.status_code, 200)

        pending = self.client.get("/learn/primary/abstraction/pending", params={"limit": 20})
        self.assertEqual(pending.status_code, 200)
        pending_payload = pending.json()
        self.assertTrue(any(item.get("concept") == "aci" for item in pending_payload.get("items", [])))

        resolved = self.client.post(
            "/learn/primary/abstraction/resolve",
            params={"limit": 20, "reinforcement_confidence": 0.97},
        )
        self.assertEqual(resolved.status_code, 200)
        resolved_payload = resolved.json()
        self.assertTrue(resolved_payload.get("ok"))
        self.assertGreaterEqual(resolved_payload.get("resolved", 0), 1)

        pending_after = self.client.get("/learn/primary/abstraction/pending", params={"limit": 20}).json()
        self.assertFalse(any(item.get("concept") == "aci" for item in pending_after.get("items", [])))

        matching = [
            (s, r, o, c)
            for s, r, o, c in api._kg.triples
            if str(s).lower() == "science" and str(r).lower() == "knows_concept" and str(o).lower() == "aci"
        ]
        self.assertEqual(len(matching), 1)
        self.assertGreaterEqual(float(matching[0][3]), 0.97)
        self.assertFalse(api._kg.get_metadata(matching[0][0], matching[0][1], matching[0][2]).get("abstraction_pending", True))


class TestLearningBootstrapAndResetEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_bootstrap_plan_endpoint_returns_stages(self):
        r = self.client.get("/learn/bootstrap/plan")
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertEqual(payload.get("model"), "concept_tensor")
        self.assertGreaterEqual(len(payload.get("stages", [])), 4)
        self.assertEqual(payload["stages"][0]["stage"], "language_literacy")

    def test_reset_requires_confirm_flag(self):
        r = self.client.post("/learn/reset")
        self.assertEqual(r.status_code, 400)

    def test_reset_clears_learning_state_when_confirmed(self):
        self.client.post(
            "/ingest",
            json={
                "facts": [
                    {
                        "subject": "tv",
                        "relation": "used_for",
                        "object": "eglence",
                        "confidence": 0.95,
                        "teaching_kind": "rule",
                    }
                ],
                "stage": "validated",
            },
        )
        before_metrics = self.client.get("/metrics").json()
        self.assertGreater(before_metrics.get("kg_edges", 0), 0)

        reset = self.client.post("/learn/reset", params={"confirm": "true"})
        self.assertEqual(reset.status_code, 200)
        payload = reset.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("reset", {}).get("after", {}).get("triples", -1), 0)

        after_metrics = self.client.get("/metrics").json()
        self.assertEqual(after_metrics.get("kg_edges", -1), 0)


class TestConceptSpaceEmbeddingEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_concept_embedding_endpoint_returns_spaces_for_known_concept(self):
        self.client.post(
            "/ingest",
            json={
                "facts": [
                    {
                        "subject": "numeracy",
                        "relation": "knows_concept",
                        "object": "fraction",
                        "confidence": 0.98,
                        "teaching_kind": "rule",
                    }
                ],
                "stage": "validated",
            },
        )
        data = self.client.get("/semantic/concept/fraction/embedding").json()
        self.assertEqual(data.get("concept"), "fraction")
        self.assertIn("spaces", data)
        self.assertIn("semantic", data.get("spaces", {}))

    def test_concept_embedding_tracks_multiple_spaces(self):
        self.client.post(
            "/ingest",
            json={
                "facts": [
                    {
                        "subject": "numeracy",
                        "relation": "knows_concept",
                        "object": "logarithm",
                        "confidence": 0.99,
                        "teaching_kind": "rule",
                        "curriculum_phase": "logarithms",
                    },
                    {
                        "subject": "arithmetic",
                        "relation": "knows_concept",
                        "object": "logarithm",
                        "confidence": 0.95,
                        "teaching_kind": "rule",
                    },
                ],
                "stage": "validated",
            },
        )
        data = self.client.get("/semantic/concept/logarithm/embedding").json()
        spaces = data.get("spaces", {})
        self.assertIn("semantic", spaces)
        self.assertIn("curriculum", spaces)
        self.assertIn("arithmetic", spaces)
        self.assertGreaterEqual(len(data.get("space_differences", [])), 1)

    def test_concept_trace_reports_space_confidence_breakdown(self):
        self.client.post(
            "/ingest",
            json={
                "facts": [
                    {
                        "subject": "ev",
                        "relation": "uses",
                        "object": "avize",
                        "confidence": 0.92,
                        "teaching_kind": "rule",
                        "space_hint": "goal",
                    },
                    {
                        "subject": "avize",
                        "relation": "used_for",
                        "object": "aydinlatma",
                        "confidence": 0.98,
                        "teaching_kind": "rule",
                        "space_hint": "goal,semantic",
                    },
                    {
                        "subject": "avize",
                        "relation": "contains",
                        "object": "ampul",
                        "confidence": 0.96,
                        "teaching_kind": "rule",
                        "space_hint": "semantic,curriculum",
                    },
                    {
                        "subject": "science",
                        "relation": "knows_concept",
                        "object": "avize",
                        "confidence": 0.99,
                        "teaching_kind": "rule",
                        "space_hint": "semantic,curriculum",
                    },
                ],
                "stage": "validated",
            },
        )

        data = self.client.get("/semantic/concept/avize/trace").json()
        self.assertEqual(data.get("concept"), "avize")
        self.assertIn("facts", data)
        self.assertTrue(any(item.get("confidence", 0) >= 0.92 for item in data.get("facts", [])))
        self.assertIn("spaces", data)
        spaces = {item.get("space") for item in data.get("spaces", [])}
        self.assertIn("semantic", spaces)
        self.assertIn("goal", spaces)
        self.assertTrue(any(float(item.get("avg_fact_confidence", 0)) > 0 for item in data.get("spaces", [])))


class TestIngestEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_ingest_texts_returns_200(self):
        r = self.client.post("/ingest/texts", json={"texts": ["rain causes flood 0.8"]})
        self.assertEqual(r.status_code, 200)

    def test_ingest_facts_adds_triples(self):
        r = self.client.post("/ingest", json={
            "facts": [{"subject": "rain", "relation": "causes", "object": "flood", "confidence": 0.9}]
        })
        data = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(data.get("triples", 0), 1)

    def test_ingest_seed_returns_200(self):
        r = self.client.post("/ingest/seed")
        self.assertEqual(r.status_code, 200)

    def test_ingest_auth_rejected_when_key_set(self):
        # Temporarily set INGEST_API_KEY in the api module so the dependency
        # enforces authentication, then send a request without the header.
        original = api.INGEST_API_KEY
        try:
            api.INGEST_API_KEY = "secret"
            r = self.client.post("/ingest/seed")
            self.assertEqual(r.status_code, 403)
        finally:
            api.INGEST_API_KEY = original

    def test_ingest_document_returns_candidates(self):
        r = self.client.post("/ingest/documents", json={
            "content": "Rain causes flood. Flood causes damage.",
            "source_document": "doc-api",
            "stage": "candidate",
        })
        data = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(data["candidates"], 2)

    def test_candidate_lifecycle_promote(self):
        create = self.client.post("/ingest/candidates", json={
            "texts": ["rain causes flood 0.8"],
            "source_document": "doc-review",
        })
        candidate_id = create.json()["candidate_ids"][0]
        pending = self.client.get("/ingest/candidates").json()
        self.assertEqual(pending["count"], 1)

        promote = self.client.post(f"/ingest/candidates/{candidate_id}/promote")
        self.assertEqual(promote.status_code, 200)
        self.assertGreaterEqual(len(api._kg.triples), 1)

    def test_candidate_reject_returns_200(self):
        create = self.client.post("/ingest/candidates", json={
            "facts": [{"subject": "rain", "relation": "causes", "object": "flood"}]
        })
        candidate_id = create.json()["candidate_ids"][0]
        reject = self.client.post(
            f"/ingest/candidates/{candidate_id}/reject",
            json={"reason": "needs review"},
        )
        self.assertEqual(reject.status_code, 200)
        self.assertEqual(api._data_loader.tms.get_candidate_belief(candidate_id)["review_status"], "rejected")


class _FakePdfLoader:
    def ingest_pdf_document(self, payload, *, source_document, stage, metadata):
        return {
            "documents": 1,
            "pages": 2,
            "sentences": 4,
            "triples": 0,
            "transitions": 0,
            "q_updates": 0,
            "candidates": 2,
            "candidate_ids": [f"cand-{source_document}"],
            "skipped": 0,
            "failed": 0,
            "source_document": source_document,
            "stage": stage,
            "metadata": metadata,
            "payload_size": len(payload),
        }


class _FakePDFExtractor:
    def extract_pages_from_bytes(self, _payload: bytes):
        return [{"page_index": 0, "text": "Rain causes flood. Flood causes damage."}]


class TestPdfIngestEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_ingest_pdf_returns_200(self):
        with patch("api._get_loader", return_value=_FakePdfLoader()):
            r = self.client.post(
                "/ingest/pdf",
                data={"stage": "candidate", "metadata": '{"source":"unit"}'},
                files={"file": ("doc.pdf", b"fake", "application/pdf")},
            )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["documents"], 1)
        self.assertEqual(data["candidates"], 2)

    def test_ingest_pdf_rejects_non_pdf(self):
        with patch("api._get_loader", return_value=_FakePdfLoader()):
            r = self.client.post(
                "/ingest/pdf",
                files={"file": ("doc.txt", b"fake", "text/plain")},
            )
        self.assertEqual(r.status_code, 415)

    def test_ingest_pdfs_batch_returns_200(self):
        with patch("api._get_loader", return_value=_FakePdfLoader()):
            r = self.client.post(
                "/ingest/pdfs",
                data={"stage": "candidate"},
                files=[
                    ("files", ("a.pdf", b"aaa", "application/pdf")),
                    ("files", ("b.pdf", b"bbb", "application/pdf")),
                ],
            )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["documents"], 2)
        self.assertEqual(data["candidates"], 4)

    def test_ingest_pdf_can_teach_curriculum_phase_from_metadata(self):
        with patch("api._get_loader", return_value=_FakePdfLoader()):
            letters = self.client.post(
                "/ingest/pdf",
                data={
                    "stage": "validated",
                    "metadata": '{"curriculum_phase":"letters","teach_curriculum":true}',
                },
                files={"file": ("letters.pdf", b"fake", "application/pdf")},
            )
            digits = self.client.post(
                "/ingest/pdf",
                data={
                    "stage": "validated",
                    "metadata": '{"curriculum_phase":"digits","teach_curriculum":true}',
                },
                files={"file": ("digits.pdf", b"fake-2", "application/pdf")},
            )

        self.assertEqual(letters.status_code, 200)
        self.assertEqual(digits.status_code, 200)
        letters_payload = letters.json()
        digits_payload = digits.json()
        self.assertEqual(letters_payload["curriculum"]["phase"], "letters")
        self.assertGreaterEqual(letters_payload["curriculum"]["taught"], 1)
        self.assertIn("digits", digits_payload["curriculum"]["completed_phases"])

    def test_ingest_pdf_debug_mode_returns_learning_diagnostics(self):
        with patch("api._get_loader", return_value=_FakePdfLoader()):
            r = self.client.post(
                "/ingest/pdf?debug=true",
                data={
                    "stage": "validated",
                    "metadata": '{"curriculum_phase":"letters","teach_curriculum":true}',
                },
                files={"file": ("letters.pdf", b"fake", "application/pdf")},
            )

        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertIn("debug", payload)
        self.assertEqual(payload["debug"]["mode"], "pdf_upload")
        self.assertEqual(payload["debug"]["curriculum_phase"], "letters")

    def test_ingest_pdf_curriculum_phase_respects_prerequisites(self):
        with patch("api._get_loader", return_value=_FakePdfLoader()):
            r = self.client.post(
                "/ingest/pdf",
                data={
                    "stage": "validated",
                    "metadata": '{"curriculum_phase":"operations","teach_curriculum":true}',
                },
                files={"file": ("operations.pdf", b"fake", "application/pdf")},
            )

        self.assertEqual(r.status_code, 409)


class TestE2EPdfCandidateRecall(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_pdf_to_candidate_promote_then_recall(self):
        loader = DataLoader(tms=api._tms, kg=api._kg, parser=api._parser)
        loader.pdf_ingestion = _FakePDFExtractor()

        with patch("api._get_loader", return_value=loader):
            create = self.client.post(
                "/ingest/pdf",
                data={"stage": "candidate", "source_document": "e2e.pdf"},
                files={"file": ("e2e.pdf", b"dummy", "application/pdf")},
            )
            self.assertEqual(create.status_code, 200)
            create_data = create.json()
            self.assertGreaterEqual(create_data.get("candidates", 0), 1)

            pending = self.client.get("/ingest/candidates")
            self.assertEqual(pending.status_code, 200)
            pending_data = pending.json()
            self.assertGreaterEqual(pending_data.get("count", 0), 1)
            candidate_id = pending_data["candidates"][0]["id"]

            promote = self.client.post(f"/ingest/candidates/{candidate_id}/promote")
            self.assertEqual(promote.status_code, 200)

            recall = self.client.get("/semantic/recall", params={"query": "flood"})
            self.assertEqual(recall.status_code, 200)
            recall_data = recall.json()
            self.assertIn("facts", recall_data)
            self.assertIn("relations_graph", recall_data)
            self.assertGreaterEqual(len(recall_data.get("facts", [])), 1)


class TestOpsAndSecurityControls(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_pdf_ingest_feature_flag_can_disable_endpoint(self):
        original = api.ENABLE_PDF_INGEST
        try:
            api.ENABLE_PDF_INGEST = False
            with patch("api._get_loader", return_value=_FakePdfLoader()):
                r = self.client.post(
                    "/ingest/pdf",
                    files={"file": ("doc.pdf", b"fake", "application/pdf")},
                )
            self.assertEqual(r.status_code, 503)
        finally:
            api.ENABLE_PDF_INGEST = original

    def test_space_relations_feature_flag_can_disable_endpoint(self):
        original = api.ENABLE_SPACE_RELATIONS
        try:
            api.ENABLE_SPACE_RELATIONS = False
            r = self.client.get("/semantic/relations", params={"query": "flood"})
            self.assertEqual(r.status_code, 503)
        finally:
            api.ENABLE_SPACE_RELATIONS = original

    def test_ingest_rate_limit_returns_429(self):
        original_max = api.INGEST_RATE_LIMIT_MAX_REQUESTS
        original_window = api.INGEST_RATE_LIMIT_WINDOW_SECONDS
        try:
            api.INGEST_RATE_LIMIT_MAX_REQUESTS = 1
            api.INGEST_RATE_LIMIT_WINDOW_SECONDS = 60
            api._ingest_rate_bucket.clear()

            first = self.client.post("/ingest/texts", json={"texts": ["rain causes flood 0.9"]})
            self.assertEqual(first.status_code, 200)
            second = self.client.post("/ingest/texts", json={"texts": ["flood causes damage 0.8"]})
            self.assertEqual(second.status_code, 429)
        finally:
            api.INGEST_RATE_LIMIT_MAX_REQUESTS = original_max
            api.INGEST_RATE_LIMIT_WINDOW_SECONDS = original_window
            api._ingest_rate_bucket.clear()


class TestJEPAPersistence(unittest.TestCase):
    """Unit tests for JEPAModel.save() / load()."""

    def test_save_and_load_roundtrip(self):
        model = JEPAModel(seed=0)
        # Do a few updates to get non-trivial weights
        rng = np.random.default_rng(1)
        for _ in range(5):
            sv = rng.random(7).astype(np.float32)
            nsv = rng.random(7).astype(np.float32)
            model.update(sv, 0, nsv)

        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            path = f.name
        try:
            model.save(path)
            restored = JEPAModel(seed=99)  # different seed → different initial weights
            restored.load(path)
            np.testing.assert_array_almost_equal(model.W_ctx, restored.W_ctx)
            np.testing.assert_array_almost_equal(model.W_tgt, restored.W_tgt)
            np.testing.assert_array_almost_equal(model.W_pred, restored.W_pred)
            self.assertEqual(model._trained_samples, restored._trained_samples)
        finally:
            os.unlink(path)

    def test_load_missing_file_raises_file_not_found(self):
        model = JEPAModel()
        with self.assertRaises(FileNotFoundError):
            model.load("/nonexistent/path/jepa.npz")

    def test_predict_consistent_after_roundtrip(self):
        model = JEPAModel(seed=7)
        rng = np.random.default_rng(7)
        for _ in range(10):
            model.update(rng.random(7).astype(np.float32), 1, rng.random(7).astype(np.float32))

        sv = rng.random(7).astype(np.float32)
        score_before = model.predict_score(sv, 0)

        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            path = f.name
        try:
            model.save(path)
            clone = JEPAModel()
            clone.load(path)
            score_after = clone.predict_score(sv, 0)
            self.assertAlmostEqual(score_before, score_after, places=6)
        finally:
            os.unlink(path)


class TestAdditionalEndpointCoverage(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def _teach_calculus(self):
        self.client.post("/learn/numeracy/basic")
        self.client.post("/learn/curriculum/phase/calculus")

    def test_semantic_search_definite_integral(self):
        self._teach_calculus()
        data = self.client.get(
            "/semantic/search",
            params={"query": "integral from 0 to 2 x^2 dx", "limit": 5},
        ).json()
        self.assertGreaterEqual(data.get("count", 0), 1)
        self.assertTrue(any(f.get("triple", [None, None])[1] == "definite_integral" for f in data.get("facts", [])))

    def test_semantic_search_derivative_chain_rule(self):
        self._teach_calculus()
        data = self.client.get(
            "/semantic/search",
            params={"query": "d/dx sin(x^2)", "limit": 5},
        ).json()
        self.assertGreaterEqual(data.get("count", 0), 1)
        self.assertTrue(any(f.get("triple", [None, None])[1] == "derivative" for f in data.get("facts", [])))

    def test_semantic_search_matrix_determinant(self):
        data = self.client.get(
            "/semantic/search",
            params={"query": "matrix det([[1,2],[3,4]])", "limit": 5},
        ).json()
        self.assertGreaterEqual(data.get("count", 0), 1)
        self.assertTrue(any(f.get("triple", [None, None])[1] == "determinant" for f in data.get("facts", [])))

    def test_semantic_search_solve_equation(self):
        data = self.client.get(
            "/semantic/search",
            params={"query": "solve x^2 - 5*x + 6 = 0", "limit": 5},
        ).json()
        self.assertGreaterEqual(data.get("count", 0), 1)
        self.assertTrue(any(f.get("triple", [None, None])[1] == "solved" for f in data.get("facts", [])))

    def test_memory_episodic_endpoint(self):
        self.client.post("/think", json={"state": "flood"})
        r = self.client.get("/memory/episodic", params={"limit": 10})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("episodes", data)
        self.assertGreaterEqual(data.get("count", 0), 1)

    def test_memory_emotional_trend_endpoint(self):
        self.client.post("/think", json={"state": "flood"})
        self.client.post("/think", json={"state": "crisis"})
        r = self.client.get("/memory/emotional_trend", params={"n": 10})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("avg_vector", data)
        self.assertEqual(len(data.get("avg_vector", [])), 5)
        self.assertIn("timeline", data)

    def test_semantic_abstractions_endpoint(self):
        self.client.post("/semantic/assert", json={"subject": "rain", "relation": "causes", "obj": "flood", "confidence": 0.9})
        self.client.post("/semantic/assert", json={"subject": "storm", "relation": "causes", "obj": "flood", "confidence": 0.9})
        r = self.client.get("/semantic/abstractions")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("abstract_patterns", data)
        self.assertIn("abstract_rules", data)

    def test_learn_abstraction_trigger_endpoint(self):
        self.client.post("/semantic/assert", json={"subject": "rain", "relation": "causes", "obj": "flood", "confidence": 0.9})
        self.client.post("/semantic/assert", json={"subject": "storm", "relation": "causes", "obj": "flood", "confidence": 0.9})
        r = self.client.post("/learn/abstraction/trigger")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("promoted", data)
        self.assertIn("concept_count", data)
        self.assertIn("rule_count", data)

    def test_debug_emotion_jepa_endpoint(self):
        r = self.client.get("/debug/emotion/jepa")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("test_sequence", data)
        self.assertGreater(data.get("count", 0), 0)

    def test_think_endpoint_emotion_fields(self):
        r = self.client.post("/think", json={"state": "flood"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("emotion", data)
        self.assertEqual(len(data.get("emotion", [])), 5)
        self.assertIn("jepa_emotion_delta", data)
        self.assertEqual(len(data.get("jepa_emotion_delta", [])), 5)

    def test_curriculum_status_endpoint(self):
        r = self.client.get("/curriculum/status")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("current_stage", data)
        self.assertIn("stage_id", data)
        self.assertIn("progress_percentage", data)

    def test_semantic_search_arithmetic_sequence(self):
        data = self.client.get(
            "/semantic/search",
            params={"query": "3, 6, 9, 15, 24, ?", "limit": 5},
        ).json()
        self.assertGreaterEqual(data.get("count", 0), 1)
        self.assertTrue(any(f.get("triple", [None, None])[1] == "sequence_next" for f in data.get("facts", [])))
        seq_fact = next(f for f in data.get("facts", []) if f.get("triple", [None, None])[1] == "sequence_next")
        self.assertEqual(seq_fact["triple"][2], "39")
        prov = seq_fact.get("provenance", {})
        self.assertEqual(prov.get("pattern_type"), "fibonacci_like")

    def test_semantic_search_geometric_sequence(self):
        data = self.client.get(
            "/semantic/search",
            params={"query": "2, 4, 8, 16, ?", "limit": 5},
        ).json()
        self.assertGreaterEqual(data.get("count", 0), 1)
        seq_fact = next(f for f in data.get("facts", []) if f.get("triple", [None, None])[1] == "sequence_next")
        self.assertEqual(seq_fact["triple"][2], "32")
        self.assertEqual(seq_fact.get("provenance", {}).get("pattern_type"), "geometric")

    def test_semantic_search_quadratic_sequence(self):
        data = self.client.get(
            "/semantic/search",
            params={"query": "1, 4, 9, 16, 25", "limit": 5},
        ).json()
        self.assertGreaterEqual(data.get("count", 0), 1)
        seq_fact = next(f for f in data.get("facts", []) if f.get("triple", [None, None])[1] == "sequence_next")
        self.assertEqual(seq_fact["triple"][2], "36")
        self.assertEqual(seq_fact.get("provenance", {}).get("pattern_type"), "quadratic")

    def test_semantic_search_sequence_no_pattern(self):
        data = self.client.get(
            "/semantic/search",
            params={"query": "1, 3, 7, 13, 22, ?", "limit": 5},
        ).json()
        self.assertFalse(any(f.get("triple", [None, None])[1] == "sequence_next" for f in data.get("facts", [])))


if __name__ == "__main__":
    unittest.main()
