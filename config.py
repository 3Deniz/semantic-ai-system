"""Central configuration for the Semantic AI Decision Engine."""

# =========================
# ✅ ACTIONS
ACTIONS = ["barrier", "release", "evacuate", "none"]

# Action cost penalties applied to the Q-learning reward
ACTION_COST = {
    "barrier": -0.06,
    "release": -0.02,
    "evacuate": -0.05,
    "none": 0,
}

# =========================
# ✅ RL TRAINING HYPERPARAMETERS
ALPHA = 0.1           # Q-learning rate
GAMMA = 0.9           # discount factor
EPSILON = 0.25        # initial exploration probability
EPSILON_DECAY = 0.999 # per-episode epsilon decay multiplier
TRAIN_EPISODES = 5000
STEPS_PER_EPISODE = 12

# =========================
# ✅ ENVIRONMENT / WORLD DYNAMICS
RAIN_PROBABILITY = 0.7          # P(rain) at episode reset
RAIN_FLOOD_PROBABILITY = 0.8    # P(flood | rain, no barrier)
FLOOD_DAMAGE_PROBABILITY = 0.5  # P(damage | flood) — used in main.py step_world
DAMAGE_COLLAPSE_PROBABILITY = 0.4
COLLAPSE_CRISIS_PROBABILITY = 0.3
RAIN_CLEAR_PROBABILITY = 0.3
RELEASE_FLOOD_CLEAR_PROBABILITY = 0.7
# P(evacuated state clears back to normal each step) — models real-world return-to-normal
EVACUATED_RETURN_PROBABILITY = 0.2

# =========================
# ✅ POLICY EXPORT
POLICY_FILE = "policy.json"
POLICY_CONFIDENCE_THRESHOLD = 0.7  # min action-frequency ratio to include in policy

# =========================
# ✅ JEPA
JEPA_WARMUP_EPOCHS = 3           # number of offline training passes over the Q-table
JEPA_WARMUP_SIMS_PER_KEY = 2     # simulations per (state, action) key during warmup
JEPA_WEIGHTS_FILE = "jepa_weights.npz"  # persisted model weights (NumPy compressed archive)

# =========================
# ✅ CURRICULUM
CURRICULUM_STATE_FILE = "curriculum_state.json"   # persisted curriculum stage
CURRICULUM_ERROR_TOLERANCE = 0.5                  # max avg JEPA loss to allow stage advance
CURRICULUM_STABILITY_WINDOW = 20                  # number of recent JEPA updates to average
API_HOST = "127.0.0.1"
API_PORT = 8000

# =========================
# ✅ INGEST AUTHENTICATION
# Set the INGEST_API_KEY environment variable to require an X-API-Key header on
# all POST /ingest/* requests.  When the variable is unset the endpoints are
# unauthenticated (development mode).
import os
INGEST_API_KEY: str | None = os.environ.get("INGEST_API_KEY")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

# =========================
# ✅ SEMANTIC STACK
GRAPH_FILE = "graph.json"
TMS_DECAY_RATE = 0.95
TMS_MIN_CONFIDENCE = 0.3

# =========================
# ✅ PDF INGEST
PDF_MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
PDF_MAX_BATCH_FILES = 10
PDF_MAX_BATCH_TOTAL_BYTES = 100 * 1024 * 1024

# =========================
# ✅ FEATURE FLAGS / OPERATIONS
ENABLE_PDF_INGEST = _env_bool("ENABLE_PDF_INGEST", True)
ENABLE_SPACE_RELATIONS = _env_bool("ENABLE_SPACE_RELATIONS", True)
ENABLE_SPACY_DEP_PARSER = _env_bool("ENABLE_SPACY_DEP_PARSER", False)
SPACY_MODEL_NAME = os.environ.get("SPACY_MODEL_NAME", "en_core_web_sm")

# Ingest API simple in-memory rate limit
INGEST_RATE_LIMIT_MAX_REQUESTS = int(os.environ.get("INGEST_RATE_LIMIT_MAX_REQUESTS", "60"))
INGEST_RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("INGEST_RATE_LIMIT_WINDOW_SECONDS", "60"))

# =========================
# ✅ JEPA EARLY STOPPING
JEPA_EARLY_STOPPING_LOSS = float(os.environ.get("JEPA_EARLY_STOPPING_LOSS", "0.0001"))
JEPA_EARLY_STOPPING_PATIENCE = int(os.environ.get("JEPA_EARLY_STOPPING_PATIENCE", "2"))

# =========================
# ✅ PARSER ENHANCEMENTS
ENABLE_ENHANCED_NEGATION = _env_bool("ENABLE_ENHANCED_NEGATION", True)

# =========================
# ✅ PERFORMANCE TUNING
KG_INDEX_CACHE_SIZE = int(os.environ.get("KG_INDEX_CACHE_SIZE", "10000"))
THREAD_POOL_SIZE = int(os.environ.get("THREAD_POOL_SIZE", "4"))
