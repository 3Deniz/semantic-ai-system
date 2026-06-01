from fastapi import FastAPI, Query, Security, HTTPException, status, UploadFile, File, Form
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import main
import json
import time
import random
import ast
import re
import threading
import logging
import shutil
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional, Any
import numpy as np
from config import (
    ACTIONS, GRAPH_FILE, TMS_DECAY_RATE, TMS_MIN_CONFIDENCE,
    JEPA_WARMUP_EPOCHS, JEPA_WARMUP_SIMS_PER_KEY,
    EVACUATED_RETURN_PROBABILITY, INGEST_API_KEY, JEPA_WEIGHTS_FILE,
    PDF_MAX_FILE_SIZE_BYTES, PDF_MAX_BATCH_FILES, PDF_MAX_BATCH_TOTAL_BYTES,
    ENABLE_PDF_INGEST, ENABLE_SPACE_RELATIONS,
    INGEST_RATE_LIMIT_MAX_REQUESTS, INGEST_RATE_LIMIT_WINDOW_SECONDS,
    ENABLE_SPACY_DEP_PARSER, SPACY_MODEL_NAME,
    CURRICULUM_STATE_FILE, CURRICULUM_ERROR_TOLERANCE, CURRICULUM_STABILITY_WINDOW,
    JEPA_EARLY_STOPPING_LOSS, JEPA_EARLY_STOPPING_PATIENCE,
)
from learning.jepa import JEPAModel, ACTION_DIM, STATE_DIM
from learning.curriculum import CurriculumController, PrerequisiteNotMetError
from cognition.thought_loop import ThoughtLoop

logger = logging.getLogger(__name__)

# =========================
# ✅ INGEST AUTHENTICATION

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _require_ingest_key(api_key: str | None = Security(_api_key_header)):
    """Dependency that enforces the ingest API key when INGEST_API_KEY is configured."""
    if INGEST_API_KEY is None:
        return  # auth disabled in development mode
    if api_key != INGEST_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-API-Key header.",
        )


# =========================
# ✅ SEMANTIC STACK
from core.parser import SemanticParser
from core.knowledge_graph import KnowledgeGraph
from core.tms import LiteTMS
from core.reasoning import Reasoner
from core.space_relations import SpaceRelationsBuilder, DEFAULT_SPACES
from learning.concept_learning import ConceptLearner
from learning.rule_learning import RuleLearner
from learning.online_learning import OnlineLearner
from memory.graph_store import GraphStore
from memory.concept_space_embeddings import ConceptSpaceEmbeddings
from core.number_parser import NumberParser
from core.pdf_ingestion import PDFIngestionError
from core.symbolic_math import compute_arithmetic, compute_calculus, compute_definite_integral, compute_derivative_advanced, compute_algebra, solve_equation
from core.symbolic_math import _format_number
from core.numeracy import (
    can_compute_expression,
    basic_numeracy_facts,
    detect_decimal_or_fraction,
    CURRICULUM_PHASES,
    curriculum_phase_facts,
    get_completed_phases,
    get_numeracy_snapshot,
    missing_curriculum_phases,
    missing_prerequisite_phases,
    required_phases_for_arithmetic,
    required_phases_for_calculus,
    required_phases_for_logarithms,
)
from core.economy_curriculum import (
    ECONOMY_CURRICULUM_PHASES,
    build_economy_phase_metrics,
    economy_curriculum_phase_facts,
    economy_curriculum_status,
    get_completed_economy_phases,
    missing_economy_prerequisite_phases,
)
from core.primary_readiness import (
    build_primary_drip_plan,
    build_primary_readiness_report,
    build_primary_weekly_plan,
)

_kg = KnowledgeGraph()
_tms = LiteTMS(decay_rate=TMS_DECAY_RATE, min_confidence=TMS_MIN_CONFIDENCE)
_parser = SemanticParser(enable_spacy_dep=ENABLE_SPACY_DEP_PARSER, spacy_model_name=SPACY_MODEL_NAME)
_graph_store = GraphStore(GRAPH_FILE)
_concept_learner = ConceptLearner(_tms)
_rule_learner = RuleLearner(_tms)
_online_learner = OnlineLearner(_tms)
_kg.tms = _tms
_relations_builder = None

# =========================
# ✅ GLOBALS
_inference_lock = threading.Lock()
inference_count = 0
last_time = time.time()
recent_states = deque(maxlen=6)

# =========================
# ✅ JEPA MODEL
_jepa = JEPAModel()
_jepa_lock = threading.Lock()
_jepa_recent_errors: deque = deque(maxlen=CURRICULUM_STABILITY_WINDOW)
_thought_loop = None
_ingest_rate_lock = threading.Lock()
_ingest_rate_bucket: dict[str, deque] = defaultdict(deque)
_loop_artifact_lock = threading.Lock()
_loop_artifacts = deque(maxlen=200)
_training_pdf_archive_root = Path(__file__).resolve().parent / "artifacts" / "training_pdfs"
SEED_TXT_DIR = Path(__file__).resolve().parent / "artifacts" / "seed_texts"
_concept_space_embeddings = ConceptSpaceEmbeddings(Path(__file__).resolve().parent / "artifacts" / "concept_space_embeddings.json")


SPACE_BOOTSTRAP_PLAN = [
    {
        "stage": "language_literacy",
        "spaces": ["semantic", "curriculum"],
        "depends_on": [],
        "learning_actions": ["learn/curriculum/phase/letters"],
        "description": "Establish symbol-to-meaning grounding before any abstract manipulation.",
    },
    {
        "stage": "numeric_literacy",
        "spaces": ["arithmetic", "semantic", "curriculum"],
        "depends_on": ["language_literacy"],
        "learning_actions": ["learn/curriculum/phase/digits", "learn/curriculum/phase/operations", "learn/curriculum/phase/real_numbers"],
        "description": "Teach digits and operators so arithmetic cannot run without prerequisites.",
    },
    {
        "stage": "goal_and_risk_grounding",
        "spaces": ["goal", "risk", "semantic"],
        "depends_on": ["language_literacy"],
        "learning_actions": ["ingest rule facts with used_for / supports_goal / hazard relations"],
        "description": "Attach purpose and risk semantics independent from low-level mechanism details.",
    },
    {
        "stage": "memory_and_attention_context",
        "spaces": ["memory", "attention", "semantic", "emotion"],
        "depends_on": ["goal_and_risk_grounding"],
        "learning_actions": ["drip learning cycles", "reinforcement for abstraction pending concepts"],
        "description": "Stabilize recall and salience via repetition and context traces.",
    },
    {
        "stage": "advanced_symbolic_reasoning",
        "spaces": ["calculus", "arithmetic", "semantic", "curriculum"],
        "depends_on": ["numeric_literacy"],
        "learning_actions": ["learn/curriculum/phase/calculus", "learn/curriculum/phase/logarithms"],
        "description": "Enable higher-order symbolic reasoning only after numeric foundation is mastered.",
    },
]


def _safe_archive_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "uploaded.pdf").strip("._-")
    return cleaned or "uploaded.pdf"


def _archive_training_pdf(payload: bytes, *, source_document: str, metadata: dict | None = None) -> dict[str, object]:
    metadata = dict(metadata or {})
    phase = str(metadata.get("curriculum_phase") or "unclassified").strip().lower() or "unclassified"
    archive_dir = _training_pdf_archive_root / phase
    archive_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    filename = f"{timestamp}_{_safe_archive_name(source_document)}"
    archive_path = archive_dir / filename
    archive_path.write_bytes(payload)

    manifest = _training_pdf_archive_root / "manifest.jsonl"
    entry = {
        "timestamp": time.time(),
        "phase": phase,
        "source_document": source_document,
        "path": str(archive_path.relative_to(_training_pdf_archive_root)),
        "bytes": len(payload),
        "metadata": metadata,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True) + "\n")

    return entry


def _inject_curriculum_phase(phase: str, *, source_document: str, source_type: str = "curriculum") -> int:
    injected = 0
    for fact in curriculum_phase_facts(phase):
        try:
            fact_meta = {
                "source_type": source_type,
                "source_document": source_document or fact.get("source_document", "math_foundation_curriculum"),
                "timestamp": time.time(),
                "stage": "validated",
                "curriculum_phase": phase,
            }
            _kg.add(
                fact["subject"],
                fact["relation"],
                fact["object"],
                float(fact.get("confidence", 1.0)),
                fact_meta,
            )
            _update_concept_space_embeddings_from_fact(
                str(fact["subject"]),
                str(fact["relation"]),
                str(fact["object"]),
                float(fact.get("confidence", 1.0)),
                fact_meta,
            )
            injected += 1
        except Exception:
            continue
    return injected


def _resolve_curriculum_track(track_hint: str | None, phase: str) -> str:
    track = str(track_hint or "").strip().lower()
    if track in {"", "math", "curriculum"}:
        if phase in CURRICULUM_PHASES:
            return "math"
        if phase in ECONOMY_CURRICULUM_PHASES:
            return "economy"
        raise HTTPException(status_code=400, detail=f"Unknown curriculum_phase: {phase}")
    if track == "economy":
        if phase not in ECONOMY_CURRICULUM_PHASES:
            raise HTTPException(status_code=400, detail=f"Unknown economy curriculum_phase: {phase}")
        return "economy"
    raise HTTPException(status_code=400, detail=f"Unknown curriculum_track: {track_hint}")


def _track_completed_phases(track: str) -> set[str]:
    if track == "economy":
        return get_completed_economy_phases(_kg)
    return get_completed_phases(_kg)


def _track_missing_prerequisite_phases(track: str, completed: set[str], phase: str) -> list[str]:
    if track == "economy":
        return missing_economy_prerequisite_phases(completed, phase)
    return missing_prerequisite_phases(completed, phase)


def _track_phase_facts(track: str, phase: str) -> list[dict]:
    if track == "economy":
        return economy_curriculum_phase_facts(phase)
    return curriculum_phase_facts(phase)


def _inject_track_phase(track: str, phase: str, *, source_document: str, source_type: str = "curriculum") -> int:
    injected = 0
    for fact in _track_phase_facts(track, phase):
        try:
            fact_meta = {
                "source_type": source_type,
                "source_document": source_document or fact.get("source_document", "curriculum"),
                "timestamp": time.time(),
                "stage": "validated",
                "curriculum_phase": phase,
                "curriculum_track": track,
            }
            _kg.add(
                fact["subject"],
                fact["relation"],
                fact["object"],
                float(fact.get("confidence", 1.0)),
                fact_meta,
            )
            _update_concept_space_embeddings_from_fact(
                str(fact["subject"]),
                str(fact["relation"]),
                str(fact["object"]),
                float(fact.get("confidence", 1.0)),
                fact_meta,
            )
            injected += 1
        except Exception:
            continue
    return injected


def _build_curriculum_phase_metrics() -> list[dict[str, object]]:
    completed = get_completed_phases(_kg)
    snapshot = get_numeracy_snapshot(_kg)
    letter_count = sum(
        1
        for s, r, _o, _c in getattr(_kg, "triples", [])
        if str(s).lower() == "numeracy" and str(r).lower() == "knows_letter"
    )
    phase_knowledge = {
        "letters": letter_count,
        "digits": len(snapshot.get("digits", set())),
        "operations": len(snapshot.get("symbols", set()) & {"+", "-", "*", "/", "(", ")"}),
        "real_numbers": len((snapshot.get("symbols", set()) & {".", "/"}) | (snapshot.get("concepts", set()) & {"decimal", "fraction", "real"})),
        "calculus": len(snapshot.get("concepts", set()) & {"derivative", "integral", "limit", "function"}),
        "logarithms": len(snapshot.get("concepts", set()) & {"logarithm", "log", "ln", "base", "change_of_base", "exponent", "inverse_function"}),
    }

    metrics: list[dict[str, object]] = []
    for phase in CURRICULUM_PHASES:
        metrics.append({
            "phase": phase,
            "completed": phase in completed,
            "missing_prerequisites": missing_prerequisite_phases(completed, phase),
            "knowledge_count": int(phase_knowledge.get(phase, 0)),
        })
    return metrics


def _fact_to_debug_entry(fact: dict) -> dict[str, object]:
    return {
        "subject": fact.get("subject"),
        "relation": fact.get("relation"),
        "object": fact.get("object"),
        "confidence": float(fact.get("confidence", 1.0)),
        "source_type": fact.get("source_type", "curriculum"),
        "source_document": fact.get("source_document", ""),
    }


def _curriculum_debug_payload(*, phase: str, facts: list[dict], completed_before: list[str], completed_after: list[str], extra: dict | None = None, phase_metrics: list[dict[str, object]] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "phase": phase,
        "taught_facts": [_fact_to_debug_entry(fact) for fact in facts],
        "completed_before": completed_before,
        "completed_after": completed_after,
        "phase_metrics": phase_metrics if phase_metrics is not None else _build_curriculum_phase_metrics(),
    }
    if extra:
        payload.update(extra)
    return payload


def _archive_pdf_if_needed(payload: bytes, *, source_document: str, metadata: dict | None = None) -> dict[str, object] | None:
    metadata = dict(metadata or {})
    if not metadata.get("curriculum_phase") and not metadata.get("teach_curriculum"):
        return None
    try:
        return _archive_training_pdf(payload, source_document=source_document, metadata=metadata)
    except Exception:
        logger.exception("Failed to archive training PDF")
        return None


def _normalize_teaching_fact(fact: dict) -> dict:
    """Normalize optional teaching semantics for fact-level confidence policy.

    - teaching_kind=rule: keep confidence high (>=0.95)
    - teaching_kind=concept_seed/concept_only: keep concept confidence low (<=0.6)
      and mark abstraction_pending=True until reinforced later.
    """
    payload = dict(fact or {})
    relation = str(payload.get("relation", "")).strip().lower()
    teaching_kind = str(payload.get("teaching_kind", "")).strip().lower()
    metadata = dict(payload.get("metadata") or {})

    try:
        confidence = float(payload.get("confidence", 1.0))
    except Exception:
        confidence = 1.0

    if teaching_kind == "rule":
        payload["confidence"] = max(confidence, 0.95)
        metadata.setdefault("teaching_kind", "rule")
        metadata["abstraction_pending"] = False
    elif teaching_kind in {"concept_seed", "concept_only"}:
        if relation == "knows_concept":
            payload["confidence"] = min(confidence, 0.6)
        else:
            payload["confidence"] = confidence
        metadata.setdefault("teaching_kind", "concept_seed")
        metadata["abstraction_pending"] = True
    else:
        payload["confidence"] = confidence

    if metadata:
        payload.pop("metadata", None)
        payload.update(metadata)
    return payload


