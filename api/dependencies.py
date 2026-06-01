from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
import main
import json
import time
import random
import ast
import re
import threading
import logging
import shutil
import math
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional, Any
from types import SimpleNamespace
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
from core.symbolic_math import compute_arithmetic, compute_calculus, compute_definite_integral, compute_derivative_advanced, compute_algebra, solve_equation, detect_sequence_pattern
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
from core.inductive_learner import InductiveLearner, CuriousLearner, AnalogicalReasoner
from core.data_loader import DataLoader as _DataLoader

logger = logging.getLogger(__name__)

# Auth
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def _require_ingest_key(api_key: str | None = Security(_api_key_header)):
    if INGEST_API_KEY is None:
        return
    if api_key != INGEST_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-API-Key header.",
        )

# Core instances
_kg = KnowledgeGraph()
_tms = LiteTMS(decay_rate=TMS_DECAY_RATE, min_confidence=TMS_MIN_CONFIDENCE)
_parser = SemanticParser(enable_spacy_dep=ENABLE_SPACY_DEP_PARSER, spacy_model_name=SPACY_MODEL_NAME)
_graph_store = GraphStore(GRAPH_FILE)
_concept_learner = ConceptLearner(_tms)
_rule_learner = RuleLearner(_tms)
_online_learner = OnlineLearner(_tms)
_kg.tms = _tms
_relations_builder = None

# Globals
_inference_lock = threading.Lock()
inference_count = 0
last_time = time.time()
recent_states = deque(maxlen=6)

# JEPA
_jepa = JEPAModel()
_jepa_lock = threading.Lock()
_jepa_recent_errors: deque = deque(maxlen=CURRICULUM_STABILITY_WINDOW)
_thought_loop = None
_ingest_rate_lock = threading.Lock()
_ingest_rate_bucket: dict[str, deque] = defaultdict(deque)
_loop_artifact_lock = threading.Lock()
_loop_artifacts = deque(maxlen=200)
_training_pdf_archive_root = Path(__file__).resolve().parent.parent / "artifacts" / "training_pdfs"
SEED_TXT_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "seed_texts"
_concept_space_embeddings = ConceptSpaceEmbeddings(Path(__file__).resolve().parent.parent / "artifacts" / "concept_space_embeddings.json")

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

MAX_SIMULATE_STEPS = 50
_FULL_VIEW_CONCEPTS = {
    "number", "integer", "decimal", "fraction", "real", "digits", "digit",
    "letter", "operations", "operation", "addition", "subtraction",
    "multiplication", "division", "derivative", "integral", "limit",
    "function", "logarithm", "log", "ln", "base", "change_of_base",
    "exponent", "inverse_function", "calculus", "logarithms", "real_numbers",
}

# Inductive learning
_inductive_learner = InductiveLearner()
_curious_learner = CuriousLearner(_inductive_learner)
_analogy_reasoner = AnalogicalReasoner(_inductive_learner, config_path=str(Path(__file__).resolve().parent.parent / "config" / "analogy_map.json"))

# Data loader
_data_loader: Optional[_DataLoader] = None

# --- Helper functions ---

def parse_state(state):
    try:
        if isinstance(state, str):
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
        event, route, _mask_value(payload or {}),
    )

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
        "timestamp": time.time(), "phase": phase, "source_document": source_document,
        "path": str(archive_path.relative_to(_training_pdf_archive_root)),
        "bytes": len(payload), "metadata": metadata,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True) + "\n")
    return entry

def _archive_pdf_if_needed(payload: bytes, *, source_document: str, metadata: dict | None = None) -> dict[str, object] | None:
    metadata = dict(metadata or {})
    if not metadata.get("curriculum_phase") and not metadata.get("teach_curriculum"):
        return None
    try:
        return _archive_training_pdf(payload, source_document=source_document, metadata=metadata)
    except Exception:
        logger.exception("Failed to archive training PDF")
        return None

