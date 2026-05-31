from __future__ import annotations

"""Build unified cross-space relation graphs for recall/explain workflows."""

from collections import deque
import ast
import re
import time
from typing import Any

from cognition.emotion_space import EmotionSpace
from cognition.intent import IntentEngine
from cognition.multispace_embedding import MultiSpaceEmbedding
from core.symbolic_math import compute_arithmetic, compute_calculus


DEFAULT_SPACES = ("risk", "goal", "memory", "attention", "self", "semantic", "arithmetic", "calculus", "curriculum", "emotion")


def _clamp_conf(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _tokenize_text(value: str) -> set[str]:
    tokens = [t for t in re.findall(r"[a-zA-Z0-9_]+", (value or "").lower()) if t]
    expanded = set(tokens)
    for token in tokens:
        if "_" in token:
            expanded.update(part for part in token.split("_") if part)
    return expanded


def _coerce_state(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, set):
        return {str(v).lower() for v in value}
    if isinstance(value, (list, tuple)):
        return {str(v).lower() for v in value if str(v).strip()}
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return set()
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, str):
                return {parsed.lower()}
            if isinstance(parsed, (set, list, tuple)):
                return {str(v).lower() for v in parsed if str(v).strip()}
        except Exception:
            pass
        return _tokenize_text(text)
    return {str(value).lower()}