def _spaces_for_fact(subject: str, relation: str, obj: str, metadata: dict | None = None) -> list[str]:
    """Infer which spaces should receive concept embedding updates for a fact."""
    s = str(subject).lower()
    r = str(relation).lower()
    o = str(obj).lower()
    m = dict(metadata or {})

    spaces: set[str] = {"semantic"}
    joined = f"{s} {r} {o}"

    if s in {"curriculum", "numeracy", "economy_curriculum"} or m.get("curriculum_phase") or m.get("curriculum_track"):
        spaces.add("curriculum")
    if s in {"arithmetic", "numeracy"}:
        spaces.add("arithmetic")
    if r in {"equals", "lhs", "rhs", "models_expression"} or any(op in joined for op in ("+", "-", "*", "/", "multiply", "divide", "plus", "minus")):
        spaces.add("arithmetic")
    if r in {"derivative", "integral", "logarithm", "produces", "applies_operator", "on_expression"} or any(t in joined for t in ("integral", "derivative", "log", "ln", "dx")):
        spaces.add("calculus")
    if r in {"prioritizes", "applies_to", "goal_for", "supports_goal", "used_for", "serves", "purpose", "enables", "uses"}:
        spaces.add("goal")
    if r in {"threat_signal", "describes_risk", "hazard", "danger", "risk_for"}:
        spaces.add("risk")
    if r in {"recalls_state", "similar_failure"}:
        spaces.add("memory")

    hint_value = m.get("space_hint") or m.get("spaces") or m.get("source_space")
    hinted: list[str] = []
    if isinstance(hint_value, str):
        hinted = [part.strip().lower() for part in hint_value.split(",") if part.strip()]
    elif isinstance(hint_value, list):
        hinted = [str(part).strip().lower() for part in hint_value if str(part).strip()]
    for item in hinted:
        if item in set(DEFAULT_SPACES):
            spaces.add(item)

    return sorted(spaces)


def _update_concept_space_embeddings_from_fact(subject: str, relation: str, obj: str, confidence: float, metadata: dict | None = None) -> None:
    """Persist per-concept embeddings across relevant spaces for the object concept."""
    if str(relation).lower() != "knows_concept":
        return
    spaces = _spaces_for_fact(subject, relation, obj, metadata)
    _concept_space_embeddings.update_from_fact(
        concept=str(obj),
        spaces=spaces,
        subject=str(subject),
        relation=str(relation),
        obj=str(obj),
        confidence=float(confidence),
    )


def _matches_concept_token(value: str, concept: str, concept_tokens: set[str]) -> bool:
    text = str(value or "").lower()
    if text == concept:
        return True
    tokens = _tokenize_query(text)
    if concept in tokens:
        return True
    return bool(tokens & concept_tokens)


def _build_concept_trace(concept: str, *, max_depth: int = 3, max_edges: int = 250) -> dict[str, object]:
    normalized = str(concept).strip().lower()
    concept_tokens = _tokenize_query(normalized)

    facts: list[dict[str, object]] = []
    for s, r, o, c in getattr(_kg, "triples", []):
        if not (
            _matches_concept_token(str(s), normalized, concept_tokens)
            or _matches_concept_token(str(o), normalized, concept_tokens)
        ):
            continue
        metadata = dict(_kg.get_metadata(s, r, o) or {})
        spaces = _spaces_for_fact(str(s), str(r), str(o), metadata)
        facts.append({
            "triple": [str(s), str(r), str(o)],
            "confidence": float(c),
            "spaces": spaces,
            "metadata": metadata,
        })

    builder = _get_relations_builder()
    relations = builder.build(
        query=normalized,
        include_spaces=list(DEFAULT_SPACES),
        max_depth=max_depth,
        max_edges=max_edges,
    )
    relation_edges = [
        {
            "source": str(edge.get("source", "")),
            "target": str(edge.get("target", "")),
            "space": str(edge.get("space", "")),
            "relation_type": str(edge.get("relation_type", "")),
            "confidence": float(edge.get("confidence", 0.0)),
            "provenance": edge.get("provenance", {}),
        }
        for edge in relations.get("edges", [])
    ]

    by_space: dict[str, dict[str, object]] = {}

    def ensure_space(space: str) -> dict[str, object]:
        if space not in by_space:
            by_space[space] = {
                "space": space,
                "facts": [],
                "relation_edges": [],
                "avg_fact_confidence": 0.0,
                "avg_edge_confidence": 0.0,
            }
        return by_space[space]

    for fact in facts:
        for space in fact.get("spaces", []) or ["semantic"]:
            bucket = ensure_space(str(space))
            bucket["facts"].append(fact)

    for edge in relation_edges:
        space = str(edge.get("space", "semantic")) or "semantic"
        bucket = ensure_space(space)
        bucket["relation_edges"].append(edge)

    for bucket in by_space.values():
        fact_conf = [float(item.get("confidence", 0.0)) for item in bucket.get("facts", [])]
        edge_conf = [float(item.get("confidence", 0.0)) for item in bucket.get("relation_edges", [])]
        bucket["avg_fact_confidence"] = round(sum(fact_conf) / max(1, len(fact_conf)), 4)
        bucket["avg_edge_confidence"] = round(sum(edge_conf) / max(1, len(edge_conf)), 4)

    return {
        "concept": normalized,
        "embeddings": _concept_space_embeddings.get_concept(normalized),
        "facts": facts,
        "relation_edges": relation_edges,
        "spaces": sorted(by_space.values(), key=lambda item: item.get("space", "")),
    }


def _list_pending_abstractions(limit: int = 100) -> list[dict[str, object]]:
    pending: list[dict[str, object]] = []
    for s, r, o, c in getattr(_kg, "triples", []):
        if str(r).lower() != "knows_concept":
            continue
        metadata = dict(_kg.get_metadata(s, r, o) or {})
        if not bool(metadata.get("abstraction_pending")):
            continue
        pending.append({
            "subject": str(s),
            "concept": str(o),
            "confidence": float(c),
            "metadata": metadata,
        })

    pending.sort(key=lambda item: (float(item.get("confidence", 1.0)), str(item.get("concept", ""))))
    return pending[: max(1, int(limit))]


def _resolve_pending_abstractions(*, limit: int = 25, reinforcement_confidence: float = 0.95) -> dict[str, object]:
    pending = _list_pending_abstractions(limit=limit)
    resolved = 0
    timestamp = time.time()
    items: list[dict[str, object]] = []

    for item in pending:
        subject = str(item["subject"])
        concept = str(item["concept"])
        fact_meta = {
            "source_type": "abstraction_resolution",
            "source_document": "pending_abstraction_resolver",
            "timestamp": timestamp,
            "stage": "validated",
            "teaching_kind": "rule",
            "learning_mode": "reinforcement",
            "abstraction_pending": False,
        }
        _kg.add(
            subject,
            "knows_concept",
            concept,
            float(reinforcement_confidence),
            fact_meta,
        )
        _update_concept_space_embeddings_from_fact(subject, "knows_concept", concept, float(reinforcement_confidence), fact_meta)
        resolved += 1
        items.append({"subject": subject, "concept": concept, "confidence": float(reinforcement_confidence)})

    return {
        "resolved": resolved,
        "items": items,
        "remaining_pending": len(_list_pending_abstractions(limit=10000)),
    }

# =========================
# ✅ CURRICULUM CONTROLLER
_curriculum = CurriculumController(
    error_tolerance=CURRICULUM_ERROR_TOLERANCE,
    stability_window=CURRICULUM_STABILITY_WINDOW,
)

# =========================
# ✅ SAFE STATE PARSER (CRITICAL FIX)
def parse_state(state):
    try:
        if isinstance(state, str):
            # ✅ graph: "('a','b'):action" fix
            if ":" in state:
                state = state.split(":")[0]

            return list(ast.literal_eval(state)) if state != "()" else []
        return list(state)
    except:
        s = str(state).replace("(", "").replace(")", "").replace("'", "").split(",")
        return [x.strip() for x in s if x.strip()]


def _require_feature(enabled: bool, feature_name: str) -> None:
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{feature_name} is disabled by feature flag.",
        )


def _check_ingest_rate_limit(route_name: str) -> None:
    now = time.time()
    window = float(INGEST_RATE_LIMIT_WINDOW_SECONDS)
    key = f"ingest:{route_name}"
    with _ingest_rate_lock:
        bucket = _ingest_rate_bucket[key]
        while bucket and (now - bucket[0]) > window:
            bucket.popleft()
        if len(bucket) >= INGEST_RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Ingest rate limit exceeded.",
            )
        bucket.append(now)


def _mask_value(value):
    if isinstance(value, str):
        lowered = value.lower()
        if any(token in lowered for token in ("api_key", "token", "secret", "password", "authorization")):
            return "***"
        if len(value) > 140:
            return value[:140] + "..."
        return value
    if isinstance(value, dict):
        return {str(k): _mask_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_value(v) for v in value]
    return value


def _log_ingest_event(event: str, route: str, payload: dict | None = None) -> None:
    logger.info(
        "INGEST_EVENT event=%s route=%s payload=%s",
        event,
        route,
        _mask_value(payload or {}),
    )

# =========================
# ✅ MULTISPACE EMBEDDING
def embed_state_multispace(state):
    s = parse_state(state)

    return {
        "risk": [
            int("flood" in s),
            int("collapse" in s),
            int("crisis" in s)
        ],
        "structure": [
            int("damage" in s),
            int("barrier" in s)
        ],
        "action": [
            int("evacuated" in s)
        ],
        "temporal": [len(recent_states)]
    }

# =========================
# ✅ JEPA STATE VECTOR HELPER

def _state_to_vec(state_set, step_in_episode: int = 0) -> np.ndarray:
    """Convert a state set (or anything parse_state can handle) to a
    7-dim float32 JEPA embedding vector.

    Dimensions match learning/jepa.py STATE_DIM = 7:
      [flood, collapse, crisis, damage, barrier, evacuated, threat_intensity]

    Uses threat intensity derived solely from the current state to preserve
    the Markov property (no cross-episode information leakage).
    """
    if not isinstance(state_set, set):
        state_set = set(parse_state(state_set))
    threat_tokens = ["flood", "collapse", "crisis", "damage"]
    threat_count = sum(1 for t in threat_tokens if t in state_set)
    threat_intensity = min(1.0, threat_count / 4.0)
    return np.array([
        float("flood"     in state_set),
        float("collapse"  in state_set),
        float("crisis"    in state_set),
        float("damage"    in state_set),
        float("barrier"   in state_set),
        float("evacuated" in state_set),
        threat_intensity,
    ], dtype=np.float32)

def _action_idx(action: str) -> int:
    return ACTIONS.index(action)

# =========================
# ✅ JEPA OFFLINE TRAINING
# Called once after RL training to warm-start the JEPA model on the
# state-action-nextstate transitions implied by the Q-table.

def _train_jepa_from_qtable(epochs: int = JEPA_WARMUP_EPOCHS,
                            target_loss: float = JEPA_EARLY_STOPPING_LOSS,
                            patience: int = JEPA_EARLY_STOPPING_PATIENCE) -> int:
    """Train JEPA on experiences derived from main.Q and simulate_outcome.

    For each (state, action) key in the Q-table we simulate
    JEPA_WARMUP_SIMS_PER_KEY next-state outcomes and train JEPA on the
    resulting triples.  The simulation is run ``epochs`` times over the
    whole key set to improve convergence.

    Supports early stopping when loss stabilises below ``target_loss``.

    Returns the total number of SGD updates performed.
    """
    keys = list({k[0] for k in main.Q.keys()})   # unique state tuples

    total = 0
    best_loss = float("inf")
    epochs_without_improvement = 0

    for epoch in range(epochs):
        random.shuffle(keys)
        epoch_loss = 0.0
        samples_in_epoch = 0

        for state_key in keys:
            state_set = set(state_key)
            s_vec = _state_to_vec(state_set)
            for action in ACTIONS:
                for _ in range(JEPA_WARMUP_SIMS_PER_KEY):
                    _, next_state = simulate_outcome(state_key, action)
                    ns_vec = _state_to_vec(set(next_state))
                    with _jepa_lock:
                        loss = _jepa.update(s_vec, _action_idx(action), ns_vec)
                    epoch_loss += loss
                    samples_in_epoch += 1
                    total += 1

        avg_loss = epoch_loss / max(1, samples_in_epoch)

        if avg_loss < target_loss:
            if avg_loss < best_loss - target_loss * 0.1:
                best_loss = avg_loss
                epochs_without_improvement = 0
            else:
                epochs_without_improvement += 1

            if epochs_without_improvement >= patience:
                print(f"[JEPA] Early stopping at epoch {epoch+1}, loss={avg_loss:.6f}")
                break
        else:
            epochs_without_improvement = 0

    return total

# =========================
# ✅ RANDOM BASELINE SCORER (kept for fallback when JEPA is not yet trained)
# _RANDOM_BASELINE_W is a fixed random matrix seeded at startup.
# It is NOT a learned model — it is used only until JEPA warms up.
_RANDOM_BASELINE_W = np.random.rand(7, 7)

def flatten_embedding(e):
    return np.array(e["risk"] + e["structure"] + e["action"] + e["temporal"])

def _random_baseline_predict(state):
    vec = flatten_embedding(embed_state_multispace(state))
    return np.dot(_RANDOM_BASELINE_W, vec)

def evaluate_actions_jepa(state):
    """Score each action using the JEPA model (or a random baseline fallback).

    When the JEPA model has been trained on enough samples it uses the learned
    predictive model: it encodes (state, action) and predicts the next-state
    latent, then scores how close that latent is to the safe (zero-risk) state.

    Before training completes the random baseline is used instead so that the
    hybrid engine can still operate during warm-up.
    """
    scores = {}
    s_vec = _state_to_vec(state)

    for action in ACTIONS:
        _, next_state = simulate_outcome(state, action)

        with _jepa_lock:
            jepa_ready = _jepa.is_trained

        if jepa_ready:
            with _jepa_lock:
                score = _jepa.predict_score(s_vec, _action_idx(action))
        else:
            pred = _random_baseline_predict(next_state)
            raw  = -sum(pred[:3]) / (len(pred[:3]) + 1e-5)
            score = max(min(raw, 5), -5)

        scores[action] = float(score)

    return scores

# =========================
# ✅ SIMULATION ENGINE (REALISTIC)

def simulate_outcome(state, action):
    s = set(parse_state(state))
    reward = 0

    # ✅ BASE COST
    if "flood" in s: reward -= 2
    if "damage" in s: reward -= 3
    if "collapse" in s: reward -= 6
    if "crisis" in s: reward -= 8

    # =========================
    # ✅ ACTIONS

    if action == "barrier":
        if "flood" in s and random.random() < 0.7:
            s.discard("flood")
            reward += 4

        if "damage" in s and random.random() < 0.5:
            s.discard("damage")
            reward += 2

    elif action == "release":
        if "flood" in s and random.random() < 0.6:
            s.discard("flood")
            reward += 3
        else:
            reward -= 2

    elif action == "evacuate":
        # ✅ survival priority
        reward += 8

        # ✅ remove major risks
        s = {x for x in s if x not in ["flood", "collapse", "crisis"]}

        s.add("evacuated")

        if random.random() < 0.15:
            reward -= 2
            s.add("injury")

    elif action == "none":
        reward -= 3

    # =========================
    # ✅ CASCADE

    if "flood" in s and random.random() < 0.4:
        s.add("damage")
        reward -= 2

    if "damage" in s and random.random() < 0.3:
        s.add("collapse")
        reward -= 3

    if "collapse" in s and random.random() < 0.3:
        s.add("crisis")
        reward -= 4

    # =========================
    # ✅ RECOVERY

    if "evacuated" in s:
        reward += 3
        # Probabilistic return to normal — mirrors step_world dynamics
        if random.random() < EVACUATED_RETURN_PROBABILITY:
            s.discard("evacuated")

    if not s:
        reward += 2

    return reward, tuple(sorted(s))