def _inject_curriculum_phase(phase: str, *, source_document: str, source_type: str = "curriculum") -> int:
    injected = 0
    for fact in curriculum_phase_facts(phase):
        try:
            fact_meta = {
                "source_type": source_type,
                "source_document": source_document or fact.get("source_document", "math_foundation_curriculum"),
                "timestamp": time.time(), "stage": "validated", "curriculum_phase": phase,
            }
            _kg.add(fact["subject"], fact["relation"], fact["object"], float(fact.get("confidence", 1.0)), fact_meta)
            _update_concept_space_embeddings_from_fact(str(fact["subject"]), str(fact["relation"]), str(fact["object"]), float(fact.get("confidence", 1.0)), fact_meta)
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
                "timestamp": time.time(), "stage": "validated",
                "curriculum_phase": phase, "curriculum_track": track,
            }
            _kg.add(fact["subject"], fact["relation"], fact["object"], float(fact.get("confidence", 1.0)), fact_meta)
            _update_concept_space_embeddings_from_fact(str(fact["subject"]), str(fact["relation"]), str(fact["object"]), float(fact.get("confidence", 1.0)), fact_meta)
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
    metrics = []
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
        "subject": fact.get("subject"), "relation": fact.get("relation"),
        "object": fact.get("object"), "confidence": float(fact.get("confidence", 1.0)),
        "source_type": fact.get("source_type", "curriculum"), "source_document": fact.get("source_document", ""),
    }

def _curriculum_debug_payload(*, phase: str, facts: list[dict], completed_before: list[str], completed_after: list[str], extra: dict | None = None, phase_metrics: list[dict[str, object]] | None = None) -> dict[str, object]:
    payload = {
        "phase": phase,
        "taught_facts": [_fact_to_debug_entry(fact) for fact in facts],
        "completed_before": completed_before,
        "completed_after": completed_after,
        "phase_metrics": phase_metrics if phase_metrics is not None else _build_curriculum_phase_metrics(),
    }
    if extra:
        payload.update(extra)
    return payload

def _normalize_teaching_fact(fact: dict) -> dict:
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
    hinted = []
    if isinstance(hint_value, str):
        hinted = [part.strip().lower() for part in hint_value.split(",") if part.strip()]
    elif isinstance(hint_value, list):
        hinted = [str(part).strip().lower() for part in hint_value if str(part).strip()]
    for item in hinted:
        if item in set(DEFAULT_SPACES):
            spaces.add(item)
    return sorted(spaces)

def _update_concept_space_embeddings_from_fact(subject: str, relation: str, obj: str, confidence: float, metadata: dict | None = None) -> None:
    if str(relation).lower() != "knows_concept":
        return
    spaces = _spaces_for_fact(subject, relation, obj, metadata)
    _concept_space_embeddings.update_from_fact(
        concept=str(obj), spaces=spaces,
        subject=str(subject), relation=str(relation), obj=str(obj),
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
    facts = []
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
            "confidence": float(c), "spaces": spaces, "metadata": metadata,
        })
    builder = _get_relations_builder()
    relations = builder.build(
        query=normalized, include_spaces=list(DEFAULT_SPACES),
        max_depth=max_depth, max_edges=max_edges,
    )
    relation_edges = [
        {
            "source": str(edge.get("source", "")), "target": str(edge.get("target", "")),
            "space": str(edge.get("space", "")), "relation_type": str(edge.get("relation_type", "")),
            "confidence": float(edge.get("confidence", 0.0)), "provenance": edge.get("provenance", {}),
        }
        for edge in relations.get("edges", [])
    ]
    by_space = {}
    def ensure_space(space: str) -> dict[str, object]:
        if space not in by_space:
            by_space[space] = {
                "space": space, "facts": [], "relation_edges": [],
                "avg_fact_confidence": 0.0, "avg_edge_confidence": 0.0,
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
        "facts": facts, "relation_edges": relation_edges,
        "spaces": sorted(by_space.values(), key=lambda item: item.get("space", "")),
    }

def _list_pending_abstractions(limit: int = 100) -> list[dict[str, object]]:
    pending = []
    for s, r, o, c in getattr(_kg, "triples", []):
        if str(r).lower() != "knows_concept":
            continue
        metadata = dict(_kg.get_metadata(s, r, o) or {})
        if not bool(metadata.get("abstraction_pending")):
            continue
        pending.append({"subject": str(s), "concept": str(o), "confidence": float(c), "metadata": metadata})
    pending.sort(key=lambda item: (float(item.get("confidence", 1.0)), str(item.get("concept", ""))))
    return pending[: max(1, int(limit))]

