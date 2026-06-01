from fastapi import APIRouter, Query
import api.dependencies as deps
from api.models.requests import (
    AssertRequest, SemanticFeedbackRequest, MathRequest,
    IngestTextsRequest, IngestDocumentRequest, CandidateFactRequest,
    CandidateReviewRequest, IngestFactsRequest,
)
from fastapi import UploadFile, File, Form, HTTPException, status
import json

router = APIRouter(tags=["semantic"])


@router.post("/semantic/assert")
def semantic_assert(req: AssertRequest):
    try:
        triple = (req.subject, req.relation, req.obj)
        if deps._tms.resolve_conflict(triple, req.confidence):
            deps._tms.add_belief(triple, req.confidence)
            deps._kg.add(req.subject, req.relation, req.obj, req.confidence)
        return {"ok": True, "triple": triple}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/semantic/beliefs")
def semantic_beliefs():
    try:
        beliefs = deps._tms.get_valid_triples()
        return {"beliefs": [{"triple": list(t), "confidence": round(c, 4)} for t, c in beliefs], "count": len(beliefs)}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.post("/semantic/infer")
def semantic_infer():
    try:
        reasoner = deps.Reasoner(deps._kg)
        before = len(deps._kg.triples)
        new_triples = reasoner.infer()
        for (s, r, o, c) in new_triples:
            deps._kg.add(s, r, o, c)
        after = len(deps._kg.triples)
        return {"new_triples": after - before, "total": after}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.post("/semantic/feedback")
def semantic_feedback(req: SemanticFeedbackRequest):
    try:
        triple = (req.subject, req.relation, req.obj)
        deps._online_learner.apply_feedback(triple, req.feedback)
        return {"ok": True}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/semantic/concepts")
def semantic_concepts():
    try:
        concepts = deps._concept_learner.learn()
        return {"concepts": concepts}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/semantic/abstractions")
def semantic_abstractions():
    try:
        concepts = deps._concept_learner.learn()
        abstract_patterns = [c for c in concepts if c.get("abstraction_level", 0) >= 0.6]
        rules = deps._rule_learner.learn_rules()
        abstract_rules = [r for r in rules if r.get("abstraction", 0) >= 0.5]
        return {
            "abstract_patterns": abstract_patterns,
            "abstract_rules": [
                {"if": list(r["if"]), "then": list(r["then"]), "weight": round(r["weight"], 4),
                 "abstraction": round(r.get("abstraction", 0), 4),
                 "context": sorted(r.get("context", set())), "usage": r.get("usage", 0)}
                for r in abstract_rules
            ],
            "concept_count": len(concepts), "rule_count": len(rules),
        }
    except Exception:
        deps.logger.exception("Abstractions request failed")
        return {"error": "Internal server error"}


@router.get("/semantic/search")
def semantic_search(query: str = Query(..., min_length=1, max_length=500), limit: int = Query(default=50, ge=1, le=200)):
    try:
        policy = deps._query_answer_policy(query)
        if not bool(policy.get("should_answer", False)):
            return {"query": query, "count": 0, "facts": [], "policy": policy}
        facts = deps._search_semantic_facts(query=query, limit=limit)
        return {"query": query, "count": len(facts), "facts": facts, "policy": policy}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/semantic/recall")
def semantic_recall(
    query: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(default=30, ge=1, le=200),
    include_spaces: str = Query(default=",".join(deps.DEFAULT_SPACES)),
    max_depth: int = Query(default=2, ge=1, le=4),
    max_edges: int = Query(default=300, ge=50, le=1000),
    expand_with_facts: bool = Query(default=True),
):
    try:
        deps._require_feature(deps.ENABLE_SPACE_RELATIONS, "space_relations")
        requested_spaces = deps._resolve_relation_spaces(query, include_spaces)
        policy = deps._query_answer_policy(query)
        if not bool(policy.get("should_answer", False)):
            return {
                "query": query, "facts": [], "count": 0,
                "relations_graph": {"spaces": requested_spaces, "nodes": [], "edges": []},
                "trace": None, "policy": policy,
            }
        facts = deps._search_semantic_facts(query=query, limit=limit)
        expanded_state = None
        if expand_with_facts and facts:
            entities = []
            for fact in facts[:min(15, len(facts))]:
                triple = fact.get("triple", [])
                if len(triple) >= 3:
                    entities.append(str(triple[0]).lower())
                    entities.append(str(triple[2]).lower())
            expanded_state = sorted({e for e in entities if e})
        relations_graph = deps._get_relations_builder().build(
            query=query, state=expanded_state,
            include_spaces=requested_spaces, max_depth=max_depth, max_edges=max_edges,
        )
        trace = None
        if deps._thought_loop is not None:
            state_tokens = set(deps._tokenize_query(query))
            if state_tokens:
                trace = deps._thought_loop.think(state_tokens)
        return {"query": query, "facts": facts, "count": len(facts), "relations_graph": relations_graph, "trace": trace, "policy": policy}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/semantic/relations")
def semantic_relations(
    query: str | None = Query(default=None, max_length=500),
    state: str | None = Query(default=None, max_length=500),
    include_spaces: str = Query(default=",".join(deps.DEFAULT_SPACES)),
    max_depth: int = Query(default=2, ge=1, le=4),
    max_edges: int = Query(default=300, ge=50, le=1000),
):
    try:
        deps._require_feature(deps.ENABLE_SPACE_RELATIONS, "space_relations")
        if not query and not state:
            raise HTTPException(status_code=400, detail="Either query or state must be provided.")
        requested_spaces = [s.strip() for s in include_spaces.split(",") if s.strip()]
        allowed_spaces = set(deps.DEFAULT_SPACES)
        requested_spaces = [s for s in requested_spaces if s in allowed_spaces]
        if not requested_spaces:
            requested_spaces = list(deps.DEFAULT_SPACES)
        builder = deps._get_relations_builder()
        return builder.build(query=query, state=state, include_spaces=requested_spaces, max_depth=max_depth, max_edges=max_edges)
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/semantic/concept/{concept}/embedding")
def semantic_concept_embedding(concept: str):
    try:
        concept = str(concept).strip().lower()
        if not concept:
            raise HTTPException(status_code=400, detail="concept is required")
        return deps._concept_space_embeddings.get_concept(concept)
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/semantic/concept/{concept}/trace")
def semantic_concept_trace(concept: str, max_depth: int = Query(default=3, ge=1, le=4), max_edges: int = Query(default=250, ge=50, le=1000)):
    try:
        concept = str(concept).strip().lower()
        if not concept:
            raise HTTPException(status_code=400, detail="concept is required")
        return deps._build_concept_trace(concept, max_depth=max_depth, max_edges=max_edges)
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}