# =========================
# ✅ RULE ENGINE

def evaluate_actions(state):
    s = str(state).lower()
    scores = {}

    for action in ACTIONS:
        score = 0

        if "flood" in s:
            if action == "barrier": score += 3
            if action == "release": score += 1

        if "collapse" in s:
            if action == "evacuate": score += 4

        if "damage" in s:
            if action == "barrier": score += 1

        if "crisis" in s:
            if action == "evacuate": score += 5

        if action == "none":
            score -= 2

        scores[action] = score

    return scores

# =========================
# ✅ PLANNING

def plan_actions(state):
    results = {}

    for action in ACTIONS:
        total = sum(simulate_outcome(state, action)[0] for _ in range(5))
        results[action] = total / 5

    return results, max(results, key=results.get)

# =========================
# ✅ DETECT

def detect_trap(sim_scores):
    return all(score < 0 for score in sim_scores.values())

def calculate_risk(state):
    s = str(state).lower()
    risk = 0
    if "flood" in s: risk += 2
    if "damage" in s: risk += 3
    if "collapse" in s: risk += 5
    if "crisis" in s: risk += 7
    return risk

def calculate_conflicts():
    count = 0
    states = set(k[0] for k in main.Q.keys())

    for state in states:
        scores = [main.Q.get((state, a), 0) for a in ACTIONS]
        best = max(scores)
        strong = [s for s in scores if abs(best - s) < 0.5]
        if len(strong) > 1:
            count += 1

    return count

# =========================
# ✅ HYBRID DECISION

def hybrid_decision(state, return_diagnostics: bool = False, step: int = 0):
    global inference_count
    with _inference_lock:
        inference_count += 1

    parsed = parse_state(state)
    parsed_set = set(parsed)
    key = tuple(sorted(parsed))

    q_scores = {a: main.Q.get((key, a), 0) for a in ACTIONS}

    sim_scores, _ = plan_actions(state)
    jepa_scores = evaluate_actions_jepa(state)

    base_scores = {
        a: 0.6 * sim_scores[a] + 0.4 * q_scores[a]
        for a in ACTIONS
    }

    with _inference_lock:
        recent_states.append(key)

    if "collapse" in parsed or "crisis" in parsed:
        best = "evacuate"
    elif recent_states.count(key) > 2:
        best = random.choice(ACTIONS)
    else:
        vals = sorted(base_scores.values(), reverse=True)
        if len(vals) > 1 and abs(vals[0] - vals[1]) < 0.5:
            best = max(jepa_scores, key=jepa_scores.get)
        else:
            best = max(base_scores, key=base_scores.get)

    thought_trace = None
    if _thought_loop is not None:
        try:
            thought_trace = _thought_loop.think(parsed_set)
        except Exception:
            logger.exception("Thought loop decision failed")

    _jepa_online_update(parsed, best, step=step)

    if return_diagnostics:
        return base_scores, best, {
            "thought_trace": thought_trace,
        }
    return base_scores, best


def _jepa_online_update(parsed_state, action: str, step: int = 0) -> None:
    """Perform one online JEPA update for the chosen (state, action) transition."""
    try:
        s_vec = _state_to_vec(set(parsed_state), step_in_episode=step)
        _, next_state = simulate_outcome(parsed_state, action)
        ns_vec = _state_to_vec(set(next_state), step_in_episode=step)
        with _jepa_lock:
            loss = _jepa.update(s_vec, _action_idx(action), ns_vec)
        _jepa_recent_errors.append(loss)
    except Exception:
        logger.exception("JEPA online update failed")   # never let this crash the decision pipeline


def _build_thought_path(trace: dict) -> list[dict]:
    """Create a compact, ordered explanation of the thought pipeline."""
    candidates = list(trace.get("candidates", {}).items())
    top_candidates = [
        {
            "action": action,
            "score": info.get("score", 0),
            "projected_reward": info.get("projected_reward", 0),
        }
        for action, info in candidates[:2]
    ]
    tension = trace.get("tensions", [])
    leading_tension = tension[0] if tension else None

    path = [
        {
            "stage": "Perception",
            "detail": f"Parsed state: {', '.join(trace.get('state', [])) or 'empty'}",
            "data": trace.get("spaces", {}),
        },
        {
            "stage": "Memory",
            "detail": "Retrieved working memory, similar failures, and long-term patterns.",
            "data": trace.get("memory_context", {}),
        },
        {
            "stage": "Intent",
            "detail": f"Dominant goal: {trace.get('dominant_goal', 'task_completion')}",
            "data": trace.get("intent", []),
        },
        {
            "stage": "Conflict",
            "detail": trace.get("resolution", "No conflict resolution available."),
            "data": leading_tension,
        },
        {
            "stage": "Simulation",
            "detail": "Projected the strongest candidate actions.",
            "data": top_candidates,
        },
        {
            "stage": "Decision",
            "detail": f"Selected {trace.get('action', 'none')} with confidence {trace.get('confidence', 0):.2f}.",
            "data": {
                "jepa_surprise": trace.get("jepa_surprise", 0),
                "explanation": trace.get("explanation", []),
            },
        },
    ]
    return path


def _record_loop_artifacts(state, action: str, base_scores: dict, thought_trace: Optional[dict] = None) -> dict:
    """Validate and persist per-cycle thought + visualization artifacts."""
    parsed_state = parse_state(state)
    state_str = str(tuple(sorted(parsed_state)))

    trace = thought_trace
    if trace is None and _thought_loop is not None:
        try:
            trace = _thought_loop.think(set(parsed_state))
        except Exception:
            logger.exception("Loop thought generation failed")
            trace = None

    thought_path = _build_thought_path(trace) if trace else []

    visualization = {"nodes": [], "edges": []}
    if ENABLE_SPACE_RELATIONS:
        try:
            visualization = _get_relations_builder().build(
                state=state_str,
                include_spaces=list(DEFAULT_SPACES),
                max_depth=1,
                max_edges=150,
            )
        except Exception:
            logger.exception("Loop visualization generation failed")

    node_count = len(visualization.get("nodes", []))
    edge_count = len(visualization.get("edges", []))
    thought_generated = bool(trace) and bool(thought_path)
    visualization_generated = node_count > 0 and edge_count > 0

    report = {
        "timestamp": time.time(),
        "state": state_str,
        "action": action,
        "base_scores": {k: float(v) for k, v in (base_scores or {}).items()},
        "thought_generated": thought_generated,
        "visualization_generated": visualization_generated,
        "thought_path_steps": len(thought_path),
        "visual_nodes": node_count,
        "visual_edges": edge_count,
    }

    if not thought_generated or not visualization_generated:
        logger.warning("LOOP_ARTIFACT_MISSING %s", report)

    with _loop_artifact_lock:
        _loop_artifacts.append(report)
    return report

# =========================
# ✅ LIFESPAN

@asynccontextmanager
async def lifespan(application: FastAPI):
    global _thought_loop
    # Load persisted knowledge graph
    _graph_store.load(_kg)
    print(f"[OK] Knowledge graph loaded ({len(_kg.triples)} triples)")

    if len(_kg.triples) == 0:
        print("[STARTUP] No existing knowledge found. Loading seed knowledge...")
        seed_result = _load_seed_knowledge()
        _graph_store.save(_kg)
        print(f"[STARTUP] Seed knowledge loaded: {seed_result['triples_loaded']} triples ({seed_result.get('txt_triples', 0)} from TXT files)")

    print("[TRAIN] RL training started...")
    main.train()
    print("[OK] RL training complete")

    # Restore JEPA weights from disk (if available); otherwise warm-start from Q-table
    try:
        _jepa.load(JEPA_WEIGHTS_FILE)
        print(f"[OK] JEPA weights restored from {JEPA_WEIGHTS_FILE} ({_jepa._trained_samples} samples)")
    except FileNotFoundError:
        jepa_updates = _train_jepa_from_qtable(epochs=JEPA_WARMUP_EPOCHS)
        print(f"[OK] JEPA offline training complete ({jepa_updates} samples, trained={_jepa.is_trained})")

    # Restore curriculum state from disk (if available)
    try:
        _curriculum.load(CURRICULUM_STATE_FILE)
        print(f"[OK] Curriculum state restored from {CURRICULUM_STATE_FILE} (stage={_curriculum.current_stage} {_curriculum.stage_label})")
    except FileNotFoundError:
        print("[OK] Curriculum state initialised at stage 0 (LITERACY)")

    _thought_loop = ThoughtLoop(main, _jepa, simulate_outcome, main.Q, ACTIONS)
    _thought_loop.embedding.kg = _kg

    def loop():
        states = [
            ("flood",),
            ("damage",),
            ("collapse",),
            ("crisis",),
            ("flood", "damage"),
            ("damage", "collapse"),
        ]

        while True:
            sampled_state = random.choice(states)
            scores, action, diagnostics = hybrid_decision(sampled_state, return_diagnostics=True)
            _record_loop_artifacts(
                sampled_state,
                action,
                scores,
                thought_trace=diagnostics.get("thought_trace"),
            )
            time.sleep(2.0)

    threading.Thread(target=loop, daemon=True).start()
    yield

    # Persist knowledge graph, JEPA weights, and curriculum state on shutdown
    _graph_store.save(_kg)
    print("[OK] Knowledge graph saved")
    _jepa.save(JEPA_WEIGHTS_FILE)
    print(f"[OK] JEPA weights saved to {JEPA_WEIGHTS_FILE}")
    _curriculum.save(CURRICULUM_STATE_FILE)
    print(f"[OK] Curriculum state saved to {CURRICULUM_STATE_FILE}")

# =========================
# ✅ FASTAPI

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# ✅ METRICS

def get_inference_rate():
    global inference_count, last_time
    now = time.time()
    with _inference_lock:
        rate = inference_count / (now - last_time) if now > last_time else 0
        inference_count = 0
        last_time = now
    return int(rate)

def get_cycles():
    with _inference_lock:
        counts = {}
        for s in recent_states:
            counts[s] = counts.get(s, 0) + 1
        return sum(1 for v in counts.values() if v > 2)

# =========================
# ✅ API

@app.get("/")
def root():
    return {"status": "semantic engine running"}

@app.get("/metrics")
def metrics():
    with _loop_artifact_lock:
        recent = list(_loop_artifacts)[-20:]
    thought_ok = sum(1 for r in recent if r.get("thought_generated"))
    visual_ok = sum(1 for r in recent if r.get("visualization_generated"))

    return {
        "nodes": len(main.Q),
        "edges": len(main.policy_counter),
        "inference": get_inference_rate(),
        "cycles": get_cycles(),
        "conflicts": calculate_conflicts(),
        "jepa_trained": _jepa.is_trained,
        "jepa_samples": _jepa._trained_samples,
        "kg_edges": len(_kg.triples),
        "loop_thought_ok_20": thought_ok,
        "loop_visual_ok_20": visual_ok,
    }


@app.get("/loop/health")
def loop_health(limit: int = Query(default=20, ge=1, le=200)):
    """Return recent per-cycle checks for thought and visualization artifacts."""
    with _loop_artifact_lock:
        reports = list(_loop_artifacts)[-limit:]
    thought_ok = sum(1 for item in reports if item.get("thought_generated"))
    visual_ok = sum(1 for item in reports if item.get("visualization_generated"))
    return {
        "count": len(reports),
        "thought_ok": thought_ok,
        "visualization_ok": visual_ok,
        "latest": reports[-1] if reports else None,
        "reports": reports,
    }

# =========================
# ✅ EXPLAIN

@app.get("/explain")
def explain(state: str = Query(..., max_length=500, description="State tuple string, e.g. ('flood','damage')")):
    try:
        explanation = []
        s = state.lower()

        if "crisis" in s:
            explanation.append("High risk crisis detected")
        if "collapse" in s:
            explanation.append("Structural collapse risk")
        if "flood" in s:
            explanation.append("Flood risk present")

        if not explanation:
            explanation.append("Stable state")

        rule_scores = evaluate_actions(state)
        sim_scores, _ = plan_actions(state)
        jepa_scores = evaluate_actions_jepa(state)
        base_scores, best_action, diagnostics = hybrid_decision(state, return_diagnostics=True)
        _record_loop_artifacts(
            state,
            best_action,
            base_scores,
            thought_trace=diagnostics.get("thought_trace"),
        )

        return {
            "state": state,
            "explanation": explanation,
            "scores": rule_scores,
            "simulation": sim_scores,
            "jepa": jepa_scores,
            "base_scores": base_scores,
            "best_action": best_action,
            "trap": detect_trap(sim_scores),
            "risk": calculate_risk(state)
        }

    except Exception as e:
        logger.exception("Explain request failed")
        return {"error": "Internal server error"}

# =========================
# ✅ GRAPH

@app.get("/graph")
def graph():
    try:
        nodes = set()
        edges = []

        for state, actions in main.policy_counter.items():
            s = str(state)
            nodes.add(s)

            for a in actions:
                node = f"{s}:{a}"
                nodes.add(node)

                edges.append({
                    "source": s,
                    "target": node
                })

        return {"nodes": list(nodes), "edges": edges}

    except Exception as e:
        print("GRAPH ERROR:", e)
        return {"nodes": [], "edges": []}

# =========================
# ✅ DECISION ENDPOINT
# POST /decision — returns the best action for a given state using the hybrid engine

from pydantic import BaseModel

class StateRequest(BaseModel):
    state: str

@app.post("/think")
def think(req: StateRequest):
    """Run the full deliberative thought loop for a state."""
    try:
        trace = _thought_loop.think(set(parse_state(req.state)))
        trace["thought_path"] = _build_thought_path(trace)
        return trace
    except Exception as e:
        logger.exception("Think request failed")
        return {"error": "Internal server error"}


@app.get("/debug/emotion/jepa")
def debug_emotion_jepa():
    """Test sequence showing how JEPA surprise modulates emotion across states."""
    try:
        results = []
        test_states = [
            ("clear", set()),
            ("rain", {"rain"}),
            ("flood", {"flood"}),
            ("flood,damage", {"flood", "damage"}),
            ("crisis", {"crisis"}),
        ]
        from cognition.emotion_space import EmotionSpace

        for label, state in test_states:
            spaces = _thought_loop.embedding.embed(state) if _thought_loop and hasattr(_thought_loop, "embedding") else {}
            risk = sum(spaces.get("risk", [0.0])) / max(1, len(spaces.get("risk", [1.0]))) if spaces else 0.0
            for surprise in [0.0, 0.2, 0.5, 0.8]:
                es2 = EmotionSpace()
                es2.from_state(state)
                es2.update_from_jepa(surprise, risk)
                post_vec = es2.to_vector()
                results.append({
                    "state": label,
                    "surprise": surprise,
                    "risk": round(risk, 4),
                    "emotion": [round(v, 4) for v in post_vec],
                })
        return {"test_sequence": results, "count": len(results)}
    except Exception:
        logger.exception("Debug emotion/jepa failed")
        return {"error": "Internal server error"}


