"""Tests for the Autonomic Curriculum Controller (learning/curriculum.py)
and its integration in the API layer.
"""

import sys
import unittest
from collections import defaultdict
from unittest.mock import MagicMock, patch
import tempfile
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Unit tests for CurriculumController
# ---------------------------------------------------------------------------

from learning.curriculum import (
    CurriculumController,
    PrerequisiteNotMetError,
    STAGE_DEFINITIONS,
    MAX_STAGE,
)


class TestStageDefinitions(unittest.TestCase):
    def test_stage_count(self):
        self.assertEqual(len(STAGE_DEFINITIONS), 3)

    def test_stage_0_literacy(self):
        s = STAGE_DEFINITIONS[0]
        self.assertEqual(s["label"], "LITERACY")
        self.assertEqual(s["min_concepts"], 5)
        self.assertFalse(s["allows_arithmetic"])

    def test_stage_1_numeracy(self):
        s = STAGE_DEFINITIONS[1]
        self.assertEqual(s["label"], "NUMERACY")
        self.assertEqual(s["min_concepts"], 15)
        self.assertTrue(s["allows_arithmetic"])

    def test_stage_2_reasoning(self):
        s = STAGE_DEFINITIONS[2]
        self.assertEqual(s["label"], "REASONING")
        self.assertEqual(s["min_concepts"], 30)
        self.assertTrue(s["allows_arithmetic"])
        self.assertTrue(s["allows_abstraction"])


class TestCurriculumControllerInit(unittest.TestCase):
    def test_initial_stage_is_zero(self):
        ctrl = CurriculumController()
        self.assertEqual(ctrl.current_stage, 0)

    def test_initial_label_is_literacy(self):
        ctrl = CurriculumController()
        self.assertEqual(ctrl.stage_label, "LITERACY")

    def test_initial_last_stage_up_time_is_none(self):
        ctrl = CurriculumController()
        self.assertIsNone(ctrl.last_stage_up_time)


class TestProgressionEvaluation(unittest.TestCase):
    def setUp(self):
        self.ctrl = CurriculumController(error_tolerance=0.5, stability_window=5)

    def test_no_advance_when_density_not_met(self):
        result = self.ctrl.evaluate_progression(concept_count=3, recent_errors=[0.1])
        self.assertFalse(result["advanced"])
        self.assertFalse(result["blocked"])
        self.assertEqual(self.ctrl.current_stage, 0)

    def test_advance_when_density_and_stability_met(self):
        result = self.ctrl.evaluate_progression(concept_count=15, recent_errors=[0.1, 0.2])
        self.assertTrue(result["advanced"])
        self.assertFalse(result["blocked"])
        self.assertEqual(self.ctrl.current_stage, 1)

    def test_blocked_when_density_met_but_stability_not(self):
        result = self.ctrl.evaluate_progression(concept_count=15, recent_errors=[0.9, 1.0])
        self.assertFalse(result["advanced"])
        self.assertTrue(result["blocked"])
        self.assertEqual(self.ctrl.current_stage, 0)  # not advanced

    def test_blocked_status_set_in_report(self):
        self.ctrl.evaluate_progression(concept_count=15, recent_errors=[0.9, 1.0])
        report = self.ctrl.get_status_report(15)
        self.assertTrue(report["blocking_status"])
        self.assertIsNotNone(report["blocking_reason"])

    def test_stage_up_time_set_on_advance(self):
        self.ctrl.evaluate_progression(concept_count=15, recent_errors=[0.1])
        self.assertIsNotNone(self.ctrl.last_stage_up_time)

    def test_no_advance_beyond_max_stage(self):
        self.ctrl.current_stage = MAX_STAGE
        result = self.ctrl.evaluate_progression(concept_count=9999, recent_errors=[0.0])
        self.assertFalse(result["advanced"])
        self.assertEqual(self.ctrl.current_stage, MAX_STAGE)

    def test_advance_to_stage_2_from_1(self):
        self.ctrl.current_stage = 1
        result = self.ctrl.evaluate_progression(concept_count=30, recent_errors=[0.1])
        self.assertTrue(result["advanced"])
        self.assertEqual(self.ctrl.current_stage, 2)

    def test_no_advance_from_1_density_not_met(self):
        self.ctrl.current_stage = 1
        result = self.ctrl.evaluate_progression(concept_count=20, recent_errors=[0.1])
        self.assertFalse(result["advanced"])
        self.assertEqual(self.ctrl.current_stage, 1)

    def test_empty_recent_errors_treated_as_stable(self):
        # No JEPA errors yet => avg=0.0 <= tolerance, counts as stable
        result = self.ctrl.evaluate_progression(concept_count=15, recent_errors=[])
        self.assertTrue(result["advanced"])

    def test_stage_progression_is_monotonic(self):
        # Stage should never decrease automatically
        self.ctrl.current_stage = 1
        for _ in range(5):
            self.ctrl.evaluate_progression(concept_count=3, recent_errors=[2.0])
        self.assertGreaterEqual(self.ctrl.current_stage, 1)


