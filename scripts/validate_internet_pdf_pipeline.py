import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import MagicMock

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Patch heavy startup dependency before importing api
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


PDF_URL = "https://arxiv.org/pdf/1706.03762.pdf"
QUERY = "attention"
PROMOTE_LIMIT = 40


def make_client() -> TestClient:
    api._kg = KnowledgeGraph()
    api._tms = LiteTMS()
    api._parser = SemanticParser(enable_spacy_dep=True)
    api._jepa = JEPAModel()
    api._ingest_rate_bucket.clear()
    api._loop_artifacts.clear()

    def _fake_simulate(state, action):
        s = set(state) if not isinstance(state, str) else set()
        reward = 4.0 if action == "barrier" else 0.0
        return reward, tuple(sorted(s))

    api._thought_loop = ThoughtLoop(_mock_main, api._jepa, _fake_simulate, _mock_main.Q, ACTIONS)
    api._data_loader = None
    return TestClient(api.app, raise_server_exceptions=False)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True))


def to_mermaid(graph: dict, max_edges: int = 80) -> str:
    lines = ["graph TD"]
    edges = graph.get("edges", [])[:max_edges]
    for idx, edge in enumerate(edges):
        src = str(edge.get("source", "src")).replace(":", "_").replace("-", "_")
        tgt = str(edge.get("target", "tgt")).replace(":", "_").replace("-", "_")
        rel = str(edge.get("relation_type", "rel")).replace("\"", "'")
        lines.append(f"  {src}{idx}[\"{edge.get('source', 'src')}\"] -->|{rel}| {tgt}{idx}[\"{edge.get('target', 'tgt')}\"]")
    return "\n".join(lines) + "\n"