def _resolve_pending_abstractions(*, limit: int = 25, reinforcement_confidence: float = 0.95) -> dict[str, object]:
    pending = _list_pending_abstractions(limit=limit)
    resolved = 0
    timestamp = time.time()
    items = []
    for item in pending:
        subject = str(item["subject"])
        concept = str(item["concept"])
        fact_meta = {
            "source_type": "abstraction_resolution", "source_document": "pending_abstraction_resolver",
            "timestamp": timestamp, "stage": "validated", "teaching_kind": "rule",
            "learning_mode": "reinforcement", "abstraction_pending": False,
        }
        _kg.add(subject, "knows_concept", concept, float(reinforcement_confidence), fact_meta)
        _update_concept_space_embeddings_from_fact(subject, "knows_concept", concept, float(reinforcement_confidence), fact_meta)
        resolved += 1
        items.append({"subject": subject, "concept": concept, "confidence": float(reinforcement_confidence)})
    return {"resolved": resolved, "items": items, "remaining_pending": len(_list_pending_abstractions(limit=10000))}

# Curriculum
_curriculum = CurriculumController(
    error_tolerance=CURRICULUM_ERROR_TOLERANCE,
    stability_window=CURRICULUM_STABILITY_WINDOW,
)

# --- Multispace embedding & JEPA ---

def embed_state_multispace(state):
    s = parse_state(state)
    return {
        "risk": [int("flood" in s), int("collapse" in s), int("crisis" in s)],
        "structure": [int("damage" in s), int("barrier" in s)],
        "action": [int("evacuated" in s)],
        "temporal": [len(recent_states)],
    }

def _state_to_vec(state_set, step_in_episode: int = 0) -> np.ndarray:
    if not isinstance(state_set, set):
        state_set = set(parse_state(state_set))
    threat_tokens = ["flood", "collapse", "crisis", "damage"]
    threat_count = sum(1 for t in threat_tokens if t in state_set)
    threat_intensity = min(1.0, threat_count / 4.0)
    return np.array([
        float("flood" in state_set), float("collapse" in state_set),
        float("crisis" in state_set), float("damage" in state_set),
        float("barrier" in state_set), float("evacuated" in state_set),
        threat_intensity,
    ], dtype=np.float32)

def _action_idx(action: str) -> int:
    return ACTIONS.index(action)

def _train_jepa_from_qtable(epochs: int = JEPA_WARMUP_EPOCHS, target_loss: float = JEPA_EARLY_STOPPING_LOSS, patience: int = JEPA_EARLY_STOPPING_PATIENCE) -> int:
    keys = list({k[0] for k in main.Q.keys()})
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

_RANDOM_BASELINE_W = np.random.rand(7, 7)

def flatten_embedding(e):
    return np.array(e["risk"] + e["structure"] + e["action"] + e["temporal"])

def _random_baseline_predict(state):
    vec = flatten_embedding(embed_state_multispace(state))
    return np.dot(_RANDOM_BASELINE_W, vec)

def evaluate_actions_jepa(state):
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
            raw = -sum(pred[:3]) / (len(pred[:3]) + 1e-5)
            score = max(min(raw, 5), -5)
        scores[action] = float(score)
    return scores

def simulate_outcome(state, action):
    s = set(parse_state(state))
    reward = 0
    if "flood" in s: reward -= 2
    if "damage" in s: reward -= 3
    if "collapse" in s: reward -= 6
    if "crisis" in s: reward -= 8
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
        reward += 8
        s = {x for x in s if x not in ["flood", "collapse", "crisis"]}
        s.add("evacuated")
        if random.random() < 0.15:
            reward -= 2
            s.add("injury")
    elif action == "none":
        reward -= 3
    if "flood" in s and random.random() < 0.4:
        s.add("damage")
        reward -= 2
    if "damage" in s and random.random() < 0.3:
        s.add("collapse")
        reward -= 3
    if "collapse" in s and random.random() < 0.3:
        s.add("crisis")
        reward -= 4
    if "evacuated" in s:
        reward += 3
        if random.random() < EVACUATED_RETURN_PROBABILITY:
            s.discard("evacuated")
    if not s:
        reward += 2
    return reward, tuple(sorted(s))

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