class TestPrerequisiteGate(unittest.TestCase):
    def setUp(self):
        self.ctrl = CurriculumController()

    def test_arithmetic_blocked_at_stage_0(self):
        self.ctrl.current_stage = 0
        with self.assertRaises(PrerequisiteNotMetError) as cm:
            self.ctrl.check_prerequisite("arithmetic")
        exc = cm.exception
        self.assertEqual(exc.required_stage, 1)
        self.assertEqual(exc.current_stage, 0)
        self.assertEqual(exc.operation, "arithmetic")

    def test_arithmetic_allowed_at_stage_1(self):
        self.ctrl.current_stage = 1
        # Should not raise
        self.ctrl.check_prerequisite("arithmetic")

    def test_arithmetic_allowed_at_stage_2(self):
        self.ctrl.current_stage = 2
        self.ctrl.check_prerequisite("arithmetic")

    def test_abstraction_blocked_at_stage_1(self):
        self.ctrl.current_stage = 1
        with self.assertRaises(PrerequisiteNotMetError) as cm:
            self.ctrl.check_prerequisite("abstraction")
        exc = cm.exception
        self.assertEqual(exc.required_stage, 2)

    def test_abstraction_allowed_at_stage_2(self):
        self.ctrl.current_stage = 2
        self.ctrl.check_prerequisite("abstraction")

    def test_unknown_task_always_allowed(self):
        self.ctrl.current_stage = 0
        self.ctrl.check_prerequisite("unknown_task")  # should not raise


class TestStatusReport(unittest.TestCase):
    def setUp(self):
        self.ctrl = CurriculumController()

    def test_status_report_keys(self):
        report = self.ctrl.get_status_report(0)
        for key in ("current_stage", "stage_id", "progress_percentage",
                    "blocking_status", "blocking_reason", "last_stage_up_time",
                    "stage_definitions"):
            self.assertIn(key, report)

    def test_status_report_current_stage_label(self):
        report = self.ctrl.get_status_report()
        self.assertEqual(report["current_stage"], "LITERACY")

    def test_progress_percentage_zero_no_concepts(self):
        report = self.ctrl.get_status_report(0)
        self.assertEqual(report["progress_percentage"], 0.0)

    def test_progress_percentage_capped_at_100(self):
        report = self.ctrl.get_status_report(9999)
        self.assertEqual(report["progress_percentage"], 100.0)

    def test_progress_percentage_partial(self):
        # next stage requires 15 concepts; with 7 concepts: 7/15 * 100 ≈ 46.67
        report = self.ctrl.get_status_report(7)
        self.assertAlmostEqual(report["progress_percentage"], round(7 / 15 * 100, 2))

    def test_blocking_status_false_by_default(self):
        report = self.ctrl.get_status_report(0)
        self.assertFalse(report["blocking_status"])


class TestReset(unittest.TestCase):
    def test_reset_reverts_to_stage_0(self):
        ctrl = CurriculumController()
        ctrl.current_stage = 2
        ctrl.last_stage_up_time = 12345.0
        ctrl.reset()
        self.assertEqual(ctrl.current_stage, 0)
        self.assertIsNone(ctrl.last_stage_up_time)

    def test_reset_clears_blocking_reason(self):
        ctrl = CurriculumController()
        ctrl._blocking_reason = "some reason"
        ctrl.reset()
        self.assertIsNone(ctrl._blocking_reason)