def main() -> None:
    out = ROOT / "artifacts" / "internet_pdf_validation"
    out.mkdir(parents=True, exist_ok=True)

    client = make_client()
    spacy_active = bool(getattr(api._parser, "_ensure_spacy_pipeline", lambda: None)())

    t0 = time.perf_counter()
    pdf_resp = requests.get(PDF_URL, timeout=60)
    pdf_resp.raise_for_status()
    download_seconds = time.perf_counter() - t0
    pdf_bytes = pdf_resp.content

    t1 = time.perf_counter()
    ingest = client.post(
        "/ingest/pdf",
        data={"stage": "candidate", "source_document": "arxiv_1706.03762.pdf"},
        files={"file": ("arxiv_1706.03762.pdf", pdf_bytes, "application/pdf")},
    )
    ingest_seconds = time.perf_counter() - t1
    ingest_payload = ingest.json()
    write_json(out / "01_ingest_pdf.json", ingest_payload)

    candidates = client.get("/ingest/candidates")
    candidates_payload = candidates.json()
    write_json(out / "02_candidates.json", candidates_payload)

    promoted = 0
    for item in candidates_payload.get("candidates", [])[:PROMOTE_LIMIT]:
        cid = item.get("id")
        if not cid:
            continue
        r = client.post(f"/ingest/candidates/{cid}/promote")
        if r.status_code == 200:
            promoted += 1

    t2 = time.perf_counter()
    recall = client.get(
        "/semantic/recall",
        params={
            "query": QUERY,
            "include_spaces": "risk,goal,memory,attention,self,semantic",
            "max_depth": 2,
            "max_edges": 300,
        },
    )
    recall_seconds = time.perf_counter() - t2
    recall_payload = recall.json()
    write_json(out / "03_recall.json", recall_payload)

    # Trigger several cycles to inspect loop health artifacts.
    probe_states = ["flood", "damage", "collapse", "crisis", "flood,damage"]
    for st in probe_states:
        client.post("/decision", json={"state": st})

    loop_health = client.get("/loop/health", params={"limit": 50}).json()
    write_json(out / "04_loop_health.json", loop_health)

    metrics = client.get("/metrics").json()
    write_json(out / "05_metrics.json", metrics)

    relations_graph = recall_payload.get("relations_graph", {})
    (out / "06_relations_graph.mmd").write_text(to_mermaid(relations_graph))

    space_counts = Counter(edge.get("space", "unknown") for edge in relations_graph.get("edges", []))

    healthy = (
        ingest.status_code == 200
        and recall.status_code == 200
        and ingest_payload.get("candidates", 0) > 0
        and promoted > 0
        and len(recall_payload.get("facts", [])) > 0
        and loop_health.get("thought_ok", 0) > 0
        and loop_health.get("visualization_ok", 0) > 0
    )

    missing = []
    if promoted < 10:
        missing.append("Promoted candidate count is low; add confidence-based auto-promote thresholds or review batching.")
    if len(recall_payload.get("facts", [])) < 3:
        missing.append("Recall fact count is low for internet PDF; improve parser precision/coverage for academic sentence structures.")
    if space_counts.get("semantic", 0) < 8:
        if spacy_active:
            missing.append("Semantic edge count is still limited even with spaCy active; tune relation mapping and multi-clause extraction for academic texts.")
        else:
            missing.append("Semantic edge count is still limited; enable full dependency parsing (spaCy/Stanza) for academic texts.")

    summary = {
        "source_pdf_url": PDF_URL,
        "query": QUERY,
        "download_seconds": round(download_seconds, 3),
        "ingest_seconds": round(ingest_seconds, 3),
        "recall_seconds": round(recall_seconds, 3),
        "ingest_status": ingest.status_code,
        "candidate_count": int(ingest_payload.get("candidates", 0)),
        "promoted_count": promoted,
        "recall_status": recall.status_code,
        "recall_fact_count": len(recall_payload.get("facts", [])),
        "recall_edge_count": len(relations_graph.get("edges", [])),
        "loop_thought_ok": int(loop_health.get("thought_ok", 0)),
        "loop_visualization_ok": int(loop_health.get("visualization_ok", 0)),
        "metrics_loop_thought_ok_20": metrics.get("loop_thought_ok_20"),
        "metrics_loop_visual_ok_20": metrics.get("loop_visual_ok_20"),
        "space_edge_distribution": dict(space_counts),
        "spacy_dependency_active": spacy_active,
        "pipeline_healthy": healthy,
        "identified_gaps": missing,
    }
    write_json(out / "07_summary.json", summary)

    report_lines = [
        "# Internet PDF Validation Report",
        "",
        f"Source PDF: {PDF_URL}",
        f"Query: {QUERY}",
        "",
        "## Pipeline Result",
        f"- Healthy: {healthy}",
        f"- Ingest status: {ingest.status_code}",
        f"- Candidates: {ingest_payload.get('candidates', 0)}",
        f"- Promoted: {promoted}",
        f"- Recall status: {recall.status_code}",
        f"- Recall facts: {len(recall_payload.get('facts', []))}",
        f"- Recall edges: {len(relations_graph.get('edges', []))}",
        "",
        "## Loop Health",
        f"- thought_ok: {loop_health.get('thought_ok', 0)}",
        f"- visualization_ok: {loop_health.get('visualization_ok', 0)}",
        "",
        "## Identified Gaps",
    ]
    if missing:
        report_lines.extend([f"- {item}" for item in missing])
    else:
        report_lines.append("- No critical gap detected in this run.")

    report_lines.extend([
        "",
        "## Saved Artifacts",
        "- artifacts/internet_pdf_validation/01_ingest_pdf.json",
        "- artifacts/internet_pdf_validation/02_candidates.json",
        "- artifacts/internet_pdf_validation/03_recall.json",
        "- artifacts/internet_pdf_validation/04_loop_health.json",
        "- artifacts/internet_pdf_validation/05_metrics.json",
        "- artifacts/internet_pdf_validation/06_relations_graph.mmd",
        "- artifacts/internet_pdf_validation/07_summary.json",
    ])

    (out / "08_report.md").write_text("\n".join(report_lines) + "\n")


if __name__ == "__main__":
    main()