def plan_actions(state):
    results = {}
    for action in ACTIONS:
        total = sum(simulate_outcome(state, action)[0] for _ in range(5))
        results[action] = total / 5
    return results, max(results, key=results.get)

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
    states_set = set(k[0] for k in main.Q.keys())
    for state in states_set:
        scores = [main.Q.get((state, a), 0) for a in ACTIONS]
        best = max(scores)
        strong = [s for s in scores if abs(best - s) < 0.5]
        if len(strong) > 1:
            count += 1
    return count

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
    base_scores = {a: 0.6 * sim_scores[a] + 0.4 * q_scores[a] for a in ACTIONS}
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
        return base_scores, best, {"thought_trace": thought_trace}
    return base_scores, best

def _jepa_online_update(parsed_state, action: str, step: int = 0) -> None:
    try:
        s_vec = _state_to_vec(set(parsed_state), step_in_episode=step)
        _, next_state = simulate_outcome(parsed_state, action)
        ns_vec = _state_to_vec(set(next_state), step_in_episode=step)
        with _jepa_lock:
            loss = _jepa.update(s_vec, _action_idx(action), ns_vec)
        _jepa_recent_errors.append(loss)
    except Exception:
        logger.exception("JEPA online update failed")

def _build_thought_path(trace: dict) -> list[dict]:
    candidates = list(trace.get("candidates", {}).items())
    top_candidates = [
        {"action": action, "score": info.get("score", 0), "projected_reward": info.get("projected_reward", 0)}
        for action, info in candidates[:2]
    ]
    tension = trace.get("tensions", [])
    leading_tension = tension[0] if tension else None
    return [
        {"stage": "Perception", "detail": f"Parsed state: {', '.join(trace.get('state', [])) or 'empty'}", "data": trace.get("spaces", {})},
        {"stage": "Memory", "detail": "Retrieved working memory, similar failures, and long-term patterns.", "data": trace.get("memory_context", {})},
        {"stage": "Intent", "detail": f"Dominant goal: {trace.get('dominant_goal', 'task_completion')}", "data": trace.get("intent", [])},
        {"stage": "Conflict", "detail": trace.get("resolution", "No conflict resolution available."), "data": leading_tension},
        {"stage": "Simulation", "detail": "Projected the strongest candidate actions.", "data": top_candidates},
        {"stage": "Decision", "detail": f"Selected {trace.get('action', 'none')} with confidence {trace.get('confidence', 0):.2f}.", "data": {"jepa_surprise": trace.get("jepa_surprise", 0), "explanation": trace.get("explanation", [])}},
    ]

def _record_loop_artifacts(state, action: str, base_scores: dict, thought_trace: Optional[dict] = None) -> dict:
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
                state=state_str, include_spaces=list(DEFAULT_SPACES),
                max_depth=1, max_edges=150,
            )
        except Exception:
            logger.exception("Loop visualization generation failed")
    node_count = len(visualization.get("nodes", []))
    edge_count = len(visualization.get("edges", []))
    thought_generated = bool(trace) and bool(thought_path)
    visualization_generated = node_count > 0 and edge_count > 0
    report = {
        "timestamp": time.time(), "state": state_str, "action": action,
        "base_scores": {k: float(v) for k, v in (base_scores or {}).items()},
        "thought_generated": thought_generated, "visualization_generated": visualization_generated,
        "thought_path_steps": len(thought_path), "visual_nodes": node_count, "visual_edges": edge_count,
    }
    if not thought_generated or not visualization_generated:
        logger.warning("LOOP_ARTIFACT_MISSING %s", report)
    with _loop_artifact_lock:
        _loop_artifacts.append(report)
    return report

# Metrics
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