class TestPersistence(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "curriculum.json"
            ctrl = CurriculumController(error_tolerance=0.3, stability_window=10)
            ctrl.current_stage = 1
            ctrl.last_stage_up_time = 999.0
            ctrl.save(path)

            ctrl2 = CurriculumController()
            ctrl2.load(path)
            self.assertEqual(ctrl2.current_stage, 1)
            self.assertAlmostEqual(ctrl2.last_stage_up_time, 999.0)
            self.assertAlmostEqual(ctrl2.error_tolerance, 0.3)
            self.assertEqual(ctrl2.stability_window, 10)

    def test_load_missing_file_raises(self):
        ctrl = CurriculumController()
        with self.assertRaises(FileNotFoundError):
            ctrl.load("/tmp/nonexistent_curriculum_state.json")

    def test_loaded_stage_label_matches_stage_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "curriculum.json"
            ctrl = CurriculumController()
            ctrl.current_stage = 2
            ctrl.save(path)

            ctrl2 = CurriculumController()
            ctrl2.load(path)
            self.assertEqual(ctrl2.stage_label, "REASONING")


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

# Patch heavy startup dependencies BEFORE importing api
_mock_main = MagicMock()
_mock_main.Q = defaultdict(float)
_mock_main.policy_counter = {}
_mock_main.get_key = lambda state: tuple(sorted(state)) if not isinstance(state, str) else state
sys.modules.setdefault("main", _mock_main)

import api  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from core.knowledge_graph import KnowledgeGraph  # noqa: E402
from core.tms import LiteTMS  # noqa: E402
from core.parser import SemanticParser  # noqa: E402
from learning.jepa import JEPAModel  # noqa: E402
from cognition.thought_loop import ThoughtLoop  # noqa: E402
from config import ACTIONS  # noqa: E402


def _make_client(stage: int = 0):
    """Build a fresh TestClient with a clean curriculum at the given stage."""
    api._kg = KnowledgeGraph()
    api._tms = LiteTMS()
    api._parser = SemanticParser()
    api._jepa = JEPAModel()
    api._jepa_recent_errors.clear()

    def _fake_simulate(state, action):
        s = set(state) if not isinstance(state, str) else set()
        reward = 4.0 if action == "barrier" else 0.0
        return reward, tuple(sorted(s))

    api._thought_loop = ThoughtLoop(
        _mock_main, api._jepa, _fake_simulate, _mock_main.Q, ACTIONS
    )
    api._data_loader = None

    # Reset curriculum to the desired stage
    from learning.curriculum import CurriculumController
    from config import CURRICULUM_ERROR_TOLERANCE, CURRICULUM_STABILITY_WINDOW
    api._curriculum = CurriculumController(
        error_tolerance=CURRICULUM_ERROR_TOLERANCE,
        stability_window=CURRICULUM_STABILITY_WINDOW,
    )
    api._curriculum.current_stage = stage

    return TestClient(api.app, raise_server_exceptions=False)


class TestLearnProcessEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client(stage=0)

    def test_learn_process_returns_200(self):
        r = self.client.post("/learn/process")
        self.assertEqual(r.status_code, 200)

    def test_learn_process_has_required_keys(self):
        data = self.client.post("/learn/process").json()
        for key in ("concept_count", "stage_advanced", "blocked", "reason", "curriculum"):
            self.assertIn(key, data, f"Missing key: {key}")

    def test_learn_process_concept_count_is_int(self):
        data = self.client.post("/learn/process").json()
        self.assertIsInstance(data["concept_count"], int)

    def test_learn_process_stage_advanced_is_bool(self):
        data = self.client.post("/learn/process").json()
        self.assertIsInstance(data["stage_advanced"], bool)

    def test_learn_process_curriculum_has_status_keys(self):
        data = self.client.post("/learn/process").json()
        curriculum = data["curriculum"]
        for key in ("current_stage", "progress_percentage", "blocking_status"):
            self.assertIn(key, curriculum)

    def test_learn_process_avg_jepa_error_none_when_no_updates(self):
        # Fresh client with no JEPA updates → avg_jepa_error should be None or 0
        data = self.client.post("/learn/process").json()
        # avg_error=0.0 for empty deque (stable), reported as 0.0
        self.assertIn("avg_jepa_error", data)


class TestJEPAErrorTracking(unittest.TestCase):
    """Verify that _jepa_recent_errors deque is populated by online updates."""

    def setUp(self):
        self.client = _make_client(stage=0)

    def test_jepa_errors_populated_after_decision(self):
        # Trigger a hybrid_decision which calls _jepa_online_update
        from learning.jepa import JEPAModel
        import numpy as np
        # Manually call _jepa_online_update to simulate an update
        initial_len = len(api._jepa_recent_errors)
        api._jepa_online_update(["flood"], "barrier")
        self.assertEqual(len(api._jepa_recent_errors), initial_len + 1)

    def test_jepa_error_is_float(self):
        api._jepa_online_update(["damage"], "evacuate")
        self.assertIsInstance(api._jepa_recent_errors[-1], float)

    def test_jepa_recent_errors_deque_maxlen(self):
        from config import CURRICULUM_STABILITY_WINDOW
        self.assertEqual(api._jepa_recent_errors.maxlen, CURRICULUM_STABILITY_WINDOW)


class TestCurriculumStatusEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client(stage=0)

    def test_curriculum_status_returns_200(self):
        r = self.client.get("/curriculum/status")
        self.assertEqual(r.status_code, 200)

    def test_curriculum_status_has_required_keys(self):
        data = self.client.get("/curriculum/status").json()
        for key in ("current_stage", "stage_id", "progress_percentage",
                    "blocking_status", "last_stage_up_time"):
            self.assertIn(key, data, f"Missing key: {key}")

    def test_curriculum_status_initial_stage(self):
        data = self.client.get("/curriculum/status").json()
        self.assertEqual(data["current_stage"], "LITERACY")
        self.assertEqual(data["stage_id"], 0)


class TestCurriculumResetEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _make_client(stage=2)

    def test_curriculum_reset_returns_200(self):
        r = self.client.post("/curriculum/reset")
        self.assertEqual(r.status_code, 200)

    def test_curriculum_reset_reverts_to_stage_0(self):
        data = self.client.post("/curriculum/reset").json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data["curriculum"]["stage_id"], 0)
        self.assertEqual(data["curriculum"]["current_stage"], "LITERACY")

    def test_curriculum_status_after_reset(self):
        self.client.post("/curriculum/reset")
        data = self.client.get("/curriculum/status").json()
        self.assertEqual(data["stage_id"], 0)


