"""JEPA — Joint Embedding Predictive Architecture (numpy implementation).

Architecture
------------
Given a (state, action) context and the resulting next_state, JEPA learns to
predict the *latent representation* of next_state from the context embedding,
following the I-JEPA design principle:

  context encoder  enc_ctx : (state ‖ action_one_hot) [11] → latent [7]
  target  encoder  enc_tgt : next_state              [ 7] → latent [7]
      • enc_tgt is kept as an EMA copy of enc_ctx's state columns so that
        predictions and targets live in the same representation space.
  predictor          pred   : latent [7] → latent [7]

Training loss  : MSE( pred(enc_ctx(s, a)),  stop_grad(enc_tgt(s')) )
EMA update     : enc_tgt ← τ · enc_tgt + (1−τ) · enc_ctx[:, :STATE_DIM]

Scoring
-------
A predicted next-state latent that resembles an empty / safe state receives a
high score.  The safe reference is enc_tgt(zero_vec) — the encoding of a state
with no active risk flags.

Dimensions
----------
STATE_DIM   = 7   (flood, collapse, crisis, damage, barrier, evacuated, temporal)
ACTION_DIM  = 4   (barrier, release, evacuate, none)
CONTEXT_DIM = 11
LATENT_DIM  = 7   (same as STATE_DIM for interpretable risk-feature alignment)
"""

from __future__ import annotations

import numpy as np
from pathlib import Path

# ─────────────────────────────────────────────
# Hyper-parameters
STATE_DIM   = 7
ACTION_DIM  = 4
CONTEXT_DIM = STATE_DIM + ACTION_DIM   # 11
LATENT_DIM  = STATE_DIM                # 7

LR          = 0.01    # SGD learning rate
EMA_DECAY   = 0.99    # target encoder momentum
MIN_SAMPLES = 100     # samples required before model is considered trained


class JEPAModel:
    """Lightweight JEPA model trained purely with NumPy."""

    def __init__(self, seed: int = 42) -> None:
        rng = np.random.default_rng(seed)
        scale = 0.05

        # Context encoder  W_ctx: (LATENT_DIM × CONTEXT_DIM)
        self.W_ctx: np.ndarray = rng.standard_normal((LATENT_DIM, CONTEXT_DIM)) * scale
        self.b_ctx: np.ndarray = np.zeros(LATENT_DIM)

        # Target encoder  W_tgt: (LATENT_DIM × STATE_DIM) — EMA shadow of W_ctx[:, :STATE_DIM]
        self.W_tgt: np.ndarray = self.W_ctx[:, :STATE_DIM].copy()
        self.b_tgt: np.ndarray = self.b_ctx.copy()

        # Predictor  W_pred: (LATENT_DIM × LATENT_DIM)
        self.W_pred: np.ndarray = np.eye(LATENT_DIM) + rng.standard_normal((LATENT_DIM, LATENT_DIM)) * scale
        self.b_pred: np.ndarray = np.zeros(LATENT_DIM)

        self._trained_samples: int = 0

        # Cached encoding of the safe (all-zero) state for scoring
        self._safe_latent: np.ndarray = self._encode_target(np.zeros(STATE_DIM))

    # ─── Private helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _relu(x: np.ndarray) -> np.ndarray:
        return np.maximum(0.0, x)

    def _encode_ctx(self, state_vec: np.ndarray, action_idx: int) -> np.ndarray:
        one_hot = np.zeros(ACTION_DIM)
        one_hot[action_idx] = 1.0
        x = np.concatenate([state_vec, one_hot])
        return self._relu(self.W_ctx @ x + self.b_ctx)

    def _encode_target(self, state_vec: np.ndarray) -> np.ndarray:
        return self._relu(self.W_tgt @ state_vec + self.b_tgt)

    def _predict(self, ctx_latent: np.ndarray) -> np.ndarray:
        return self.W_pred @ ctx_latent + self.b_pred

    # ─── Public API ───────────────────────────────────────────────────────────

    def update(
        self,
        state_vec: np.ndarray,
        action_idx: int,
        next_state_vec: np.ndarray,
    ) -> float:
        """One SGD step.  Returns the scalar MSE loss for this sample."""
        ctx    = self._encode_ctx(state_vec, action_idx)
        pred   = self._predict(ctx)
        target = self._encode_target(next_state_vec)   # stop-gradient side

        err = pred - target                             # shape (LATENT_DIM,)
        loss = float(np.mean(err ** 2))

        # ── Predictor gradients ──────────────────────────────────────────────
        dW_pred = np.outer(err, ctx)
        db_pred = err.copy()
        d_ctx   = self.W_pred.T @ err

        # ── Context encoder gradients (through ReLU) ─────────────────────────
        d_ctx_pre = d_ctx * (ctx > 0)
        one_hot   = np.zeros(ACTION_DIM)
        one_hot[action_idx] = 1.0
        x_full    = np.concatenate([state_vec, one_hot])
        dW_ctx    = np.outer(d_ctx_pre, x_full)
        db_ctx    = d_ctx_pre.copy()

        # ── SGD updates ──────────────────────────────────────────────────────
        self.W_pred -= LR * dW_pred
        self.b_pred -= LR * db_pred
        self.W_ctx  -= LR * dW_ctx
        self.b_ctx  -= LR * db_ctx

        # ── EMA target encoder update ─────────────────────────────────────────
        self.W_tgt = EMA_DECAY * self.W_tgt + (1.0 - EMA_DECAY) * self.W_ctx[:, :STATE_DIM]
        self.b_tgt = EMA_DECAY * self.b_tgt + (1.0 - EMA_DECAY) * self.b_ctx

        self._trained_samples += 1

        # Refresh safe-state reference after encoder updates
        self._safe_latent = self._encode_target(np.zeros(STATE_DIM))

        return loss

    def predict_score(self, state_vec: np.ndarray, action_idx: int) -> float:
        """Score an action: higher is safer / more desirable.

        The predicted next-state latent is compared to the safe (zero-risk) latent.
        Proximity to the safe latent → positive score.
        """
        ctx        = self._encode_ctx(state_vec, action_idx)
        pred       = self._predict(ctx)
        dist       = float(np.linalg.norm(pred - self._safe_latent))
        return -dist   # less distance from safe state → higher score

    @property
    def is_trained(self) -> bool:
        return self._trained_samples >= MIN_SAMPLES

    # ─── Persistence ──────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Persist all model weights and sample counter to a compressed NumPy archive."""
        np.savez_compressed(
            path,
            W_ctx=self.W_ctx,
            b_ctx=self.b_ctx,
            W_tgt=self.W_tgt,
            b_tgt=self.b_tgt,
            W_pred=self.W_pred,
            b_pred=self.b_pred,
            trained_samples=np.array(self._trained_samples, dtype=np.int64),
        )

    def load(self, path: str | Path) -> None:
        """Restore model weights and sample counter from a compressed NumPy archive.

        Raises ``FileNotFoundError`` if *path* does not exist (let callers decide
        whether to treat a missing file as a first-run condition).
        """
        data = np.load(path)
        self.W_ctx = data["W_ctx"]
        self.b_ctx = data["b_ctx"]
        self.W_tgt = data["W_tgt"]
        self.b_tgt = data["b_tgt"]
        self.W_pred = data["W_pred"]
        self.b_pred = data["b_pred"]
        self._trained_samples = int(data["trained_samples"])
        # Refresh cached safe-state encoding after weight restore
        self._safe_latent = self._encode_target(np.zeros(STATE_DIM))