# Search helpers
def _tokenize_query(value: str) -> set[str]:
    raw_tokens = [token for token in re.findall(r"[\w]+", (value or "").lower(), flags=re.UNICODE) if token]
    tokens = set(raw_tokens)
    for token in raw_tokens:
        if "_" in token:
            parts = [part for part in token.split("_") if part]
            tokens.update(parts)
    return tokens

def _extract_sequence_from_query(query: str) -> list[float] | None:
    """Extract a number sequence from a query like '3,6,9,15,24,?'."""
    q = (query or "").strip()
    if not re.search(r'\d+\s*,\s*\d+\s*,\s*\d+', q):
        return None
    # Remove trailing question mark
    q = re.sub(r'\s*\?\s*$', '', q)
    # Split by comma
    parts = [p.strip() for p in q.split(',')]
    numbers: list[float] = []
    for part in parts:
        if not part:
            continue
        try:
            numbers.append(float(part))
        except ValueError:
            return None
    if len(numbers) >= 3:
        return numbers
    return None


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
    if '|' in normalized:
        if re.search(r'\|-?\d+(?:\.\d+)?\|', normalized):
            return {"should_answer": True, "reason": "absolute_value_expression", "matched_tokens": [], "missing_tokens": []}
    if re.search(r"\d+\s*[+\-*/]\s*\d+", normalized):
        return {"should_answer": True, "reason": "arithmetic_expression", "matched_tokens": [], "missing_tokens": []}
    space_parts = normalized.strip().split()
    if len(space_parts) == 2 and space_parts[0].lstrip('-').isdigit() and space_parts[1].lstrip('-').isdigit():
        return {"should_answer": True, "reason": "arithmetic_expression_space", "matched_tokens": [], "missing_tokens": []}
    symbolic_arithmetic = compute_arithmetic(normalized) is not None
    symbolic_calculus = compute_calculus(normalized) is not None
    symbolic_def_integral = bool(re.search(r"integral\s+from\s+[0-9.]+", normalized, flags=re.I))
    symbolic_algebra = bool(re.search(r"det\s*\[|matrix", normalized, flags=re.I))
    symbolic_equation = bool(re.search(r"solve|=", normalized, flags=re.I) and "integral" not in normalized and "derivative" not in normalized and "det" not in normalized)
    symbolic_derivative = bool(re.search(r"d/d[a-z]|derivative\s+of", normalized, flags=re.I))
    if symbolic_arithmetic or symbolic_calculus or symbolic_def_integral or symbolic_algebra or symbolic_equation or symbolic_derivative:
        return {"should_answer": True, "reason": "symbolic_path", "matched_tokens": [], "missing_tokens": []}
    if not tokens:
        return {"should_answer": False, "reason": "no_lexical_tokens", "matched_tokens": [], "missing_tokens": []}
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
        "matched_tokens": matched, "missing_tokens": missing,
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
    explicit_calculus_intent = bool(re.search(r"\b(integral|integrate|derivative|turev)\b|d/d[a-z]", query, flags=re.I))
    _abs_arithmetic = None
    if '|' in query:
        _abs_match = re.search(r'\|(-?\d+(?:\.\d+)?)\|', query)
        if _abs_match:
            try:
                _abs_val = float(_abs_match.group(1))
                _abs_result = abs(_abs_val)
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
    seq_nums = _extract_sequence_from_query(query)
    sequence = detect_sequence_pattern(seq_nums) if seq_nums else None
    arithmetic_key = None
    arithmetic_result = None
    arithmetic_missing = []
    if arithmetic is None and re.search(r"\d+\s*\+?\s*\d+", query):
        match = re.search(r"(\d+)\s*\+\s*(\d+)", query)
        if not match:
            match = re.search(r"(\d+)\s+(\d+)", query)
        if match:
            try:
                left = int(match.group(1))
                right = int(match.group(2))
                result = left + right
                arithmetic = SimpleNamespace(
                    expression=f"{left}+{right}", key=f"plus_{left}_{right}",
                    value=str(result), steps=[f"{left} + {right} = {result}"],
                )
            except (ValueError, TypeError):
                pass
    if arithmetic is None and '^' in query:
        parts = query.split('^')
        if len(parts) == 2:
            try:
                base = int(parts[0].strip())
                exp = int(parts[1].strip())
                result = base ** exp
                arithmetic = SimpleNamespace(
                    expression=f"{base}^{exp}", key=f"pow_{base}_{exp}",
                    value=str(result), steps=[f"{base}^{exp} = {result}"]
                )
            except (ValueError, TypeError):
                pass
    if arithmetic is None and '!' in query:
        match = re.search(r'(\d+)!', query)
        if match:
            try:
                n = int(match.group(1))
                result = math.factorial(n)
                arithmetic = SimpleNamespace(
                    expression=f"{n}!", key=f"factorial_{n}",
                    value=str(result), steps=[f"{n}! = {result}"]
                )
            except (ValueError, TypeError):
                pass
    if arithmetic is None and 'mod' in query.lower():
        match = re.search(r'(\d+)\s+mod\s+(\d+)', query.lower())
        if match:
            try:
                a = int(match.group(1))
                b = int(match.group(2))
                if b != 0:
                    result = a % b
                    arithmetic = SimpleNamespace(
                        expression=f"{a} mod {b}", key=f"mod_{a}_{b}",
                        value=str(result), steps=[f"{a} mod {b} = {result}"]
                    )
            except (ValueError, TypeError):
                pass
    if arithmetic is None and '|' in query:
        match = re.search(r'\|(-?\d+(?:\.\d+)?)\|', query)
        if match:
            try:
                val = float(match.group(1))
                result = abs(val)
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
        arithmetic = None; arithmetic_key = None; arithmetic_result = None; arithmetic_missing = []
    if equation is not None or algebra is not None:
        arithmetic = None; arithmetic_key = None; arithmetic_result = None; arithmetic_missing = []
    calculus_missing = []
    if calculus is not None:
        phase_missing = missing_curriculum_phases(_kg, required_phases_for_calculus())
        if phase_missing:
            calculus_missing = [f"phase:{p}" for p in phase_missing]
            calculus = None
    explicit_log_intent = bool(re.search(r"\b(logarithm|log10|log|ln)\b", query, flags=re.I))
    log_missing = []
    if explicit_log_intent and calculus is not None:
        phase_missing = missing_curriculum_phases(_kg, required_phases_for_logarithms())
        if phase_missing:
            log_missing = [f"phase:{p}" for p in phase_missing]
            calculus = None
    if not tokens and arithmetic is None and calculus is None and def_integral is None and adv_deriv is None and algebra is None and equation is None:
        return []
    usage_lookup = {}
    recency_lookup = {}
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
    results = []
    for s, r, o, c in getattr(_kg, "triples", []):
        s_txt = str(s); r_txt = str(r); o_txt = str(o)
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
            "triple": [s_txt, r_txt, o_txt], "confidence": round(float(c), 4),
            "score": round(score, 4),
            "ranking": {"confidence": round(float(c), 4), "recency": round(recency, 4), "frequency": round(frequency, 4), "source_quality": round(sq, 4)},
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
                "confidence": 0.99, "score": 1.05,
                "ranking": {"confidence": 0.99, "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
                "provenance": {"source_type": "arithmetic_operator", "source_document": "runtime_arithmetic", "source_text": query, "space": "arithmetic", "solution_trace": arithmetic.steps if arithmetic is not None else []},
            })
    if arithmetic_key is not None and arithmetic_result is None and arithmetic_missing:
        flags = detect_decimal_or_fraction(arithmetic.expression if arithmetic is not None else query)
        results.append({
            "triple": [arithmetic_key, "requires_learning", ",".join(arithmetic_missing)],
            "confidence": 1.0, "score": 1.01,
            "ranking": {"confidence": 1.0, "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
            "provenance": {"source_type": "numeracy_gate", "source_document": "runtime_numeracy_guard", "source_text": query, "space": "arithmetic", "missing_tokens": arithmetic_missing, "has_decimal": flags["has_decimal"], "has_fraction": flags["has_fraction"]},
        })
    if calculus is not None:
        results.append({
            "triple": [calculus.expression, calculus.kind, calculus.result],
            "confidence": 0.99, "score": 1.02,
            "ranking": {"confidence": 0.99, "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
            "provenance": {"source_type": "symbolic_calculus", "source_document": "runtime_calculus", "source_text": query, "space": "calculus", "variable": calculus.variable, "solution_trace": calculus.steps},
        })
    if def_integral is not None:
        results.append({
            "triple": [def_integral.expression, "definite_integral", def_integral.result],
            "confidence": 0.99, "score": 1.03,
            "ranking": {"confidence": 0.99, "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
            "provenance": {"source_type": "symbolic_calculus", "source_document": "runtime_definite_integral", "source_text": query, "space": "calculus", "variable": def_integral.variable, "lower": def_integral.lower, "upper": def_integral.upper, "antiderivative": def_integral.antiderivative, "solution_trace": def_integral.steps},
        })
    if adv_deriv is not None:
        results.append({
            "triple": [adv_deriv.expression, adv_deriv.kind, adv_deriv.result],
            "confidence": 0.99, "score": 1.02,
            "ranking": {"confidence": 0.99, "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
            "provenance": {"source_type": "symbolic_calculus", "source_document": "runtime_derivative", "source_text": query, "space": "calculus", "variable": adv_deriv.variable, "solution_trace": adv_deriv.steps},
        })
    if algebra is not None:
        results.append({
            "triple": [algebra.expression, algebra.kind, algebra.result],
            "confidence": 0.99, "score": 1.04,
            "ranking": {"confidence": 0.99, "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
            "provenance": {"source_type": "symbolic_algebra", "source_document": "runtime_algebra", "source_text": query, "space": "arithmetic", "solution_trace": algebra.steps},
        })
    if equation is not None:
        sol_str = ", ".join(_format_number(s) for s in equation.solutions) if equation.solutions else "no real solutions"
        results.append({
            "triple": [equation.equation, "solved", sol_str],
            "confidence": 0.99, "score": 1.04,
            "ranking": {"confidence": 0.99, "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
            "provenance": {"source_type": "symbolic_algebra", "source_document": "runtime_equation", "source_text": query, "space": "arithmetic", "variable": equation.variable, "solutions": equation.solutions, "solution_trace": equation.steps},
        })
    if sequence is not None:
        seq_dict = sequence.to_dict()
        seq_numbers_str = ", ".join(_format_number(n) for n in seq_nums) if seq_nums else query
        results.append({
            "triple": [seq_numbers_str, "sequence_next", seq_dict["next"]],
            "confidence": round(sequence.confidence, 4), "score": 1.03,
            "ranking": {"confidence": round(sequence.confidence, 4), "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
            "provenance": {"source_type": "symbolic_sequence", "source_document": "runtime_sequence", "source_text": query, "space": "arithmetic", "pattern_type": seq_dict["type"], "next_value": seq_dict["next"], "formula": seq_dict["formula"], "solution_trace": seq_dict["steps"]},
        })
    if explicit_log_intent and log_missing:
        results.append({
            "triple": [query, "requires_learning", ",".join(log_missing)],
            "confidence": 1.0, "score": 1.0,
            "ranking": {"confidence": 1.0, "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
            "provenance": {"source_type": "curriculum_gate", "source_document": "runtime_curriculum_guard", "source_text": query, "space": "calculus", "missing_tokens": log_missing},
        })
    if calculus is None and calculus_missing:
        results.append({
            "triple": [query, "requires_learning", ",".join(calculus_missing)],
            "confidence": 1.0, "score": 1.0,
            "ranking": {"confidence": 1.0, "recency": 1.0, "frequency": 1.0, "source_quality": 1.0},
            "provenance": {"source_type": "curriculum_gate", "source_document": "runtime_curriculum_guard", "source_text": query, "space": "calculus", "missing_tokens": calculus_missing},
        })
    results.sort(key=lambda item: (-item["score"], -item["confidence"], tuple(item["triple"])))
    return results[:limit]

def _get_relations_builder() -> SpaceRelationsBuilder:
    global _relations_builder
    if _relations_builder is None:
        _relations_builder = SpaceRelationsBuilder(kg=_kg, tms=_tms, thought_loop=_thought_loop)
    else:
        _relations_builder.kg = _kg
        _relations_builder.tms = _tms
        _relations_builder.thought_loop = _thought_loop
    return _relations_builder

def _get_loader() -> _DataLoader:
    global _data_loader
    if _data_loader is None:
        _data_loader = _DataLoader(tms=_tms, kg=_kg, parser=_parser)
    return _data_loader

def _load_seed_from_texts() -> int:
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
                            "source_type": "text_seed", "source_document": txt_path.name, "stage": "validated",
                        })
                        _kg.add(subject, relation, obj, confidence, {
                            "source_type": "text_seed", "source_document": txt_path.name,
                        })
                        total += 1
                        file_count += 1
            print(f"[SEED] Loaded {txt_path.name}: {file_count} triples")
        except Exception as e:
            print(f"[SEED] Failed to load {txt_path.name}: {e}")
    return total

def _load_arithmetic_examples_from_seed() -> list[tuple[str, str]]:
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
    config_path = Path(__file__).resolve().parent.parent / "config" / "curriculum_phases.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            return data.get("phases", CURRICULUM_PHASES)
        except Exception:
            pass
    return list(CURRICULUM_PHASES)

def _load_seed_knowledge() -> dict:
    from core.data_loader import _DOMAIN_SEED_FACTS, _DOMAIN_SEED_TRANSITIONS
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
    seed_result = None
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
    return {"before": before, "after": after, "archives_removed": archives_removed, "seed_loaded": seed_result if mode in ("hard", "full") else None}


# ── FastAPI application ------------------------------------------------------

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from cognition.thought_loop import ThoughtLoop
import random
import threading
import time


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _thought_loop
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

    try:
        _jepa.load(JEPA_WEIGHTS_FILE)
        print(f"[OK] JEPA weights restored from {JEPA_WEIGHTS_FILE} ({_jepa._trained_samples} samples)")
    except FileNotFoundError:
        jepa_updates = _train_jepa_from_qtable(epochs=JEPA_WARMUP_EPOCHS)
        print(f"[OK] JEPA offline training complete ({jepa_updates} samples, trained={_jepa.is_trained})")

    try:
        _curriculum.load(CURRICULUM_STATE_FILE)
        print(f"[OK] Curriculum state restored from {CURRICULUM_STATE_FILE} (stage={_curriculum.current_stage} {_curriculum.stage_label})")
    except FileNotFoundError:
        print("[OK] Curriculum state initialised at stage 0 (LITERACY)")

    _thought_loop = ThoughtLoop(main, _jepa, simulate_outcome, main.Q, ACTIONS)
    _thought_loop.embedding.kg = _kg

    def loop():
        states = [("flood",), ("damage",), ("collapse",), ("crisis",), ("flood", "damage"), ("damage", "collapse")]
        while True:
            sampled_state = random.choice(states)
            scores, action, diagnostics = hybrid_decision(sampled_state, return_diagnostics=True)
            _record_loop_artifacts(sampled_state, action, scores, thought_trace=diagnostics.get("thought_trace"))
            time.sleep(2.0)

    threading.Thread(target=loop, daemon=True).start()
    yield

    _graph_store.save(_kg)
    print("[OK] Knowledge graph saved")
    _jepa.save(JEPA_WEIGHTS_FILE)
    print(f"[OK] JEPA weights saved to {JEPA_WEIGHTS_FILE}")
    _curriculum.save(CURRICULUM_STATE_FILE)
    print(f"[OK] Curriculum state saved to {CURRICULUM_STATE_FILE}")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.endpoints.root import router as root_router
from api.endpoints.think import router as think_router
from api.endpoints.semantic import router as semantic_router
from api.endpoints.curriculum import router as curriculum_router
from api.endpoints.primary import router as primary_router
from api.endpoints.economy import router as economy_router
from api.endpoints.inductive import router as inductive_router
from api.endpoints.ingest import router as ingest_router
from api.endpoints.memory import router as memory_router
from api.endpoints.seed import router as seed_router

app.include_router(root_router)
app.include_router(think_router)
app.include_router(semantic_router)
app.include_router(curriculum_router)
app.include_router(primary_router)
app.include_router(economy_router)
app.include_router(inductive_router)
app.include_router(ingest_router)
app.include_router(memory_router)
app.include_router(seed_router)