class SpaceRelationsBuilder:
    def __init__(self, kg=None, tms=None, thought_loop=None):
        self.kg = kg
        self.tms = tms
        self.thought_loop = thought_loop

    def build(
        self,
        *,
        query: str | None = None,
        state: Any = None,
        include_spaces: list[str] | None = None,
        max_depth: int = 2,
        max_edges: int = 300,
    ) -> dict:
        spaces = tuple(include_spaces or DEFAULT_SPACES)
        state_tokens = _coerce_state(state)
        query_tokens = _tokenize_text(query or "")
        anchors = set(state_tokens) | set(query_tokens)

        if not anchors and self.kg is not None:
            # Fallback anchor for empty queries: first known entity.
            for s, _r, o, _c in getattr(self.kg, "triples", []):
                anchors.update({str(s).lower(), str(o).lower()})
                break

        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        def add_node(node_id: str, node_type: str, label: str):
            if node_id not in nodes:
                nodes[node_id] = {"id": node_id, "type": node_type, "label": label}

        def add_edge(edge: dict):
            if len(edges) >= max_edges:
                return
            edges.append(edge)

        for space_name in spaces:
            add_node(f"space:{space_name}", "space", space_name)

        for token in sorted(anchors):
            add_node(f"entity:{token}", "entity", token)
            add_node(f"state:{token}", "state", token)

        if "semantic" in spaces:
            self._add_semantic_edges(anchors, max_depth, add_node, add_edge)

        if "memory" in spaces:
            self._add_memory_edges(state_tokens or anchors, add_node, add_edge)

        if "goal" in spaces:
            self._add_goal_edges(state_tokens or anchors, add_node, add_edge)

        if "risk" in spaces:
            self._add_risk_edges(state_tokens or anchors, add_node, add_edge)

        if "attention" in spaces or "self" in spaces:
            self._add_embedding_edges(state_tokens or anchors, spaces, add_node, add_edge)

        if "arithmetic" in spaces:
            self._add_arithmetic_edges(query, state_tokens or anchors, add_node, add_edge)

        if "calculus" in spaces:
            self._add_calculus_edges(query, add_node, add_edge)

        if "curriculum" in spaces:
            self._add_curriculum_edges(add_node, add_edge)

        if "emotion" in spaces:
            self._add_emotion_edges(state_tokens or anchors, add_node, add_edge)

        return {
            "query": query,
            "state": sorted(state_tokens) if state_tokens else None,
            "spaces": list(spaces),
            "nodes": list(nodes.values()),
            "edges": edges[:max_edges],
            "meta": {
                "max_depth": int(max_depth),
                "max_edges": int(max_edges),
                "generated_at": float(time.time()),
            },
        }

    def _add_semantic_edges(self, anchors: set[str], max_depth: int, add_node, add_edge):
        triples = list(getattr(self.kg, "triples", [])) if self.kg is not None else []
        if not triples:
            return

        belief_status: dict[tuple[str, str, str], str] = {}
        if self.tms is not None:
            for belief in getattr(self.tms, "beliefs", []):
                triple = belief.get("triple", ())
                if len(triple) >= 3:
                    belief_status[(str(triple[0]), str(triple[1]), str(triple[2]))] = belief.get("review_status", "approved")

        frontier = set(anchors)
        visited_entities = set(anchors)
        depth = 0

        while depth < max_depth and frontier:
            next_frontier = set()
            for s, r, o, c in triples:
                s_s = str(s).lower()
                o_s = str(o).lower()
                if s_s not in frontier and o_s not in frontier:
                    continue

                add_node(f"entity:{s_s}", "entity", s_s)
                add_node(f"entity:{o_s}", "entity", o_s)

                provenance = {}
                if self.kg is not None and hasattr(self.kg, "get_metadata"):
                    provenance = dict(self.kg.get_metadata(s, r, o) or {})
                review_status = belief_status.get((str(s), str(r), str(o)))
                if review_status:
                    provenance.setdefault("review_status", review_status)

                add_edge({
                    "source": f"entity:{s_s}",
                    "target": f"entity:{o_s}",
                    "space": "semantic",
                    "source_space": "semantic",
                    "target_space": "semantic",
                    "relation_type": str(r),
                    "confidence": _clamp_conf(float(c)),
                    "provenance": provenance,
                })

                if s_s not in visited_entities:
                    next_frontier.add(s_s)
                if o_s not in visited_entities:
                    next_frontier.add(o_s)

            visited_entities.update(next_frontier)
            frontier = next_frontier
            depth += 1

    def _add_memory_edges(self, anchor_tokens: set[str], add_node, add_edge):
        if self.thought_loop is None or getattr(self.thought_loop, "memory", None) is None:
            return

        memory = self.thought_loop.memory
        add_node("memory:working", "memory", "working_memory")
        add_node("space:memory", "space", "memory")
        add_edge({
            "source": "space:memory",
            "target": "memory:working",
            "space": "memory",
            "source_space": "memory",
            "target_space": "memory",
            "relation_type": "contains",
            "confidence": 1.0,
            "provenance": {},
        })

        working = memory.get_working_memory()
        for token in working.get("state", []):
            t = str(token).lower()
            add_node(f"state:{t}", "state", t)
            add_edge({
                "source": "memory:working",
                "target": f"state:{t}",
                "space": "memory",
                "source_space": "memory",
                "target_space": "state",
                "relation_type": "recalls_state",
                "confidence": 0.8,
                "provenance": {"timestamp": working.get("timestamp")},
            })

        similar_failures = memory.get_similar_failures(anchor_tokens)[:5]
        for idx, failure in enumerate(similar_failures):
            node_id = f"memory:failure:{idx}"
            add_node(node_id, "memory", f"failure_{idx}")
            add_edge({
                "source": "space:memory",
                "target": node_id,
                "space": "memory",
                "source_space": "memory",
                "target_space": "memory",
                "relation_type": "similar_failure",
                "confidence": _clamp_conf(0.5 + 0.1 * len(failure.get("overlap", []))),
                "provenance": {"overlap": failure.get("overlap", [])},
            })

    def _add_goal_edges(self, anchor_tokens: set[str], add_node, add_edge):
        state = set(anchor_tokens)
        if self.thought_loop is not None and getattr(self.thought_loop, "intent_engine", None) is not None:
            goals = self.thought_loop.intent_engine.compute_goals(state)
        else:
            goals = IntentEngine().compute_goals(state)

        for item in goals[:5]:
            goal = item["goal"]
            score = float(item["score"])
            add_node(f"goal:{goal}", "goal", goal)
            add_edge({
                "source": "space:goal",
                "target": f"goal:{goal}",
                "space": "goal",
                "source_space": "goal",
                "target_space": "goal",
                "relation_type": "prioritizes",
                "confidence": _clamp_conf(score),
                "provenance": {"reason": item.get("reason", "")},
            })
            for token in sorted(state)[:5]:
                add_node(f"state:{token}", "state", token)
                add_edge({
                    "source": f"goal:{goal}",
                    "target": f"state:{token}",
                    "space": "goal",
                    "source_space": "goal",
                    "target_space": "state",
                    "relation_type": "applies_to",
                    "confidence": _clamp_conf(score * 0.8),
                    "provenance": {},
                })

    def _add_risk_edges(self, anchor_tokens: set[str], add_node, add_edge):
        threats = ("rain", "flood", "damage", "collapse", "crisis")
        for token in sorted(anchor_tokens):
            add_node(f"state:{token}", "state", token)
            if token in threats:
                add_node(f"risk:{token}", "risk", token)
                conf = 1.0 if token in ("crisis", "collapse") else (0.7 if token in ("flood", "damage") else 0.4)
                add_edge({
                    "source": "space:risk",
                    "target": f"risk:{token}",
                    "space": "risk",
                    "source_space": "risk",
                    "target_space": "risk",
                    "relation_type": "threat_signal",
                    "confidence": conf,
                    "provenance": {},
                })
                add_edge({
                    "source": f"risk:{token}",
                    "target": f"state:{token}",
                    "space": "risk",
                    "source_space": "risk",
                    "target_space": "state",
                    "relation_type": "describes",
                    "confidence": conf,
                    "provenance": {},
                })

    def _add_embedding_edges(self, anchor_tokens: set[str], spaces: tuple[str, ...], add_node, add_edge):
        state = set(anchor_tokens)
        if self.thought_loop is not None and getattr(self.thought_loop, "embedding", None) is not None:
            embedding = self.thought_loop.embedding.embed(state)
        else:
            embedding = MultiSpaceEmbedding().embed(state)

        if "attention" in spaces:
            add_node("attention:salience", "attention", "salience")
            add_node("attention:novelty", "attention", "novelty")
            add_node("attention:context_load", "attention", "context_load")
            labels = ("salience", "novelty", "context_load")
            for idx, label in enumerate(labels):
                value = float((embedding.get("attention", [0.0, 0.0, 0.0]) + [0.0, 0.0, 0.0])[idx])
                add_edge({
                    "source": "space:attention",
                    "target": f"attention:{label}",
                    "space": "attention",
                    "source_space": "attention",
                    "target_space": "attention",
                    "relation_type": "weights",
                    "confidence": _clamp_conf(value),
                    "provenance": {},
                })

        if "self" in spaces:
            add_node("self:confidence", "self", "confidence")
            add_node("self:overload", "self", "overload")
            add_node("self:surprise", "self", "surprise")
            labels = ("confidence", "overload", "surprise")
            for idx, label in enumerate(labels):
                value = float((embedding.get("self", [0.0, 0.0, 0.0]) + [0.0, 0.0, 0.0])[idx])
                add_edge({
                    "source": "space:self",
                    "target": f"self:{label}",
                    "space": "self",
                    "source_space": "self",
                    "target_space": "self",
                    "relation_type": "estimates",
                    "confidence": _clamp_conf(value),
                    "provenance": {},
                })

    def _add_arithmetic_edges(self, query: str | None, anchor_tokens: set[str], add_node, add_edge):
        info = compute_arithmetic(query or " ".join(sorted(anchor_tokens)))
        if info is None:
            return

        expr_id = f"arithmetic:{info.key}"

        add_node(expr_id, "arithmetic", info.expression)
        numbers_in_expr = sorted(set(re.findall(r"\d+(?:\.\d+)?", info.expression + " " + info.value)))
        for number in numbers_in_expr:
            add_node(f"number:{number}", "number", number)

        add_edge({
            "source": "space:arithmetic",
            "target": expr_id,
            "space": "arithmetic",
            "source_space": "arithmetic",
            "target_space": "arithmetic",
            "relation_type": "models_expression",
            "confidence": 1.0,
            "provenance": {},
        })
        expr_digits = re.findall(r"\d+(?:\.\d+)?", info.expression)
        lhs_digit = expr_digits[0] if expr_digits else ""
        rhs_digit = expr_digits[-1] if expr_digits else ""
        add_edge({
            "source": expr_id,
            "target": f"number:{lhs_digit}",
            "space": "arithmetic",
            "source_space": "arithmetic",
            "target_space": "number",
            "relation_type": "lhs",
            "confidence": 1.0,
            "provenance": {},
        })
        add_edge({
            "source": expr_id,
            "target": f"number:{rhs_digit}",
            "space": "arithmetic",
            "source_space": "arithmetic",
            "target_space": "number",
            "relation_type": "rhs",
            "confidence": 1.0,
            "provenance": {},
        })
        add_edge({
            "source": expr_id,
            "target": f"number:{info.value}",
            "space": "arithmetic",
            "source_space": "arithmetic",
            "target_space": "number",
            "relation_type": "equals",
            "confidence": 1.0,
            "provenance": {"computed": True},
        })

    def _add_calculus_edges(self, query: str | None, add_node, add_edge):
        info = compute_calculus(query or "")
        if info is None:
            return

        expr_node = f"calculus:expr:{info.expression}"
        result_node = f"calculus:result:{info.result}"
        op_node = f"calculus:{info.kind}"

        add_node(op_node, "calculus", info.kind)
        add_node(expr_node, "calculus", info.expression)
        add_node(result_node, "calculus", info.result)

        add_edge({
            "source": "space:calculus",
            "target": op_node,
            "space": "calculus",
            "source_space": "calculus",
            "target_space": "calculus",
            "relation_type": "applies_operator",
            "confidence": 1.0,
            "provenance": {},
        })
        add_edge({
            "source": op_node,
            "target": expr_node,
            "space": "calculus",
            "source_space": "calculus",
            "target_space": "calculus",
            "relation_type": "on_expression",
            "confidence": 1.0,
            "provenance": {},
        })
        add_edge({
            "source": expr_node,
            "target": result_node,
            "space": "calculus",
            "source_space": "calculus",
            "target_space": "calculus",
            "relation_type": "produces",
            "confidence": 1.0,
            "provenance": {"computed": True, "kind": info.kind},
        })

    def _add_curriculum_edges(self, add_node, add_edge):
        triples = list(getattr(self.kg, "triples", [])) if self.kg is not None else []
        if not triples:
            return

        for s, r, o, c in triples:
            s_txt = str(s).lower()
            r_txt = str(r).lower()
            o_txt = str(o).lower()
            if s_txt not in {"curriculum", "numeracy"}:
                continue
            if r_txt not in {"completed_phase", "knows_digit", "knows_symbol", "knows_concept", "knows_letter"}:
                continue

            src = f"curriculum:{s_txt}"
            tgt = f"curriculum:{r_txt}:{o_txt}"
            add_node(src, "curriculum", s_txt)
            add_node(tgt, "curriculum", o_txt)

            provenance = {}
            if self.kg is not None and hasattr(self.kg, "get_metadata"):
                provenance = dict(self.kg.get_metadata(s, r, o) or {})

            add_edge({
                "source": src,
                "target": tgt,
                "space": "curriculum",
                "source_space": "curriculum",
                "target_space": "curriculum",
                "relation_type": r_txt,
                "confidence": _clamp_conf(float(c)),
                "provenance": provenance,
            })

    def _add_emotion_edges(self, anchor_tokens: set[str], add_node, add_edge):
        state = set(anchor_tokens)
        emotion = EmotionSpace().from_state(state)
        vector = emotion.to_vector()
        labels = ("fear", "anger", "sadness", "surprise", "calm")
        add_node("space:emotion", "space", "emotion")
        for idx, label in enumerate(labels):
            value = vector[idx]
            add_node(f"emotion:{label}", "emotion", label)
            add_edge({
                "source": "space:emotion",
                "target": f"emotion:{label}",
                "space": "emotion",
                "source_space": "emotion",
                "target_space": "emotion",
                "relation_type": "expresses",
                "confidence": _clamp_conf(value),
                "provenance": {},
            })
