"""Autonomic Curriculum Controller (ACC).

Manages the system's learning stage and enforces prerequisite gates for
restricted operations.  Stage progression is strictly monotonic — the stage
can only increase automatically; a manual :meth:`reset` reverts to stage 0.

State machine
-------------
  Stage 0 – LITERACY   : min_concepts= 5, allows_arithmetic=False
  Stage 1 – NUMERACY   : min_concepts=15, allows_arithmetic=True
  Stage 2 – REASONING  : min_concepts=30, allows_arithmetic=True, allows_abstraction=True

Progression conditions (both must hold to advance)
---------------------------------------------------
  A. Density   : learned concept count >= next-stage min_concepts threshold
  B. Stability : recent average JEPA prediction error <= error_tolerance
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Stage definitions ────────────────────────────────────────────────────────

STAGE_DEFINITIONS: list[dict] = [
    {
        "id": 0,
        "label": "LITERACY",
        "min_concepts": 5,
        "allows_arithmetic": False,
        "allows_abstraction": False,
    },
    {
        "id": 1,
        "label": "NUMERACY",
        "min_concepts": 15,
        "allows_arithmetic": True,
        "allows_abstraction": False,
    },
    {
        "id": 2,
        "label": "REASONING",
        "min_concepts": 30,
        "allows_arithmetic": True,
        "allows_abstraction": True,
    },
]

# Minimum curriculum stage required per task type
TASK_REQUIRED_STAGE: dict[str, int] = {
    "arithmetic": 1,
    "abstraction": 2,
}

MAX_STAGE = len(STAGE_DEFINITIONS) - 1

# Defaults
DEFAULT_ERROR_TOLERANCE = 0.5
DEFAULT_STABILITY_WINDOW = 20


# ─── Exceptions ───────────────────────────────────────────────────────────────

class PrerequisiteNotMetError(Exception):
    """Raised when an operation requires a higher curriculum stage."""

    def __init__(
        self,
        required_stage: int,
        current_stage: int,
        operation: str = "",
    ) -> None:
        self.required_stage = required_stage
        self.current_stage = current_stage
        self.operation = operation
        super().__init__(
            f"Operation '{operation}' requires curriculum stage {required_stage} "
            f"({STAGE_DEFINITIONS[required_stage]['label']}) but current stage is "
            f"{current_stage} ({STAGE_DEFINITIONS[current_stage]['label']})."
        )


# ─── Controller ───────────────────────────────────────────────────────────────

class CurriculumController:
    """Autonomic Curriculum Controller service.

    Usage
    -----
    Instantiate once and wire into the application.  Call
    :meth:`evaluate_progression` on every ``POST /learn/process`` invocation.
    Use :meth:`check_prerequisite` to gate restricted operations.
    """

    def __init__(
        self,
        error_tolerance: float = DEFAULT_ERROR_TOLERANCE,
        stability_window: int = DEFAULT_STABILITY_WINDOW,
    ) -> None:
        self.error_tolerance = error_tolerance
        self.stability_window = stability_window

        self.current_stage: int = 0
        self.last_stage_up_time: Optional[float] = None
        self._blocking_reason: Optional[str] = None

    # ─── Stage helpers ────────────────────────────────────────────────────────

    @property
    def stage_def(self) -> dict:
        """Return the definition dict for the current stage."""
        return STAGE_DEFINITIONS[self.current_stage]

    @property
    def stage_label(self) -> str:
        """Return the label string of the current stage."""
        return self.stage_def["label"]

    # ─── Progression ─────────────────────────────────────────────────────────

    def evaluate_progression(
        self,
        concept_count: int,
        recent_errors: list[float],
    ) -> dict:
        """Evaluate whether the system should advance to the next stage.

        Parameters
        ----------
        concept_count:
            Number of concepts learned (length of ``ConceptLearner.learn()``).
        recent_errors:
            Recent JEPA MSE losses from the last *N* update calls.

        Returns
        -------
        dict
            ``advanced``  – True if the stage was incremented.
            ``blocked``   – True if density is met but stability is not.
            ``reason``    – Human-readable explanation.
        """
        if self.current_stage >= MAX_STAGE:
            self._blocking_reason = None
            return {
                "advanced": False,
                "blocked": False,
                "reason": "Already at maximum stage.",
            }

        next_def = STAGE_DEFINITIONS[self.current_stage + 1]
        required_concepts = next_def["min_concepts"]

        # Condition A: density
        density_met = concept_count >= required_concepts

        # Condition B: stability (JEPA damper)
        avg_error = float(sum(recent_errors) / len(recent_errors)) if recent_errors else 0.0
        stability_met = avg_error <= self.error_tolerance

        if density_met and stability_met:
            self.current_stage += 1
            self.last_stage_up_time = time.time()
            self._blocking_reason = None
            logger.info(
                "Curriculum advanced to stage %d (%s). "
                "concepts=%d avg_jepa_error=%.4f",
                self.current_stage,
                self.stage_label,
                concept_count,
                avg_error,
            )
            return {
                "advanced": True,
                "blocked": False,
                "reason": f"Advanced to {self.stage_label}.",
                "avg_jepa_error": avg_error,
            }

        if density_met:
            # Density met but JEPA still unstable — block and record reason
            reason = (
                f"High latent uncertainty: avg JEPA error={avg_error:.4f} "
                f"> tolerance={self.error_tolerance:.4f}."
            )
            self._blocking_reason = reason
            logger.warning("Curriculum progression blocked. %s", reason)
            return {"advanced": False, "blocked": True, "reason": reason, "avg_jepa_error": avg_error}

        # Density not yet met
        reason = (
            f"Density not met: {concept_count}/{required_concepts} concepts "
            f"required for {next_def['label']}."
        )
        self._blocking_reason = None
        return {"advanced": False, "blocked": False, "reason": reason, "avg_jepa_error": avg_error}

    # ─── Prerequisite gate ────────────────────────────────────────────────────

    def check_prerequisite(self, task: str) -> None:
        """Raise :exc:`PrerequisiteNotMetError` if *task* requires a higher stage.

        Parameters
        ----------
        task:
            Task identifier.  Known keys: ``"arithmetic"``, ``"abstraction"``.
        """
        required = TASK_REQUIRED_STAGE.get(task, 0)
        if self.current_stage < required:
            raise PrerequisiteNotMetError(
                required_stage=required,
                current_stage=self.current_stage,
                operation=task,
            )

    # ─── Observability ────────────────────────────────────────────────────────

    def get_abstraction_gate(self) -> bool:
        """Return True only if current stage allows abstraction (stage >= 2)."""
        return self.current_stage >= 2

    def get_status_report(self, concept_count: int = 0) -> dict:
        """Return a full status report dict, including progress percentage.

        Parameters
        ----------
        concept_count:
            Current learned concept count for progress percentage calculation.
        """
        if self.current_stage < MAX_STAGE:
            next_threshold = STAGE_DEFINITIONS[self.current_stage + 1]["min_concepts"]
        else:
            next_threshold = self.stage_def["min_concepts"]

        progress_pct = min(100.0, (concept_count / max(next_threshold, 1)) * 100.0)

        return {
            "current_stage": self.stage_label,
            "stage_id": self.current_stage,
            "progress_percentage": round(progress_pct, 2),
            "blocking_status": self._blocking_reason is not None,
            "blocking_reason": self._blocking_reason,
            "last_stage_up_time": self.last_stage_up_time,
            "stage_definitions": STAGE_DEFINITIONS,
            "allows_abstraction": self.get_abstraction_gate(),
        }

    # ─── Reset ────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Manually revert the curriculum back to stage 0 (LITERACY)."""
        self.current_stage = 0
        self.last_stage_up_time = None
        self._blocking_reason = None
        logger.info("Curriculum reset to stage 0 (LITERACY).")

    # ─── Persistence ──────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Persist curriculum state to a JSON file."""
        data = {
            "current_stage": self.current_stage,
            "last_stage_up_time": self.last_stage_up_time,
            "error_tolerance": self.error_tolerance,
            "stability_window": self.stability_window,
        }
        Path(path).write_text(json.dumps(data, indent=2))
        logger.info("Curriculum state saved to %s", path)

    def load(self, path: str | Path) -> None:
        """Restore curriculum state from a JSON file.

        Raises :exc:`FileNotFoundError` if *path* does not exist.
        """
        data = json.loads(Path(path).read_text())
        self.current_stage = int(data.get("current_stage", 0))
        self.last_stage_up_time = data.get("last_stage_up_time")
        self.error_tolerance = float(
            data.get("error_tolerance", DEFAULT_ERROR_TOLERANCE)
        )
        self.stability_window = int(
            data.get("stability_window", DEFAULT_STABILITY_WINDOW)
        )
        logger.info(
            "Curriculum state loaded from %s (stage=%d %s)",
            path,
            self.current_stage,
            self.stage_label,
        )