@app.get("/thought_trace")
def thought_trace(n: int = Query(default=5, ge=1, le=20)):
    """Return the last n thought traces."""
    try:
        return {"traces": _thought_loop.get_recent_traces(n)}
    except Exception as e:
        logger.exception("Thought trace request failed")
        return {"error": "Internal server error"}


@app.post("/decision")
def decision(req: StateRequest):
    try:
        base_scores, best, diagnostics = hybrid_decision(req.state, return_diagnostics=True)
        _record_loop_artifacts(
            req.state,
            best,
            base_scores,
            thought_trace=diagnostics.get("thought_trace"),
        )
        return {
            "state": req.state,
            "action": best,
            "scores": base_scores,
        }
    except Exception as e:
        logger.exception("Request failed")
        return {"error": "Internal server error"}

# =========================
# ✅ SIMULATE ENDPOINT
# POST /simulate — runs up to MAX_SIMULATE_STEPS steps using the hybrid engine

class SimulateRequest(BaseModel):
    state: str
    steps: Optional[int] = 10

MAX_SIMULATE_STEPS = 50

@app.post("/simulate")
def simulate(req: SimulateRequest):
    try:
        n = min(req.steps or 10, MAX_SIMULATE_STEPS)
        trajectory = []
        current = req.state

        for _ in range(n):
            scores, action, diagnostics = hybrid_decision(current, return_diagnostics=True)
            _record_loop_artifacts(
                current,
                action,
                scores,
                thought_trace=diagnostics.get("thought_trace"),
            )
            reward, next_state = simulate_outcome(current, action)
            trajectory.append({
                "state": current,
                "action": action,
                "reward": round(reward, 3),
                "next_state": str(next_state),
            })
            current = str(next_state)

        return {"trajectory": trajectory, "steps": len(trajectory)}
    except Exception as e:
        logger.exception("Request failed")
        return {"error": "Internal server error"}

# =========================
# ✅ SEMANTIC ENDPOINTS

class AssertRequest(BaseModel):
    subject: str
    relation: str
    obj: str
    confidence: float = 1.0

@app.post("/semantic/assert")
def semantic_assert(req: AssertRequest):
    """Add a triple to the KG and assert it in the TMS."""
    try:
        triple = (req.subject, req.relation, req.obj)
        if _tms.resolve_conflict(triple, req.confidence):
            _tms.add_belief(triple, req.confidence)
            _kg.add(req.subject, req.relation, req.obj, req.confidence)
        return {"ok": True, "triple": triple}
    except Exception as e:
        logger.exception("Request failed")
        return {"error": "Internal server error"}

@app.get("/semantic/beliefs")
def semantic_beliefs():
    """Return the current valid belief set from the TMS."""
    try:
        beliefs = _tms.get_valid_triples()
        return {"beliefs": [{"triple": list(t), "confidence": round(c, 4)} for t, c in beliefs], "count": len(beliefs)}
    except Exception as e:
        logger.exception("Request failed")
        return {"error": "Internal server error"}

@app.post("/semantic/infer")
def semantic_infer():
    """Run the Reasoner over the current KG and commit new inferences."""
    try:
        reasoner = Reasoner(_kg)
        before = len(_kg.triples)
        new_triples = reasoner.infer()
        for (s, r, o, c) in new_triples:
            _kg.add(s, r, o, c)
        after = len(_kg.triples)
        return {"new_triples": after - before, "total": after}
    except Exception as e:
        logger.exception("Request failed")
        return {"error": "Internal server error"}

class FeedbackRequest(BaseModel):
    subject: str
    relation: str
    obj: str
    feedback: str  # "correct" or "wrong"

@app.post("/semantic/feedback")
def semantic_feedback(req: FeedbackRequest):
    """Send feedback on a belief to the online learner ('correct' or 'wrong')."""
    try:
        triple = (req.subject, req.relation, req.obj)
        _online_learner.apply_feedback(triple, req.feedback)
        return {"ok": True}
    except Exception as e:
        logger.exception("Request failed")
        return {"error": "Internal server error"}

@app.get("/semantic/concepts")
def semantic_concepts():
    """Return patterns extracted from TMS beliefs by the concept learner."""
    try:
        concepts = _concept_learner.learn()
        return {"concepts": concepts}
    except Exception as e:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/semantic/abstractions")
def semantic_abstractions():
    """Return abstract patterns (abstraction_level >= 0.6) and abstract rules (abstraction >= 0.5)."""
    try:
        concepts = _concept_learner.learn()
        abstract_patterns = [
            c for c in concepts
            if c.get("abstraction_level", 0) >= 0.6
        ]

        rules = _rule_learner.learn_rules()
        abstract_rules = [
            r for r in rules
            if r.get("abstraction", 0) >= 0.5
        ]

        return {
            "abstract_patterns": abstract_patterns,
            "abstract_rules": [
                {
                    "if": list(r["if"]),
                    "then": list(r["then"]),
                    "weight": round(r["weight"], 4),
                    "abstraction": round(r.get("abstraction", 0), 4),
                    "context": sorted(r.get("context", set())),
                    "usage": r.get("usage", 0),
                }
                for r in abstract_rules
            ],
            "concept_count": len(concepts),
            "rule_count": len(rules),
        }
    except Exception:
        logger.exception("Abstractions request failed")
        return {"error": "Internal server error"}


@app.post("/learn/abstraction/trigger")
def learn_abstraction_trigger():
    """Run concept and rule learning, promote high-abstraction patterns to curriculum."""
    try:
        concepts = _concept_learner.learn()
        rules = _rule_learner.learn_rules()

        promoted = 0
        promoted_items = []

        for c in concepts:
            if c.get("abstraction_level", 0) >= 0.6:
                pattern = c["pattern"]
                fact_meta = {
                    "source_type": "abstraction_promotion",
                    "source_document": "abstraction_trigger",
                    "timestamp": time.time(),
                    "stage": "validated",
                    "teaching_kind": "rule",
                    "abstraction_pending": False,
                }
                _kg.add("curriculum", "knows_abstract_concept", pattern, min(1.0, c["abstraction_level"]), fact_meta)
                _update_concept_space_embeddings_from_fact(
                    "curriculum", "knows_abstract_concept", pattern, min(1.0, c["abstraction_level"]), fact_meta
                )
                promoted += 1
                promoted_items.append({"pattern": pattern, "abstraction_level": c["abstraction_level"]})

        return {
            "promoted": promoted,
            "promoted_items": promoted_items,
            "concept_count": len(concepts),
            "rule_count": len(rules),
        }
    except Exception:
        logger.exception("Abstraction trigger failed")
        return {"error": "Internal server error"}


# =========================
# ✅ LEARN / PROCESS ENDPOINT
# POST /learn/process — run concept learning and evaluate curriculum progression

@app.post("/learn/process")
def learn_process():
    """Run the concept learner and evaluate curriculum stage progression.

    Triggered externally whenever new knowledge has been ingested.  Checks
    both the density condition (concept count vs. next-stage threshold) and
    the stability condition (recent average JEPA error).  If both pass the
    stage advances; otherwise a blocking reason is returned.
    """
    try:
        concepts = _concept_learner.learn()
        concept_count = len(concepts)
        recent_errors = list(_jepa_recent_errors)

        result = _curriculum.evaluate_progression(concept_count, recent_errors)

        return {
            "concept_count": concept_count,
            "avg_jepa_error": round(result["avg_jepa_error"], 6) if result["avg_jepa_error"] is not None else None,
            "stage_advanced": result["advanced"],
            "blocked": result["blocked"],
            "reason": result["reason"],
            "curriculum": _curriculum.get_status_report(concept_count),
        }
    except Exception:
        logger.exception("Learn process request failed")
        return {"error": "Internal server error"}


# =========================
# ✅ CURRICULUM ENDPOINTS

@app.get("/curriculum/status")
def curriculum_status():
    """Return the current curriculum stage, progress, and blocking status."""
    try:
        concepts = _concept_learner.learn()
        concept_count = len(concepts)
        return _curriculum.get_status_report(concept_count)
    except Exception:
        logger.exception("Curriculum status request failed")
        return {"error": "Internal server error"}


@app.post("/curriculum/reset")
def curriculum_reset():
    """Manually reset the curriculum back to stage 0 (LITERACY).

    This is the only way to decrease the stage — automatic progression
    only ever moves the stage forward.
    """
    try:
        _curriculum.reset()
        return {
            "ok": True,
            "curriculum": _curriculum.get_status_report(0),
        }
    except Exception:
        logger.exception("Curriculum reset request failed")
        return {"error": "Internal server error"}


# =========================
# ✅ ARITHMETIC ENDPOINT (prerequisite-gated)
# POST /math/calculate — requires NUMERACY stage (stage >= 1)

class MathRequest(BaseModel):
    operation: str  # "add", "subtract", "multiply", "divide"
    a: float
    b: float


