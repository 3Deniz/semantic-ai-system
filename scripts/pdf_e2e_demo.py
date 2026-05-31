import json
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

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


def make_client() -> TestClient:
    api._kg = KnowledgeGraph()
    api._tms = LiteTMS()
    api._parser = SemanticParser()
    api._jepa = JEPAModel()

    def _fake_simulate(state, action):
        s = set(state) if not isinstance(state, str) else set()
        reward = 4.0 if action == "barrier" else 0.0
        return reward, tuple(sorted(s))

    api._thought_loop = ThoughtLoop(
        _mock_main, api._jepa, _fake_simulate, _mock_main.Q, ACTIONS
    )
    api._data_loader = None
    api._ingest_rate_bucket.clear()
    return TestClient(api.app, raise_server_exceptions=False)


def write_sample_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 780, "Rain causes flood.")
    c.drawString(72, 760, "Flood causes damage.")
    c.drawString(72, 740, "Barrier prevents flood.")
    c.save()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True))


def main() -> None:
    out_dir = Path("artifacts/pdf_demo")
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = out_dir / "simple_demo.pdf"
    write_sample_pdf(pdf_path)

    client = make_client()

    with pdf_path.open("rb") as f:
        ingest = client.post(
            "/ingest/pdf",
            data={"stage": "candidate", "source_document": "simple_demo.pdf"},
            files={"file": ("simple_demo.pdf", f.read(), "application/pdf")},
        )

    ingest_payload = ingest.json()
    write_json(out_dir / "01_ingest_pdf.json", ingest_payload)

    candidates = client.get("/ingest/candidates")
    candidates_payload = candidates.json()
    write_json(out_dir / "02_candidates.json", candidates_payload)

    promoted_payload = {"ok": False, "reason": "no_candidate"}
    candidate_id = None
    if candidates_payload.get("candidates"):
        candidate_id = candidates_payload["candidates"][0]["id"]
        promoted = client.post(f"/ingest/candidates/{candidate_id}/promote")
        promoted_payload = promoted.json()
    write_json(out_dir / "03_promote.json", promoted_payload)

    recall = client.get(
        "/semantic/recall",
        params={
            "query": "flood",
            "include_spaces": "risk,goal,memory,attention,self,semantic",
            "max_depth": 2,
            "max_edges": 250,
        },
    )
    recall_payload = recall.json()
    write_json(out_dir / "04_recall.json", recall_payload)

    log = {
        "pdf": str(pdf_path),
        "ingest_status": ingest.status_code,
        "candidate_count": candidates_payload.get("count", 0),
        "promoted_candidate_id": candidate_id,
        "recall_status": recall.status_code,
        "recall_fact_count": len(recall_payload.get("facts", [])),
        "recall_edge_count": len(recall_payload.get("relations_graph", {}).get("edges", [])),
    }
    write_json(out_dir / "05_summary.json", log)

    process_md = "\n".join([
        "# PDF E2E Demo Run",
        "",
        "1. Sample PDF generated: artifacts/pdf_demo/simple_demo.pdf",
        "2. Ingest endpoint called: POST /ingest/pdf (stage=candidate)",
        "3. Candidate queue listed: GET /ingest/candidates",
        "4. First candidate promoted: POST /ingest/candidates/{id}/promote",
        "5. Recall called: GET /semantic/recall?query=flood",
        "",
        "## Output Files",
        "- artifacts/pdf_demo/01_ingest_pdf.json",
        "- artifacts/pdf_demo/02_candidates.json",
        "- artifacts/pdf_demo/03_promote.json",
        "- artifacts/pdf_demo/04_recall.json",
        "- artifacts/pdf_demo/05_summary.json",
        "",
        f"Summary: {json.dumps(log, ensure_ascii=True)}",
    ])
    (out_dir / "process_log.md").write_text(process_md)


if __name__ == "__main__":
    main()
