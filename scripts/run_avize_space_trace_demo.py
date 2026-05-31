import json
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_mock_main = MagicMock()
_mock_main.Q = defaultdict(float)
_mock_main.policy_counter = {}
_mock_main.get_key = lambda state: tuple(sorted(state)) if not isinstance(state, str) else state
sys.modules.setdefault("main", _mock_main)

import api  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from cognition.thought_loop import ThoughtLoop  # noqa: E402
from config import ACTIONS  # noqa: E402
from core.knowledge_graph import KnowledgeGraph  # noqa: E402
from core.parser import SemanticParser  # noqa: E402
from core.tms import LiteTMS  # noqa: E402
from learning.jepa import JEPAModel  # noqa: E402
from memory.concept_space_embeddings import ConceptSpaceEmbeddings  # noqa: E402


def make_client() -> TestClient:
    api._kg = KnowledgeGraph()
    api._tms = LiteTMS()
    api._parser = SemanticParser(enable_spacy_dep=True)
    api._jepa = JEPAModel()
    api._ingest_rate_bucket.clear()
    api._loop_artifacts.clear()
    api._concept_space_embeddings = ConceptSpaceEmbeddings(ROOT / "artifacts" / "avize_space_trace_demo" / "concept_space_embeddings.json")

    def _fake_simulate(state, action):
        s = set(state) if not isinstance(state, str) else set()
        reward = 4.0 if action == "barrier" else 0.0
        return reward, tuple(sorted(s))

    api._thought_loop = ThoughtLoop(_mock_main, api._jepa, _fake_simulate, _mock_main.Q, ACTIONS)
    api._data_loader = None
    return TestClient(api.app, raise_server_exceptions=False)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> None:
    out = ROOT / "artifacts" / "avize_space_trace_demo"
    out.mkdir(parents=True, exist_ok=True)

    client = make_client()

    seed_payload = {
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
                "subject": "ampul",
                "relation": "emits",
                "object": "isik",
                "confidence": 0.93,
                "teaching_kind": "rule",
                "space_hint": "semantic",
            },
            {
                "subject": "avize",
                "relation": "installed_in",
                "object": "salon",
                "confidence": 0.9,
                "teaching_kind": "rule",
                "space_hint": "memory,semantic",
            },
            {
                "subject": "science",
                "relation": "knows_concept",
                "object": "avize",
                "confidence": 0.99,
                "teaching_kind": "rule",
                "space_hint": "semantic,curriculum",
            },
            {
                "subject": "science",
                "relation": "knows_concept",
                "object": "lumen",
                "confidence": 0.55,
                "teaching_kind": "concept_seed",
                "space_hint": "semantic",
            },
        ],
        "stage": "validated",
        "source_document": "avize_demo.txt",
    }

    ingest = client.post("/ingest", json=seed_payload).json()
    trace = client.get("/semantic/concept/avize/trace").json()
    embedding = client.get("/semantic/concept/avize/embedding").json()

    write_json(out / "01_ingest_result.json", ingest)
    write_json(out / "02_avize_trace.json", trace)
    write_json(out / "03_avize_embedding.json", embedding)

    report_lines = [
        "# Avize Concept Space Trace Demo",
        "",
        "This report shows which data was pulled from which spaces and confidence values.",
        "",
        "## Space Buckets",
    ]

    for bucket in trace.get("spaces", []):
        space = bucket.get("space", "unknown")
        avg_fact = bucket.get("avg_fact_confidence", 0)
        avg_edge = bucket.get("avg_edge_confidence", 0)
        fact_count = len(bucket.get("facts", []))
        edge_count = len(bucket.get("relation_edges", []))
        report_lines.append(f"- {space}: facts={fact_count} avg_fact_conf={avg_fact} edges={edge_count} avg_edge_conf={avg_edge}")

    report_lines.extend([
        "",
        "## Sample Pulled Facts",
    ])

    for fact in trace.get("facts", [])[:8]:
        triple = fact.get("triple", ["", "", ""])
        conf = fact.get("confidence", 0)
        spaces = ", ".join(fact.get("spaces", []))
        report_lines.append(f"- ({triple[0]}, {triple[1]}, {triple[2]}) conf={conf} spaces=[{spaces}]")

    (out / "04_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