@app.post("/math/calculate")
def math_calculate(req: MathRequest):
    """Perform a basic arithmetic operation.

    Requires curriculum stage 1 (NUMERACY) or above.  Returns HTTP 403 if
    the curriculum has not yet reached the required stage.
    """
    try:
        _curriculum.check_prerequisite("arithmetic")
    except PrerequisiteNotMetError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    try:
        op = req.operation.strip().lower()
        if op == "add":
            result = req.a + req.b
        elif op == "subtract":
            result = req.a - req.b
        elif op == "multiply":
            result = req.a * req.b
        elif op == "divide":
            if req.b == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Division by zero.",
                )
            result = req.a / req.b
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown operation '{op}'. Supported: add, subtract, multiply, divide.",
            )
        return {
            "operation": op,
            "a": req.a,
            "b": req.b,
            "result": result,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Math calculate request failed")
        return {"error": "Internal server error"}


def _get_relations_builder() -> SpaceRelationsBuilder:
    global _relations_builder
    if _relations_builder is None:
        _relations_builder = SpaceRelationsBuilder(kg=_kg, tms=_tms, thought_loop=_thought_loop)
    else:
        _relations_builder.kg = _kg
        _relations_builder.tms = _tms
        _relations_builder.thought_loop = _thought_loop
    return _relations_builder


@app.get("/semantic/relations")
def semantic_relations(
    query: Optional[str] = Query(default=None, max_length=500),
    state: Optional[str] = Query(default=None, max_length=500),
    include_spaces: str = Query(default=",".join(DEFAULT_SPACES)),
    max_depth: int = Query(default=2, ge=1, le=4),
    max_edges: int = Query(default=300, ge=50, le=1000),
):
    """Return a unified graph of relations across selected cognitive spaces."""
    try:
        _require_feature(ENABLE_SPACE_RELATIONS, "space_relations")
        if not query and not state:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either query or state must be provided.",
            )

        requested_spaces = [s.strip() for s in include_spaces.split(",") if s.strip()]
        allowed_spaces = set(DEFAULT_SPACES)
        requested_spaces = [s for s in requested_spaces if s in allowed_spaces]
        if not requested_spaces:
            requested_spaces = list(DEFAULT_SPACES)

        builder = _get_relations_builder()
        return builder.build(
            query=query,
            state=state,
            include_spaces=requested_spaces,
            max_depth=max_depth,
            max_edges=max_edges,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


def _tokenize_query(value: str) -> set[str]:
    # Unicode-aware tokenization so Turkish and other non-ASCII words are searchable.
    raw_tokens = [token for token in re.findall(r"[\w]+", (value or "").lower(), flags=re.UNICODE) if token]
    tokens = set(raw_tokens)
    for token in raw_tokens:
        if "_" in token:
            parts = [part for part in token.split("_") if part]
            tokens.update(parts)
    return tokens


def _known_semantic_tokens() -> set[str]:
    known: set[str] = set()
    for s, r, o, _c in getattr(_kg, "triples", []):
        known.update(_tokenize_query(str(s)))
        known.update(_tokenize_query(str(r)))
        known.update(_tokenize_query(str(o)))
    known.update(NumberParser.known_tokens())
    return known


def _query_answer_policy(query: str) -> dict[str, object]:
    normalized = str(query or "").strip().lower()
    tokens = _tokenize_query(normalized)

    # Early detection: absolute value like |-5|
    if '|' in normalized:
        if re.search(r'\|-?\d+(?:\.\d+)?\|', normalized):
            return {
                "should_answer": True,
                "reason": "absolute_value_expression",
                "matched_tokens": [],
                "missing_tokens": [],
            }

    # Early detection: any expression with digits and an operator (any length)
    if re.search(r"\d+\s*[+\-*/]\s*\d+", normalized):
        return {
            "should_answer": True,
            "reason": "arithmetic_expression",
            "matched_tokens": [],
            "missing_tokens": [],
        }

    # Space-separated numbers (e.g. "4 1" from URL-decoded "4+1")
    space_parts = normalized.strip().split()
    if len(space_parts) == 2 and space_parts[0].lstrip('-').isdigit() and space_parts[1].lstrip('-').isdigit():
        return {
            "should_answer": True,
            "reason": "arithmetic_expression_space",
            "matched_tokens": [],
            "missing_tokens": [],
        }

    symbolic_arithmetic = compute_arithmetic(normalized) is not None
    symbolic_calculus = compute_calculus(normalized) is not None
    symbolic_def_integral = bool(re.search(r"integral\s+from\s+[0-9.]+", normalized, flags=re.I))
    symbolic_algebra = bool(re.search(r"det\s*\[|matrix", normalized, flags=re.I))
    symbolic_equation = bool(re.search(r"solve|=", normalized, flags=re.I) and "integral" not in normalized and "derivative" not in normalized and "det" not in normalized)
    symbolic_derivative = bool(re.search(r"d/d[a-z]|derivative\s+of", normalized, flags=re.I))

    if symbolic_arithmetic or symbolic_calculus or symbolic_def_integral or symbolic_algebra or symbolic_equation or symbolic_derivative:
        return {
            "should_answer": True,
            "reason": "symbolic_path",
            "matched_tokens": [],
            "missing_tokens": [],
        }

    if not tokens:
        return {
            "should_answer": False,
            "reason": "no_lexical_tokens",
            "matched_tokens": [],
            "missing_tokens": [],
        }

    known = _known_semantic_tokens()
    matched = sorted(tokens & known)
    missing = sorted(tokens - known)

    if missing:
        new_matched = []
        still_missing = []
        for token in missing:
            num = NumberParser.parse_number(token)
            if num is not None:
                new_matched.append(token)
            else:
                still_missing.append(token)
        if new_matched:
            matched = sorted(set(matched) | set(new_matched))
            missing = still_missing

    return {
        "should_answer": bool(matched) or bool(re.search(r'\d', normalized)),
        "reason": "matched_known_tokens" if matched else ("has_digits" if re.search(r'\d', normalized) else "unknown_concept_tokens"),
        "matched_tokens": matched,
        "missing_tokens": missing,
    }


_FULL_VIEW_CONCEPTS = {
    "number",
    "integer",
    "decimal",
    "fraction",
    "real",
    "digits",
    "digit",
    "letter",
    "operations",
    "operation",
    "addition",
    "subtraction",
    "multiplication",
    "division",
    "derivative",
    "integral",
    "limit",
    "function",
    "logarithm",
    "log",
    "ln",
    "base",
    "change_of_base",
    "exponent",
    "inverse_function",
    "calculus",
    "logarithms",
    "real_numbers",
}


def _should_expand_full_relation_view(query: Optional[str]) -> bool:
    text = (query or "").strip().lower()
    if not text:
        return False
    if any(symbol in text for symbol in ("+", "-", "*", "/", "=", "^")):
        return False
    tokens = _tokenize_query(text)
    if not tokens:
        return False
    if len(tokens) > 3:
        return False
    return any(token in _FULL_VIEW_CONCEPTS for token in tokens)


def _resolve_relation_spaces(query: Optional[str], include_spaces: str) -> list[str]:
    requested_spaces = [s.strip() for s in include_spaces.split(",") if s.strip()]
    allowed_spaces = set(DEFAULT_SPACES)
    requested_spaces = [s for s in requested_spaces if s in allowed_spaces]
    if _should_expand_full_relation_view(query):
        return list(DEFAULT_SPACES)
    if not requested_spaces:
        return list(DEFAULT_SPACES)
    return requested_spaces


def _source_quality(provenance: dict) -> float:
    source_type = str(provenance.get("source_type", "")).lower()
    if source_type == "pdf":
        return 0.9
    if source_type:
        return 0.8
    return 0.7


def _score_fact(confidence: float, recency: float, frequency: float, source_quality: float) -> float:
    return float((0.45 * confidence) + (0.20 * recency) + (0.20 * frequency) + (0.15 * source_quality))


def _search_semantic_facts(query: str, limit: int = 50) -> list[dict]:
    tokens = _tokenize_query(query)
    now = time.time()
    explicit_calculus_intent = bool(
        re.search(r"\b(integral|integrate|derivative|turev)\b|d/d[a-z]", query, flags=re.I)
    )
    # Absolute value handler — must come BEFORE compute_arithmetic
    # because compute_arithmetic strips | chars and misparses |-5| as -5.
    _abs_arithmetic = None
    if '|' in query:
        _abs_match = re.search(r'\|(-?\d+(?:\.\d+)?)\|', query)
        if _abs_match:
            try:
                _abs_val = float(_abs_match.group(1))
                _abs_result = abs(_abs_val)
                from types import SimpleNamespace
                _abs_arithmetic = SimpleNamespace(
                    expression=f"|{_abs_val}|",
                    key=f"abs_{str(_abs_val).replace('.', 'dot').replace('-', 'neg')}",
                    value=str(int(_abs_result) if _abs_result.is_integer() else _abs_result),
                    steps=[f"|{_abs_val}| = {_abs_result}"]
                )
            except (ValueError, TypeError):
                pass

    arithmetic = _abs_arithmetic if _abs_arithmetic is not None else compute_arithmetic(query)
    calculus = compute_calculus(query)
    def_integral = compute_definite_integral(query) if re.search(r"integral\s+from\s+[0-9.]+", query, flags=re.I) else None
    adv_deriv = compute_derivative_advanced(query) if re.search(r"d/d[a-z]|derivative\s+of", query, flags=re.I) else None
    algebra = compute_algebra(query) if re.search(r"det\s*\[|matrix", query, flags=re.I) else None
    equation = solve_equation(query) if re.search(r"solve|=", query, flags=re.I) and "integral" not in query and "derivative" not in query and "det" not in query else None
    arithmetic_key = None
    arithmetic_result = None
    arithmetic_missing: list[str] = []

    # Addition handler - works for ANY digit length
    if arithmetic is None and re.search(r"\d+\s*\+?\s*\d+", query):
        match = re.search(r"(\d+)\s*\+\s*(\d+)", query)
        if not match:
            match = re.search(r"(\d+)\s+(\d+)", query)
        if match:
            try:
                left = int(match.group(1))
                right = int(match.group(2))
                result = left + right
                from types import SimpleNamespace
                arithmetic = SimpleNamespace(
                    expression=f"{left}+{right}",
                    key=f"plus_{left}_{right}",
                    value=str(result),
                    steps=[f"{left} + {right} = {result}"],
                )
            except (ValueError, TypeError):
                pass

    # Exponent handler (2^10)
    if arithmetic is None and '^' in query:
        parts = query.split('^')
        if len(parts) == 2:
            try:
                base = int(parts[0].strip())
                exp = int(parts[1].strip())
                result = base ** exp
                from types import SimpleNamespace
                arithmetic = SimpleNamespace(
                    expression=f"{base}^{exp}",
                    key=f"pow_{base}_{exp}",
                    value=str(result),
                    steps=[f"{base}^{exp} = {result}"]
                )
            except (ValueError, TypeError):
                pass

    # Factorial handler (5!)
    if arithmetic is None and '!' in query:
        import math
        match = re.search(r'(\d+)!', query)
        if match:
            try:
                n = int(match.group(1))
                result = math.factorial(n)
                from types import SimpleNamespace
                arithmetic = SimpleNamespace(
                    expression=f"{n}!",
                    key=f"factorial_{n}",
                    value=str(result),
                    steps=[f"{n}! = {result}"]
                )
            except (ValueError, TypeError):
                pass

    # Modulus handler (10 mod 3)
    if arithmetic is None and 'mod' in query.lower():
        match = re.search(r'(\d+)\s+mod\s+(\d+)', query.lower())
        if match:
            try:
                a = int(match.group(1))
                b = int(match.group(2))
                if b != 0:
                    result = a % b
                    from types import SimpleNamespace
                    arithmetic = SimpleNamespace(
                        expression=f"{a} mod {b}",
                        key=f"mod_{a}_{b}",
                        value=str(result),
                        steps=[f"{a} mod {b} = {result}"]
                    )
            except (ValueError, TypeError):
                pass

    # Absolute value handler (|-5|)
    if arithmetic is None and '|' in query:
        match = re.search(r'\|(-?\d+(?:\.\d+)?)\|', query)
        if match:
            try:
                val = float(match.group(1))
                result = abs(val)
                from types import SimpleNamespace
                arithmetic = SimpleNamespace(
                    expression=f"|{val}|",
                    key=f"abs_{str(val).replace('.', 'dot').replace('-', 'neg')}",
                    value=str(int(result) if result.is_integer() else result),
                    steps=[f"|{val}| = {result}"]
                )
            except (ValueError, TypeError):
                pass

    if arithmetic is not None:
        arithmetic_key = arithmetic.key
        arithmetic_result = arithmetic.value
        can_compute, missing = can_compute_expression(_kg, arithmetic.expression)
        phase_missing = missing_curriculum_phases(_kg, required_phases_for_arithmetic(arithmetic.expression))
        missing = [*missing, *[f"phase:{p}" for p in phase_missing]]
        if not can_compute:
            arithmetic_missing = missing
            arithmetic_result = None
        elif phase_missing:
            arithmetic_missing = missing
            arithmetic_result = None

    if explicit_calculus_intent and (calculus is not None or def_integral is not None or adv_deriv is not None):
        arithmetic = None
        arithmetic_key = None
        arithmetic_result = None
        arithmetic_missing = []

    # Equation or algebra results suppress arithmetic (to avoid spurious extraction like '2-40' from 'solve x^2-4=0')
    if equation is not None or algebra is not None:
        arithmetic = None
        arithmetic_key = None
        arithmetic_result = None
        arithmetic_missing = []

    calculus_missing: list[str] = []
    if calculus is not None:
        phase_missing = missing_curriculum_phases(_kg, required_phases_for_calculus())
        if phase_missing:
            calculus_missing = [f"phase:{p}" for p in phase_missing]
            calculus = None

    explicit_log_intent = bool(re.search(r"\b(logarithm|log10|log|ln)\b", query, flags=re.I))
    log_missing: list[str] = []
    if explicit_log_intent and calculus is not None:
        phase_missing = missing_curriculum_phases(_kg, required_phases_for_logarithms())
        if phase_missing:
            log_missing = [f"phase:{p}" for p in phase_missing]
            calculus = None

    # If the query has no lexical tokens and no symbolic math intent, do not
    # fallback to broad KG matches.
    if not tokens and arithmetic is None and calculus is None and def_integral is None and adv_deriv is None and algebra is None and equation is None:
        return []

    usage_lookup: dict[tuple[str, str, str], float] = {}
    recency_lookup: dict[tuple[str, str, str], float] = {}
    max_usage = 1.0
    if _tms is not None:
        for belief in getattr(_tms, "beliefs", []):
            triple = belief.get("triple", ())
            if len(triple) < 3:
                continue
            key = (str(triple[0]), str(triple[1]), str(triple[2]))
            usage = float(belief.get("usage", 1) or 1)
            max_usage = max(max_usage, usage)
            usage_lookup[key] = usage

            ts = float(belief.get("timestamp", now) or now)
            age_seconds = max(0.0, now - ts)
            recency_lookup[key] = max(0.0, min(1.0, 1.0 / (1.0 + (age_seconds / 3600.0))))

    results: list[dict] = []
    for s, r, o, c in getattr(_kg, "triples", []):
        s_txt = str(s)
        r_txt = str(r)
        o_txt = str(o)
        key = (s_txt, r_txt, o_txt)

        searchable_tokens = _tokenize_query(" ".join((s_txt, r_txt, o_txt)))
        if tokens and not (tokens & searchable_tokens):
            metadata = _kg.get_metadata(s, r, o) if hasattr(_kg, "get_metadata") else {}
            source_text_tokens = _tokenize_query(str(metadata.get("source_text", "")))
            if not (tokens & source_text_tokens):
                continue

        provenance = dict(_kg.get_metadata(s, r, o) if hasattr(_kg, "get_metadata") else {})
        frequency = min(1.0, usage_lookup.get(key, 1.0) / max_usage)
        recency = recency_lookup.get(key, 0.5)
        sq = _source_quality(provenance)
        score = _score_fact(float(c), recency, frequency, sq)
        if arithmetic_key and str(s_txt).lower() == arithmetic_key:
            score += 0.2

        results.append({
            "triple": [s_txt, r_txt, o_txt],
            "confidence": round(float(c), 4),
            "score": round(score, 4),
            "ranking": {
                "confidence": round(float(c), 4),
                "recency": round(recency, 4),
                "frequency": round(frequency, 4),
                "source_quality": round(sq, 4),
            },
            "provenance": provenance,
        })

    if arithmetic_key is not None and arithmetic_result is not None:
        has_exact = any(
            (str(item.get("triple", ["", "", ""])[0]).lower() == arithmetic_key)
            and (str(item.get("triple", ["", "", ""])[2]) == str(arithmetic_result))
            for item in results
        )
        if not has_exact:
            results.append({
                "triple": [arithmetic_key, "equals", str(arithmetic_result)],
                "confidence": 0.99,
                "score": 1.05,
                "ranking": {
                    "confidence": 0.99,
                    "recency": 1.0,
                    "frequency": 1.0,
                    "source_quality": 1.0,
                },
                "provenance": {
                    "source_type": "arithmetic_operator",
                    "source_document": "runtime_arithmetic",
                    "source_text": query,
                    "space": "arithmetic",
                    "solution_trace": arithmetic.steps if arithmetic is not None else [],
                },
            })

    if arithmetic_key is not None and arithmetic_result is None and arithmetic_missing:
        flags = detect_decimal_or_fraction(arithmetic.expression if arithmetic is not None else query)
        results.append({
            "triple": [arithmetic_key, "requires_learning", ",".join(arithmetic_missing)],
            "confidence": 1.0,
            "score": 1.01,
            "ranking": {
                "confidence": 1.0,
                "recency": 1.0,
                "frequency": 1.0,
                "source_quality": 1.0,
            },
            "provenance": {
                "source_type": "numeracy_gate",
                "source_document": "runtime_numeracy_guard",
                "source_text": query,
                "space": "arithmetic",
                "missing_tokens": arithmetic_missing,
                "has_decimal": flags["has_decimal"],
                "has_fraction": flags["has_fraction"],
            },
        })

    if calculus is not None:
        results.append({
            "triple": [calculus.expression, calculus.kind, calculus.result],
            "confidence": 0.99,
            "score": 1.02,
            "ranking": {
                "confidence": 0.99,
                "recency": 1.0,
                "frequency": 1.0,
                "source_quality": 1.0,
            },
            "provenance": {
                "source_type": "symbolic_calculus",
                "source_document": "runtime_calculus",
                "source_text": query,
                "space": "calculus",
                "variable": calculus.variable,
                "solution_trace": calculus.steps,
            },
        })

    if def_integral is not None:
        results.append({
            "triple": [def_integral.expression, "definite_integral", def_integral.result],
            "confidence": 0.99,
            "score": 1.03,
            "ranking": {"confidence": 0.99, "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
            "provenance": {
                "source_type": "symbolic_calculus",
                "source_document": "runtime_definite_integral",
                "source_text": query,
                "space": "calculus",
                "variable": def_integral.variable,
                "lower": def_integral.lower,
                "upper": def_integral.upper,
                "antiderivative": def_integral.antiderivative,
                "solution_trace": def_integral.steps,
            },
        })

    if adv_deriv is not None:
        results.append({
            "triple": [adv_deriv.expression, adv_deriv.kind, adv_deriv.result],
            "confidence": 0.99,
            "score": 1.02,
            "ranking": {"confidence": 0.99, "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
            "provenance": {
                "source_type": "symbolic_calculus",
                "source_document": "runtime_derivative",
                "source_text": query,
                "space": "calculus",
                "variable": adv_deriv.variable,
                "solution_trace": adv_deriv.steps,
            },
        })

    if algebra is not None:
        results.append({
            "triple": [algebra.expression, algebra.kind, algebra.result],
            "confidence": 0.99,
            "score": 1.04,
            "ranking": {"confidence": 0.99, "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
            "provenance": {
                "source_type": "symbolic_algebra",
                "source_document": "runtime_algebra",
                "source_text": query,
                "space": "arithmetic",
                "solution_trace": algebra.steps,
            },
        })

    if equation is not None:
        sol_str = ", ".join(_format_number(s) for s in equation.solutions) if equation.solutions else "no real solutions"
        results.append({
            "triple": [equation.equation, "solved", sol_str],
            "confidence": 0.99,
            "score": 1.04,
            "ranking": {"confidence": 0.99, "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
            "provenance": {
                "source_type": "symbolic_algebra",
                "source_document": "runtime_equation",
                "source_text": query,
                "space": "arithmetic",
                "variable": equation.variable,
                "solutions": equation.solutions,
                "solution_trace": equation.steps,
            },
        })

    if explicit_log_intent and log_missing:
        results.append({
            "triple": [query, "requires_learning", ",".join(log_missing)],
            "confidence": 1.0,
            "score": 1.0,
            "ranking": {
                "confidence": 1.0,
                "recency": 1.0,
                "frequency": 1.0,
                "source_quality": 1.0,
            },
            "provenance": {
                "source_type": "curriculum_gate",
                "source_document": "runtime_curriculum_guard",
                "source_text": query,
                "space": "calculus",
                "missing_tokens": log_missing,
            },
        })

    if calculus is None and calculus_missing:
        results.append({
            "triple": [query, "requires_learning", ",".join(calculus_missing)],
            "confidence": 1.0,
            "score": 1.0,
            "ranking": {
                "confidence": 1.0,
                "recency": 1.0,
                "frequency": 1.0,
                "source_quality": 1.0,
            },
            "provenance": {
                "source_type": "curriculum_gate",
                "source_document": "runtime_curriculum_guard",
                "source_text": query,
                "space": "calculus",
                "missing_tokens": calculus_missing,
            },
        })

    results.sort(key=lambda item: (-item["score"], -item["confidence"], tuple(item["triple"])))
    return results[:limit]


def _load_seed_from_texts() -> int:
    """Load all seed TXT files from artifacts/seed_texts/ directory.

    Each line format: subject relation object
    Example: numeracy knows_digit 0

    Returns:
        Number of triples loaded
    """
    if not SEED_TXT_DIR.exists():
        print(f"[SEED] Directory not found: {SEED_TXT_DIR}")
        return 0

    total = 0

    for txt_path in sorted(SEED_TXT_DIR.glob("*.txt")):
        try:
            content = txt_path.read_text(encoding="utf-8")
            lines = content.strip().split('\n')
            file_count = 0

            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                parts = line.split()
                if len(parts) >= 3:
                    subject = parts[0]
                    relation = parts[1]
                    obj = ' '.join(parts[2:])
                    confidence = 1.0

                    if _tms.resolve_conflict((subject, relation, obj), confidence):
                        _tms.add_belief((subject, relation, obj), confidence, {
                            "source_type": "text_seed",
                            "source_document": txt_path.name,
                            "stage": "validated",
                        })
                        _kg.add(subject, relation, obj, confidence, {
                            "source_type": "text_seed",
                            "source_document": txt_path.name,
                        })
                        total += 1
                        file_count += 1

            print(f"[SEED] Loaded {txt_path.name}: {file_count} triples")
        except Exception as e:
            print(f"[SEED] Failed to load {txt_path.name}: {e}")

    return total


def _load_arithmetic_examples_from_seed() -> list[tuple[str, str]]:
    """Load arithmetic examples from seed_texts/*.txt files."""
    examples = []
    if not SEED_TXT_DIR.exists():
        return examples
    for txt_path in SEED_TXT_DIR.glob("*.txt"):
        content = txt_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ' equals ' in line:
                parts = line.split(' equals ')
                if len(parts) == 2:
                    expr, result = parts[0].strip(), parts[1].strip()
                    if any(op in expr for op in ['+', '-', '*', '/', '^', '!', 'mod']):
                        examples.append((expr, result))
    return examples


def _get_curriculum_phases() -> list[str]:
    """Load curriculum phase order from config file, with fallback."""
    config_path = Path(__file__).resolve().parent / "config" / "curriculum_phases.json"
    if config_path.exists():
        try:
            import json
            data = json.loads(config_path.read_text(encoding="utf-8"))
            return data.get("phases", CURRICULUM_PHASES)
        except Exception:
            pass
    return list(CURRICULUM_PHASES)


def _load_seed_knowledge() -> dict:
    """Load all seed knowledge into KG and TMS."""
    from core.data_loader import _DOMAIN_SEED_FACTS, _DOMAIN_SEED_TRANSITIONS
    from core.number_parser import NumberParser

    total = 0

    for fact in _DOMAIN_SEED_FACTS:
        if _tms.resolve_conflict((fact["subject"], fact["relation"], fact["object"]), fact["confidence"]):
            _tms.add_belief((fact["subject"], fact["relation"], fact["object"]), fact["confidence"])
            _kg.add(fact["subject"], fact["relation"], fact["object"], fact["confidence"])
            total += 1

    for token in NumberParser.known_tokens():
        if token.isdigit() or (token.startswith('0.') and token.replace('.', '').isdigit()):
            _kg.add("numeracy", "knows_number", token, 1.0)
            total += 1

    for expr, result in _load_arithmetic_examples_from_seed():
        _kg.add(expr, "equals", result, 1.0)
        total += 1

    for phase in _get_curriculum_phases():
        _kg.add("curriculum", "completed_phase", phase, 1.0)
        total += 1

    txt_count = _load_seed_from_texts()
    total += txt_count

    return {"triples_loaded": total, "txt_triples": txt_count}


def _reset_learning_state(include_archives: bool = False, mode: str = "soft") -> dict[str, object]:
    global _kg, _tms, _parser, _concept_learner, _rule_learner, _online_learner, _relations_builder, _data_loader, _concept_space_embeddings

    before = {
        "triples": len(getattr(_kg, "triples", [])),
        "beliefs": len(getattr(_tms, "beliefs", [])),
        "candidates": len(getattr(_tms, "candidates", [])),
    }

    _kg = KnowledgeGraph()
    _tms = LiteTMS(decay_rate=TMS_DECAY_RATE, min_confidence=TMS_MIN_CONFIDENCE)
    _parser = SemanticParser(enable_spacy_dep=ENABLE_SPACY_DEP_PARSER, spacy_model_name=SPACY_MODEL_NAME)
    _concept_learner = ConceptLearner(_tms)
    _rule_learner = RuleLearner(_tms)
    _online_learner = OnlineLearner(_tms)
    _kg.tms = _tms
    _relations_builder = None
    _data_loader = None

    with _ingest_rate_lock:
        _ingest_rate_bucket.clear()
    with _loop_artifact_lock:
        _loop_artifacts.clear()

    store_path = _concept_space_embeddings.path
    try:
        if store_path.exists():
            store_path.unlink()
    except Exception:
        logger.exception("Failed to remove concept embedding store")
    _concept_space_embeddings = ConceptSpaceEmbeddings(store_path)

    if _thought_loop is not None:
        try:
            _thought_loop.embedding.kg = _kg
        except Exception:
            logger.exception("Failed to rebind thought loop KG after reset")

    archives_removed = False
    if include_archives:
        try:
            if _training_pdf_archive_root.exists():
                shutil.rmtree(_training_pdf_archive_root)
            archives_removed = True
        except Exception:
            logger.exception("Failed to remove training archives")

    if mode in ("hard", "full"):
        if Path(GRAPH_FILE).exists():
            Path(GRAPH_FILE).unlink()
        seed_result = _load_seed_knowledge()
        print(f"[RESET] Seed knowledge loaded: {seed_result['triples_loaded']} triples ({seed_result.get('txt_triples', 0)} from TXT files)")
        _graph_store.save(_kg)

    if mode == "full":
        global _jepa
        _jepa = JEPAModel()
        jepa_updates = _train_jepa_from_qtable(epochs=JEPA_WARMUP_EPOCHS)
        print(f"[RESET] JEPA retrained: {jepa_updates} updates")
        _curriculum.reset()

    after = {
        "triples": len(getattr(_kg, "triples", [])),
        "beliefs": len(getattr(_tms, "beliefs", [])),
        "candidates": len(getattr(_tms, "candidates", [])),
    }
    return {
        "before": before,
        "after": after,
        "archives_removed": archives_removed,
        "seed_loaded": seed_result if mode in ("hard", "full") else None,
    }


@app.get("/semantic/search")
def semantic_search(
    query: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Search learned semantic triples and return scored facts with provenance."""
    try:
        policy = _query_answer_policy(query)
        if not bool(policy.get("should_answer", False)):
            return {
                "query": query,
                "count": 0,
                "facts": [],
                "policy": policy,
            }

        facts = _search_semantic_facts(query=query, limit=limit)
        return {
            "query": query,
            "count": len(facts),
            "facts": facts,
            "policy": policy,
        }
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/semantic/recall")
def semantic_recall(
    query: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(default=30, ge=1, le=200),
    include_spaces: str = Query(default=",".join(DEFAULT_SPACES)),
    max_depth: int = Query(default=2, ge=1, le=4),
    max_edges: int = Query(default=300, ge=50, le=1000),
    expand_with_facts: bool = Query(default=True),
):
    """Recall learned facts and cross-space relations in a single response."""
    try:
        _require_feature(ENABLE_SPACE_RELATIONS, "space_relations")
        requested_spaces = _resolve_relation_spaces(query, include_spaces)
        policy = _query_answer_policy(query)
        if not bool(policy.get("should_answer", False)):
            return {
                "query": query,
                "facts": [],
                "count": 0,
                "relations_graph": {
                    "spaces": requested_spaces,
                    "nodes": [],
                    "edges": [],
                },
                "trace": None,
                "policy": policy,
            }

        facts = _search_semantic_facts(query=query, limit=limit)

        expanded_state = None
        if expand_with_facts and facts:
            entities = []
            for fact in facts[: min(15, len(facts))]:
                triple = fact.get("triple", [])
                if len(triple) >= 3:
                    entities.append(str(triple[0]).lower())
                    entities.append(str(triple[2]).lower())
            expanded_state = sorted({e for e in entities if e})

        relations_graph = _get_relations_builder().build(
            query=query,
            state=expanded_state,
            include_spaces=requested_spaces,
            max_depth=max_depth,
            max_edges=max_edges,
        )

        trace = None
        if _thought_loop is not None:
            state_tokens = set(_tokenize_query(query))
            if state_tokens:
                trace = _thought_loop.think(state_tokens)

        return {
            "query": query,
            "facts": facts,
            "count": len(facts),
            "relations_graph": relations_graph,
            "trace": trace,
            "policy": policy,
        }
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}

# =========================
# ✅ INGEST ENDPOINT
# POST /ingest — bulk-load knowledge and/or RL transitions

from core.data_loader import DataLoader as _DataLoader

_data_loader: Optional[_DataLoader] = None


def _get_loader() -> _DataLoader:
    global _data_loader
    if _data_loader is None:
        _data_loader = _DataLoader(tms=_tms, kg=_kg, parser=_parser)
    return _data_loader


class IngestTextsRequest(BaseModel):
    texts: list[str]
    source_document: Optional[str] = None
    stage: str = "validated"


class IngestDocumentRequest(BaseModel):
    content: str
    source_document: Optional[str] = None
    stage: str = "candidate"
    metadata: dict = {}


class CandidateFactRequest(BaseModel):
    facts: list[dict] = []
    texts: list[str] = []
    source_document: Optional[str] = None


class CandidateReviewRequest(BaseModel):
    reason: Optional[str] = None


@app.post("/learn/numeracy/basic")
def learn_numeracy_basic(debug: bool = Query(default=False)):
    """Teach baseline numeric literacy (digits, symbols, real/decimal/fraction concepts)."""
    try:
        completed_before = sorted(get_completed_phases(_kg))
        injected = 0
        debug_facts: list[dict] = []
        for phase in ("letters", "digits", "operations", "real_numbers"):
            phase_facts = curriculum_phase_facts(phase)
            injected += _inject_curriculum_phase(
                phase,
                source_document="math_foundation_curriculum",
            )
            if debug:
                debug_facts.extend(phase_facts)
        for fact in basic_numeracy_facts():
            try:
                _kg.add(
                    fact["subject"],
                    fact["relation"],
                    fact["object"],
                    float(fact.get("confidence", 1.0)),
                    {
                        "source_type": fact.get("source_type", "curriculum"),
                        "source_document": fact.get("source_document", "numeracy_basic"),
                        "timestamp": time.time(),
                        "stage": "validated",
                    },
                )
                injected += 1
                if debug:
                    debug_facts.append(fact)
            except Exception:
                continue
        completed = sorted(get_completed_phases(_kg))
        response = {
            "ok": True,
            "taught": injected,
            "scope": ["digits", "symbols", "integer", "decimal", "fraction", "real"],
            "completed_phases": completed,
        }
        if debug:
            response["debug"] = _curriculum_debug_payload(
                phase="basic",
                facts=debug_facts,
                completed_before=completed_before,
                completed_after=completed,
                extra={"mode": "numeracy_basic"},
            )
        return response
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.post("/learn/curriculum/phase/{phase}")
def learn_curriculum_phase(phase: str, debug: bool = Query(default=False)):
    """Teach one curriculum phase in order: letters -> digits -> operations -> real_numbers -> calculus."""
    try:
        phase = str(phase).strip().lower()
        if phase not in CURRICULUM_PHASES:
            raise HTTPException(status_code=400, detail=f"Unknown phase: {phase}")

        completed = get_completed_phases(_kg)
        missing_prev = missing_prerequisite_phases(completed, phase)
        if missing_prev:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Prerequisite phases missing",
                    "missing": missing_prev,
                },
            )

        completed_before = sorted(get_completed_phases(_kg))
        phase_facts = curriculum_phase_facts(phase)
        injected = _inject_curriculum_phase(
            phase,
            source_document="math_foundation_curriculum",
        )
        completed_after = sorted(get_completed_phases(_kg))
        response = {
            "ok": True,
            "phase": phase,
            "taught": injected,
            "completed_phases": completed_after,
        }
        if debug:
            response["debug"] = _curriculum_debug_payload(
                phase=phase,
                facts=phase_facts,
                completed_before=completed_before,
                completed_after=completed_after,
                extra={"mode": "curriculum_phase"},
            )
        return response
    except HTTPException:
        raise
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/learn/bootstrap/plan")
def get_learning_bootstrap_plan():
    """Return recommended space-first bootstrap sequence for human-like staged learning."""
    try:
        return {
            "model": "concept_tensor",
            "notes": [
                "A concept is the weighted composition of its representations across spaces.",
                "Not every concept must exist in every space.",
                "Higher-level spaces should be enabled only after prerequisite spaces stabilize.",
            ],
            "stages": SPACE_BOOTSTRAP_PLAN,
            "active_defaults": list(DEFAULT_SPACES),
        }
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.post("/learn/reset")
def reset_learning_state(
    confirm: bool = Query(default=False),
    mode: str = Query(default="soft", pattern="^(soft|hard|full)$"),
    include_archives: bool = Query(default=False),
):
    """Reset learning state.

    Modes:
    - soft: Clear memory, reload from existing graph.json (current behavior)
    - hard: Clear memory, DELETE graph.json, reload from seed knowledge
    - full: Clear memory, DELETE graph.json, reload seed, retrain JEPA
    """
    try:
        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Pass confirm=true to reset learning state.",
            )
        result = _reset_learning_state(include_archives=include_archives, mode=mode)
        return {
            "ok": True,
            "mode": mode,
            "reset": result,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/seed/status")
def seed_status():
    """Return the status of seed knowledge from TXT files."""
    try:
        txt_files = list(SEED_TXT_DIR.glob("*.txt")) if SEED_TXT_DIR.exists() else []

        txt_triple_count = 0
        for s, r, o, c in _kg.triples:
            metadata = _kg.get_metadata(s, r, o)
            if metadata.get("source_type") == "text_seed":
                txt_triple_count += 1

        from core.numeracy import get_completed_phases
        completed_phases = get_completed_phases(_kg)

        return {
            "status": "ok",
            "seed_txt_directory_exists": SEED_TXT_DIR.exists(),
            "seed_txt_count": len(txt_files),
            "seed_txts": [f.name for f in txt_files],
            "kg_triples_total": len(_kg.triples),
            "kg_triples_from_texts": txt_triple_count,
            "completed_curriculum_phases": sorted(completed_phases),
            "all_phases_complete": len(completed_phases) == 6,
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/learn/curriculum/economy/phase/{phase}")
def learn_economy_curriculum_phase(phase: str, debug: bool = Query(default=False)):
    """Teach one economy curriculum phase in order."""
    try:
        phase = str(phase).strip().lower()
        if phase not in ECONOMY_CURRICULUM_PHASES:
            raise HTTPException(status_code=400, detail=f"Unknown economy curriculum phase: {phase}")

        completed = _track_completed_phases("economy")
        missing_prev = _track_missing_prerequisite_phases("economy", completed, phase)
        if missing_prev:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Prerequisite phases missing",
                    "missing": missing_prev,
                },
            )

        completed_before = sorted(_track_completed_phases("economy"))
        phase_facts = _track_phase_facts("economy", phase)
        injected = _inject_track_phase(
            "economy",
            phase,
            source_document="economy_graph_curriculum",
        )
        completed_after = sorted(_track_completed_phases("economy"))
        response = {
            "ok": True,
            "track": "economy",
            "phase": phase,
            "taught": injected,
            "completed_phases": completed_after,
        }
        if debug:
            response["debug"] = _curriculum_debug_payload(
                phase=phase,
                facts=phase_facts,
                completed_before=completed_before,
                completed_after=completed_after,
                extra={"mode": "curriculum_phase", "track": "economy"},
                phase_metrics=build_economy_phase_metrics(_kg),
            )
        return response
    except HTTPException:
        raise
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/learn/curriculum/status")
def get_curriculum_status():
    try:
        completed = sorted(get_completed_phases(_kg))
        missing = [phase for phase in CURRICULUM_PHASES if phase not in completed]
        snapshot = get_numeracy_snapshot(_kg)
        phase_metrics = _build_curriculum_phase_metrics()
        return {
            "curriculum": {
                "completed": completed,
                "missing": missing,
                "total_phases": len(CURRICULUM_PHASES),
                "progress": round(len(completed) / max(1, len(CURRICULUM_PHASES)), 3),
                "phase_metrics": phase_metrics,
            },
            "numeracy": {
                "known_digits": sorted(snapshot.get("digits", set())),
                "known_symbols": sorted(snapshot.get("symbols", set())),
                "known_concepts": sorted(snapshot.get("concepts", set())),
            },
        }
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/learn/curriculum/economy/status")
def get_economy_curriculum_status():
    try:
        return economy_curriculum_status(_kg)
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/learn/primary/readiness")
def get_primary_readiness_status():
    """Audit current knowledge coverage against a primary-school graduation profile."""
    try:
        return build_primary_readiness_report(_kg)
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/learn/primary/plan")
def get_primary_weekly_plan(weeks: int = Query(default=6, ge=1, le=24)):
    """Generate an automated weekly training plan based on readiness gaps."""
    try:
        return build_primary_weekly_plan(_kg, weeks=weeks)
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/learn/primary/drip/plan")
def get_primary_drip_plan(
    cycles: int = Query(default=12, ge=1, le=500),
    new_concepts_per_cycle: int = Query(default=3, ge=1, le=8),
    reinforcement_concepts_per_cycle: int = Query(default=2, ge=0, le=8),
):
    """Generate a no-wait drip learning plan with reinforcement for each cycle."""
    try:
        return build_primary_drip_plan(
            _kg,
            cycles=cycles,
            new_concepts_per_cycle=new_concepts_per_cycle,
            reinforcement_concepts_per_cycle=reinforcement_concepts_per_cycle,
        )
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/learn/primary/abstraction/pending")
def get_primary_abstraction_pending(limit: int = Query(default=100, ge=1, le=5000)):
    """List concept seeds that are still pending abstraction."""
    try:
        items = _list_pending_abstractions(limit=limit)
        return {
            "count": len(items),
            "items": items,
        }
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.post("/learn/primary/abstraction/resolve")
def resolve_primary_abstraction_pending(
    limit: int = Query(default=25, ge=1, le=5000),
    reinforcement_confidence: float = Query(default=0.95, ge=0.1, le=1.0),
):
    """Reinforce and close pending concept abstractions."""
    try:
        result = _resolve_pending_abstractions(limit=limit, reinforcement_confidence=reinforcement_confidence)
        return {
            "ok": True,
            "reinforcement_confidence": float(reinforcement_confidence),
            **result,
        }
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/semantic/concept/{concept}/embedding")
def semantic_concept_embedding(concept: str):
    """Return persistent per-space embeddings and pairwise space differences for a concept."""
    try:
        concept = str(concept).strip().lower()
        if not concept:
            raise HTTPException(status_code=400, detail="concept is required")
        return _concept_space_embeddings.get_concept(concept)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/semantic/concept/{concept}/trace")
def semantic_concept_trace(
    concept: str,
    max_depth: int = Query(default=3, ge=1, le=4),
    max_edges: int = Query(default=250, ge=50, le=1000),
):
    """Return concept-centered trace showing what was pulled from each space with confidences."""
    try:
        concept = str(concept).strip().lower()
        if not concept:
            raise HTTPException(status_code=400, detail="concept is required")
        return _build_concept_trace(concept, max_depth=max_depth, max_edges=max_edges)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.post("/learn/primary/drip/run")
def run_primary_drip(
    cycles: int = Query(default=12, ge=1, le=500),
    new_concepts_per_cycle: int = Query(default=3, ge=1, le=8),
    reinforcement_concepts_per_cycle: int = Query(default=2, ge=0, le=8),
    exposure_confidence: float = Query(default=0.6, ge=0.1, le=1.0),
    reinforcement_confidence: float = Query(default=0.95, ge=0.1, le=1.0),
    target_coverage: float | None = Query(default=None, ge=0.0, le=1.0),
    max_total_cycles: int | None = Query(default=None, ge=1, le=5000),
):
    """Run immediate drip feeding: each cycle teaches new concepts and reinforces known ones."""
    try:
        readiness_before = build_primary_readiness_report(_kg)

        injected_new = 0
        reinforced = 0
        executed_cycles: list[dict[str, object]] = []
        stop_reason = "planned_cycles_completed"
        cycle_limit = max_total_cycles if max_total_cycles is not None else cycles
        cycle_limit = max(1, cycle_limit)
        cycle_index = 0

        while cycle_index < cycle_limit:
            current_readiness = build_primary_readiness_report(_kg)
            if target_coverage is not None and float(current_readiness.get("overall_coverage", 0.0)) >= float(target_coverage):
                stop_reason = "target_coverage_reached"
                break

            plan = build_primary_drip_plan(
                _kg,
                cycles=1,
                new_concepts_per_cycle=new_concepts_per_cycle,
                reinforcement_concepts_per_cycle=reinforcement_concepts_per_cycle,
            )
            cycle = (plan.get("drip_plan") or [{}])[0]
            domain = str(cycle.get("domain", "general"))
            new_concepts = [str(c) for c in cycle.get("new_concepts", [])]
            reinforcement_concepts = [str(c) for c in cycle.get("reinforcement_concepts", [])]
            cycle_index += 1

            timestamp = time.time()
            for concept in new_concepts:
                fact_meta = {
                    "source_type": "primary_drip",
                    "source_document": f"primary_drip_cycle_{cycle_index}",
                    "timestamp": timestamp,
                    "stage": "validated",
                    "learning_mode": "exposure",
                    "abstraction_pending": True,
                }
                _kg.add(
                    domain,
                    "knows_concept",
                    concept,
                    float(exposure_confidence),
                    fact_meta,
                )
                _update_concept_space_embeddings_from_fact(domain, "knows_concept", concept, float(exposure_confidence), fact_meta)
                injected_new += 1

            for concept in reinforcement_concepts:
                fact_meta = {
                    "source_type": "primary_drip",
                    "source_document": f"primary_drip_cycle_{cycle_index}",
                    "timestamp": timestamp,
                    "stage": "validated",
                    "learning_mode": "reinforcement",
                    "abstraction_pending": False,
                }
                _kg.add(
                    domain,
                    "knows_concept",
                    concept,
                    float(reinforcement_confidence),
                    fact_meta,
                )
                _update_concept_space_embeddings_from_fact(domain, "knows_concept", concept, float(reinforcement_confidence), fact_meta)
                reinforced += 1

            executed_cycles.append({
                "cycle": cycle_index,
                "domain": domain,
                "new_concepts": new_concepts,
                "reinforcement_concepts": reinforcement_concepts,
            })

        if target_coverage is not None and cycle_index >= cycle_limit and stop_reason != "target_coverage_reached":
            stop_reason = "max_total_cycles_reached"

        readiness_after = build_primary_readiness_report(_kg)
        delta = round(
            float(readiness_after.get("overall_coverage", 0.0))
            - float(readiness_before.get("overall_coverage", 0.0)),
            3,
        )

        return {
            "ok": True,
            "mode": "continuous_drip",
            "requested": {
                "cycles": cycles,
                "new_concepts_per_cycle": new_concepts_per_cycle,
                "reinforcement_concepts_per_cycle": reinforcement_concepts_per_cycle,
                "exposure_confidence": exposure_confidence,
                "reinforcement_confidence": reinforcement_confidence,
                "target_coverage": target_coverage,
                "max_total_cycles": max_total_cycles,
            },
            "applied": {
                "cycles": len(executed_cycles),
                "new_concepts_ingested": injected_new,
                "reinforcement_updates": reinforced,
            },
            "target_reached": bool(target_coverage is not None and float(readiness_after.get("overall_coverage", 0.0)) >= float(target_coverage)),
            "stop_reason": stop_reason,
            "coverage": {
                "before": readiness_before.get("overall_coverage", 0.0),
                "after": readiness_after.get("overall_coverage", 0.0),
                "delta": delta,
            },
            "executed_cycles": executed_cycles,
        }
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}

# =========================
# ✅ INDUCTIVE LEARNING (Pattern extraction from examples)
from core.inductive_learner import InductiveLearner, CuriousLearner, AnalogicalReasoner

_inductive_learner = InductiveLearner()
_curious_learner = CuriousLearner(_inductive_learner)
_analogy_reasoner = AnalogicalReasoner(_inductive_learner, config_path="config/analogy_map.json")


class InductiveRequest(BaseModel):
    predicate: str
    examples: list[list]


class AskRequest(BaseModel):
    predicate: str
    subject: Any


class FeedbackRequest(BaseModel):
    predicate: str
    subject: Any
    correct_object: Any


class PredictRequest(BaseModel):
    predicate: str
    subject: Any


class AnalogyRequest(BaseModel):
    source: str
    target: str


@app.post("/learn/inductive")
def learn_inductive(req: InductiveRequest):
    try:
        predicate = req.predicate
        examples = [(s, o) for s, o in req.examples]
        if not predicate or not examples:
            raise HTTPException(status_code=400, detail="Missing predicate or examples")
        learned_rule = _inductive_learner.add_examples(predicate, examples)
        if learned_rule:
            return {
                "ok": True,
                "predicate": predicate,
                "rule": {
                    "type": learned_rule.rule_type,
                    "description": learned_rule.description,
                    "confidence": learned_rule.confidence,
                    "examples_used": len(_inductive_learner.examples.get(predicate, [])),
                },
            }
        return {
            "ok": True,
            "predicate": predicate,
            "message": "Need more examples (at least 3)",
            "examples_used": len(_inductive_learner.examples.get(predicate, [])),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.post("/learn/ask")
def learn_ask(req: AskRequest):
    try:
        predicate = req.predicate
        subject = req.subject
        if not predicate or subject is None:
            raise HTTPException(status_code=400, detail="Missing predicate or subject")
        question = _curious_learner.ask(predicate, subject)
        return {"ok": True, "question": question}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.post("/learn/feedback")
def learn_feedback(req: FeedbackRequest):
    try:
        predicate = req.predicate
        subject = req.subject
        correct_object = req.correct_object
        if not predicate or subject is None or correct_object is None:
            raise HTTPException(status_code=400, detail="Missing predicate, subject, or correct_object")
        _curious_learner.learn_from_feedback(predicate, subject, correct_object)
        learned_rule = _inductive_learner.add_examples(predicate, [(subject, correct_object)])
        return {
            "ok": True,
            "message": f"Learned: {subject} {predicate} {correct_object}",
            "pattern_found": learned_rule.description if learned_rule else "Pattern not yet found, need more examples",
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.post("/learn/predict")
def learn_predict(req: PredictRequest):
    try:
        predicate = req.predicate
        subject = req.subject
        if not predicate or subject is None:
            raise HTTPException(status_code=400, detail="Missing predicate or subject")
        prediction = _inductive_learner.predict(predicate, subject)
        confidence = _inductive_learner.get_confidence(predicate)
        return {
            "ok": True,
            "predicate": predicate,
            "subject": subject,
            "prediction": prediction,
            "confidence": confidence,
            "has_rule": prediction is not None,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/learn/rules")
def get_learn_rules():
    try:
        summary = _curious_learner.get_learning_summary()
        return {"ok": True, "summary": summary}
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.post("/learn/analogy")
def learn_analogy(req: AnalogyRequest):
    try:
        source = req.source
        target = req.target
        if not source or not target:
            raise HTTPException(status_code=400, detail="Missing source or target")
        result = _analogy_reasoner.transfer_knowledge(source, target)
        if result:
            for rule in result.get("rules", []):
                _inductive_learner.rules[target].append(rule)
            return {
                "ok": True,
                "source": source,
                "target": target,
                "rules": [
                    {"type": r.rule_type, "description": r.description, "confidence": r.confidence}
                    for r in result.get("rules", [])
                ],
                "explanation": result.get("explanation"),
            }
        raise HTTPException(status_code=404, detail=f"No analogy found between {source} and {target}")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


@app.get("/learn/inductive/status")
def get_inductive_learning_status():
    try:
        return {
            "ok": True,
            "total_examples": sum(len(ex) for ex in _inductive_learner.examples.values()),
            "total_rules": sum(len(rules) for rules in _inductive_learner.rules.values()),
            "predicates_with_rules": list(_inductive_learner.rules.keys()),
            "pending_questions": len(_curious_learner.pending_questions),
            "learning_history_count": len(_curious_learner.learning_history),
        }
    except Exception:
        logger.exception("Request failed")
        return {"error": "Internal server error"}


class IngestFactsRequest(BaseModel):
    facts: list[dict] = []
    texts: list[str] = []
    documents: list[IngestDocumentRequest] = []
    transitions: list[dict] = []
    source_document: Optional[str] = None
    stage: str = "validated"


@app.post("/ingest/texts")
def ingest_texts(req: IngestTextsRequest, _auth=Security(_require_ingest_key)):
    """Parse natural-language statements and inject the resulting triples."""
    try:
        _check_ingest_rate_limit("ingest_texts")
        loader = _get_loader()
        result = loader.ingest_texts_with_context(
            req.texts,
            source_document=req.source_document,
            stage=req.stage,
        )
        _log_ingest_event("ingest_texts", "/ingest/texts", {
            "source_document": req.source_document,
            "stage": req.stage,
            "texts": req.texts,
            "result": result,
        })
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Ingest texts failed")
        return {"error": "Internal server error"}


@app.post("/ingest/seed")
def ingest_seed(_auth=Security(_require_ingest_key)):
    """Inject the built-in domain seed knowledge (flood/disaster domain)."""
    try:
        _check_ingest_rate_limit("ingest_seed")
        loader = _get_loader()
        result = loader.ingest_seed_knowledge()
        _log_ingest_event("ingest_seed", "/ingest/seed", {"result": result})
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Ingest seed failed")
        return {"error": "Internal server error"}


@app.post("/ingest")
def ingest(req: IngestFactsRequest, _auth=Security(_require_ingest_key)):
    """Bulk-ingest facts, free-text statements, and/or RL transition examples.

    Body schema (all fields optional):
    {
      "facts":       [{"subject": ..., "relation": ..., "object": ..., "confidence": ...}],
      "texts":       ["rain causes flood 0.9", ...],
      "transitions": [{"state": [...], "action": "barrier", "reward": 3.0, "next_state": [...]}]
    }
    """
    try:
        _check_ingest_rate_limit("ingest")
        loader = _get_loader()
        triples_added = 0
        candidates_added = 0
        candidate_ids = []
        documents_done = 0
        transitions_done = 0
        q_updates = 0

        for fact in req.facts:
            normalized_fact = _normalize_teaching_fact(fact)
            if req.stage == "candidate":
                candidate_id = loader.ingest_candidate_triple({**normalized_fact, "source_document": req.source_document})
                if candidate_id:
                    candidates_added += 1
                    candidate_ids.append(candidate_id)
            elif loader.ingest_triple({**normalized_fact, "source_document": req.source_document}):
                triples_added += 1
                _update_concept_space_embeddings_from_fact(
                    str(normalized_fact.get("subject", "")),
                    str(normalized_fact.get("relation", "")),
                    str(normalized_fact.get("object", "")),
                    float(normalized_fact.get("confidence", 1.0)),
                    {k: v for k, v in normalized_fact.items() if k not in {"subject", "relation", "object", "confidence", "negation"}},
                )

        if req.texts:
            r = loader.ingest_texts_with_context(
                req.texts,
                source_document=req.source_document,
                stage=req.stage,
            )
            triples_added += r.get("triples", 0)
            candidates_added += r.get("candidates", 0)
            candidate_ids.extend(r.get("candidate_ids", []))

        for document in req.documents:
            r = loader.ingest_document(
                document.content,
                source_document=document.source_document or req.source_document or "api_document",
                stage=document.stage or req.stage,
                metadata=document.metadata,
            )
            documents_done += r.get("documents", 0)
            triples_added += r.get("triples", 0)
            candidates_added += r.get("candidates", 0)
            candidate_ids.extend(r.get("candidate_ids", []))

        if req.transitions:
            q_updates = loader.ingest_transitions(req.transitions)
            transitions_done = len(req.transitions)

        result = {
            "triples":     triples_added,
            "candidates":  candidates_added,
            "candidate_ids": candidate_ids,
            "documents":   documents_done,
            "transitions": transitions_done,
            "q_updates":   q_updates,
        }
        _log_ingest_event("ingest", "/ingest", {
            "source_document": req.source_document,
            "stage": req.stage,
            "facts_count": len(req.facts),
            "texts_count": len(req.texts),
            "documents_count": len(req.documents),
            "transitions_count": len(req.transitions),
            "result": result,
        })
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Ingest failed")
        return {"error": "Internal server error"}


@app.post("/ingest/documents")
def ingest_documents(req: IngestDocumentRequest, _auth=Security(_require_ingest_key)):
    """Ingest a full document with paragraph/sentence provenance tracking."""
    try:
        _check_ingest_rate_limit("ingest_documents")
        loader = _get_loader()
        result = loader.ingest_document(
            req.content,
            source_document=req.source_document or "api_document",
            stage=req.stage,
            metadata=req.metadata,
        )
        _log_ingest_event("ingest_documents", "/ingest/documents", {
            "source_document": req.source_document or "api_document",
            "stage": req.stage,
            "metadata": req.metadata,
            "result": result,
        })
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Ingest documents failed")
        return {"error": "Internal server error"}


@app.post("/ingest/pdf")
async def ingest_pdf(
    file: UploadFile = File(...),
    source_document: Optional[str] = Form(default=None),
    stage: str = Form(default="candidate"),
    metadata: Optional[str] = Form(default=None),
    debug: bool = Query(default=False),
    _auth=Security(_require_ingest_key),
):
    """Ingest a single PDF and stage extracted knowledge with provenance."""
    try:
        _require_feature(ENABLE_PDF_INGEST, "pdf_ingest")
        _check_ingest_rate_limit("ingest_pdf")
        if not file.filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing file name.")

        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only PDF files are supported.")

        payload = await file.read()
        if len(payload) > PDF_MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="PDF exceeds size limit.")

        parsed_metadata = {}
        if metadata:
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="metadata must be valid JSON.") from exc

        curriculum_phase = str(parsed_metadata.get("curriculum_phase", "")).strip().lower()
        curriculum_track = _resolve_curriculum_track(parsed_metadata.get("curriculum_track"), curriculum_phase) if curriculum_phase else "math"
        teach_curriculum = bool(parsed_metadata.get("teach_curriculum")) and bool(curriculum_phase)
        if curriculum_phase:
            missing_prev = _track_missing_prerequisite_phases(curriculum_track, _track_completed_phases(curriculum_track), curriculum_phase)
            if missing_prev:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "Prerequisite phases missing",
                        "missing": missing_prev,
                    },
                )

        loader = _get_loader()
        completed_before = sorted(get_completed_phases(_kg))
        archive_info = _archive_pdf_if_needed(
            payload,
            source_document=source_document or file.filename,
            metadata=parsed_metadata,
        )
        result = loader.ingest_pdf_document(
            payload,
            source_document=source_document or file.filename,
            stage=stage,
            metadata=parsed_metadata,
        )
        if teach_curriculum:
            curriculum_payload = {
                "track": curriculum_track,
                "phase": curriculum_phase,
                "taught": _inject_track_phase(
                    curriculum_track,
                    curriculum_phase,
                    source_document=source_document or file.filename,
                    source_type="pdf_curriculum",
                ),
                "completed_phases": sorted(_track_completed_phases(curriculum_track)),
            }
            result["curriculum"] = curriculum_payload
            if debug:
                result["debug"] = {
                    "mode": "pdf_upload",
                    "source_document": source_document or file.filename,
                    "stage": stage,
                    "metadata": parsed_metadata,
                    "archive": archive_info,
                    "completed_before": completed_before,
                    "completed_after": curriculum_payload["completed_phases"],
                    "curriculum_track": curriculum_track,
                    "curriculum_phase": curriculum_phase,
                }
        _log_ingest_event("ingest_pdf", "/ingest/pdf", {
            "source_document": source_document or file.filename,
            "stage": stage,
            "metadata": parsed_metadata,
            "size_bytes": len(payload),
            "result": result,
        })
        return result
    except PDFIngestionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception:
        logger.exception("Ingest PDF failed")
        return {"error": "Internal server error"}


@app.post("/ingest/pdfs")
async def ingest_pdfs(
    files: list[UploadFile] = File(...),
    stage: str = Form(default="candidate"),
    metadata: Optional[str] = Form(default=None),
    debug: bool = Query(default=False),
    _auth=Security(_require_ingest_key),
):
    """Batch ingest PDFs and return aggregate ingestion stats."""
    try:
        _require_feature(ENABLE_PDF_INGEST, "pdf_ingest")
        _check_ingest_rate_limit("ingest_pdfs")
        if not files:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one PDF file is required.")
        if len(files) > PDF_MAX_BATCH_FILES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Too many files in batch.")

        parsed_metadata = {}
        if metadata:
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="metadata must be valid JSON.") from exc

        curriculum_phase = str(parsed_metadata.get("curriculum_phase", "")).strip().lower()
        teach_curriculum = bool(parsed_metadata.get("teach_curriculum")) and bool(curriculum_phase)
        if curriculum_phase:
            if curriculum_phase not in CURRICULUM_PHASES:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown curriculum_phase: {curriculum_phase}")
            missing_prev = missing_prerequisite_phases(get_completed_phases(_kg), curriculum_phase)
            if missing_prev:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "Prerequisite phases missing",
                        "missing": missing_prev,
                    },
                )

        completed_before = sorted(get_completed_phases(_kg))
        loader = _get_loader()
        total_size = 0
        aggregate = {
            "documents": 0,
            "pages": 0,
            "sentences": 0,
            "triples": 0,
            "transitions": 0,
            "q_updates": 0,
            "candidates": 0,
            "candidate_ids": [],
            "skipped": 0,
            "failed": 0,
            "failed_documents": [],
        }

        for upload in files:
            filename = upload.filename or "uploaded.pdf"
            if not filename.lower().endswith(".pdf"):
                raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=f"Unsupported file type: {filename}")

            payload = await upload.read()
            total_size += len(payload)
            archive_info = _archive_pdf_if_needed(
                payload,
                source_document=filename,
                metadata=parsed_metadata,
            )
            if total_size > PDF_MAX_BATCH_TOTAL_BYTES:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Batch size exceeds limit.")
            if len(payload) > PDF_MAX_FILE_SIZE_BYTES:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"{filename} exceeds per-file size limit.")

            try:
                result = loader.ingest_pdf_document(
                    payload,
                    source_document=filename,
                    stage=stage,
                    metadata=parsed_metadata,
                )
                if debug:
                    result.setdefault("debug", {})
                    result["debug"].update({"archive": archive_info, "source_document": filename})
                for key in ("documents", "pages", "sentences", "triples", "transitions", "q_updates", "candidates", "skipped", "failed"):
                    aggregate[key] += int(result.get(key, 0))
                aggregate["candidate_ids"].extend(result.get("candidate_ids", []))
            except PDFIngestionError:
                aggregate["failed"] += 1
                aggregate["failed_documents"].append({"name": filename, "error": "parse_failure"})

        if teach_curriculum:
            curriculum_payload = {
                "phase": curriculum_phase,
                "taught": _inject_curriculum_phase(
                    curriculum_phase,
                    source_document=curriculum_phase,
                    source_type="pdf_curriculum",
                ),
                "completed_phases": sorted(get_completed_phases(_kg)),
            }
            aggregate["curriculum"] = curriculum_payload
            if debug:
                aggregate["debug"] = {
                    "mode": "pdf_batch",
                    "stage": stage,
                    "metadata": parsed_metadata,
                    "completed_before": completed_before,
                    "completed_after": curriculum_payload["completed_phases"],
                    "curriculum_phase": curriculum_phase,
                    "files": [upload.filename or "uploaded.pdf" for upload in files],
                }

        _log_ingest_event("ingest_pdfs", "/ingest/pdfs", {
            "documents": len(files),
            "stage": stage,
            "metadata": parsed_metadata,
            "total_size": total_size,
            "result": aggregate,
        })
        return aggregate
    except HTTPException:
        raise
    except Exception:
        logger.exception("Batch ingest PDFs failed")
        return {"error": "Internal server error"}


@app.post("/ingest/candidates")
def ingest_candidates(req: CandidateFactRequest, _auth=Security(_require_ingest_key)):
    """Stage facts and texts as candidate knowledge before promotion."""
    try:
        _check_ingest_rate_limit("ingest_candidates")
        loader = _get_loader()
        candidate_ids = []
        for fact in req.facts:
            candidate_id = loader.ingest_candidate_triple({**fact, "source_document": req.source_document})
            if candidate_id:
                candidate_ids.append(candidate_id)
        if req.texts:
            result = loader.ingest_texts_with_context(
                req.texts,
                source_document=req.source_document,
                stage="candidate",
            )
            candidate_ids.extend(result.get("candidate_ids", []))
        result = {"candidates": len(candidate_ids), "candidate_ids": candidate_ids}
        _log_ingest_event("ingest_candidates", "/ingest/candidates", {
            "source_document": req.source_document,
            "facts_count": len(req.facts),
            "texts_count": len(req.texts),
            "result": result,
        })
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Ingest candidates failed")
        return {"error": "Internal server error"}


@app.get("/ingest/candidates")
def list_ingest_candidates(limit: int = Query(default=50, ge=1, le=200), _auth=Security(_require_ingest_key)):
    """Return the pending candidate knowledge review queue."""
    try:
        loader = _get_loader()
        candidates = loader.get_review_queue()[:limit]
        return {"candidates": candidates, "count": len(candidates)}
    except Exception:
        logger.exception("List candidates failed")
        return {"error": "Internal server error"}


@app.post("/ingest/candidates/{candidate_id}/promote")
def promote_ingest_candidate(candidate_id: str, _auth=Security(_require_ingest_key)):
    """Promote a candidate triple into the active belief graph."""
    try:
        _check_ingest_rate_limit("promote_candidate")
        loader = _get_loader()
        if not loader.promote_candidate(candidate_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found or not pending.")
        result = {"ok": True, "candidate_id": candidate_id}
        _log_ingest_event("promote_candidate", "/ingest/candidates/{candidate_id}/promote", result)
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Promote candidate failed")
        return {"error": "Internal server error"}


@app.get("/memory/episodic")
def memory_episodic(limit: int = Query(default=50, ge=1, le=500)):
    """Return recent episodic memory entries."""
    try:
        if _thought_loop is None:
            return {"episodes": [], "count": 0}
        episodes = _thought_loop.memory.get_episodic_memory(limit=limit)
        return {"episodes": episodes, "count": len(episodes)}
    except Exception:
        logger.exception("Episodic memory request failed")
        return {"error": "Internal server error"}


@app.get("/memory/emotional_trend")
def memory_emotional_trend(n: int = Query(default=10, ge=1, le=200)):
    """Return average emotion vector and per-episode timeline over recent N episodes."""
    try:
        if _thought_loop is None:
            return {"avg_vector": [0.0] * 5, "timeline": [], "count": 0}
        episodes = _thought_loop.memory.get_episodic_memory(limit=n)
        timeline = []
        sum_vec = [0.0] * 5
        valid_count = 0
        for i, ep in enumerate(episodes):
            emotion = ep.get("emotion")
            if emotion and isinstance(emotion, (list, tuple)) and len(emotion) >= 5:
                timeline.append({
                    "episode": i + 1,
                    "fear": emotion[0],
                    "anger": emotion[1],
                    "sadness": emotion[2],
                    "surprise": emotion[3],
                    "calm": emotion[4],
                })
                for j in range(5):
                    sum_vec[j] += emotion[j]
                valid_count += 1
        avg_vector = [round(v / max(1, valid_count), 4) for v in sum_vec] if valid_count else [0.0] * 5
        return {"avg_vector": avg_vector, "timeline": timeline, "count": valid_count}
    except Exception:
        logger.exception("Emotional trend request failed")
        return {"error": "Internal server error"}


@app.post("/ingest/candidates/{candidate_id}/reject")
def reject_ingest_candidate(candidate_id: str, req: CandidateReviewRequest, _auth=Security(_require_ingest_key)):
    """Reject a candidate triple and keep the review audit trail."""
    try:
        _check_ingest_rate_limit("reject_candidate")
        loader = _get_loader()
        if not loader.reject_candidate(candidate_id, req.reason):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found or not pending.")
        result = {"ok": True, "candidate_id": candidate_id}
        _log_ingest_event("reject_candidate", "/ingest/candidates/{candidate_id}/reject", {
            "candidate_id": candidate_id,
            "reason": req.reason,
        })
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Reject candidate failed")
        return {"error": "Internal server error"}