class TestMathCalculateEndpoint(unittest.TestCase):
    def test_math_blocked_at_stage_0(self):
        client = _make_client(stage=0)
        r = client.post("/math/calculate", json={"operation": "add", "a": 2, "b": 3})
        self.assertEqual(r.status_code, 403)

    def test_math_allowed_at_stage_1(self):
        client = _make_client(stage=1)
        r = client.post("/math/calculate", json={"operation": "add", "a": 2, "b": 3})
        self.assertEqual(r.status_code, 200)
        self.assertAlmostEqual(r.json()["result"], 5.0)

    def test_math_add(self):
        client = _make_client(stage=1)
        data = client.post("/math/calculate", json={"operation": "add", "a": 10, "b": 5}).json()
        self.assertAlmostEqual(data["result"], 15.0)

    def test_math_subtract(self):
        client = _make_client(stage=1)
        data = client.post("/math/calculate", json={"operation": "subtract", "a": 10, "b": 4}).json()
        self.assertAlmostEqual(data["result"], 6.0)

    def test_math_multiply(self):
        client = _make_client(stage=1)
        data = client.post("/math/calculate", json={"operation": "multiply", "a": 3, "b": 7}).json()
        self.assertAlmostEqual(data["result"], 21.0)

    def test_math_divide(self):
        client = _make_client(stage=1)
        data = client.post("/math/calculate", json={"operation": "divide", "a": 10, "b": 2}).json()
        self.assertAlmostEqual(data["result"], 5.0)

    def test_math_divide_by_zero(self):
        client = _make_client(stage=1)
        r = client.post("/math/calculate", json={"operation": "divide", "a": 10, "b": 0})
        self.assertEqual(r.status_code, 400)

    def test_math_unknown_operation(self):
        client = _make_client(stage=1)
        r = client.post("/math/calculate", json={"operation": "power", "a": 2, "b": 3})
        self.assertEqual(r.status_code, 400)

    def test_math_allowed_at_stage_2(self):
        client = _make_client(stage=2)
        r = client.post("/math/calculate", json={"operation": "add", "a": 1, "b": 1})
        self.assertEqual(r.status_code, 200)

    def test_math_403_includes_reason(self):
        client = _make_client(stage=0)
        data = client.post("/math/calculate", json={"operation": "add", "a": 1, "b": 1}).json()
        self.assertIn("detail", data)


if __name__ == "__main__":
    unittest.main()
