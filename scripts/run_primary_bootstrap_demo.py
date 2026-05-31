import json
import sys
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

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


def write_pdf(path: Path, title: str, lines: list[str]) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, 800, title)
    c.setFont("Helvetica", 11)
    y = 772
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
        if y < 60:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = 800
    c.save()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _lesson_lines(domain: str, concepts: list[str]) -> list[str]:
    lines = [f"Domain: {domain}", "Primary-level lesson notes:"]
    for concept in concepts:
        readable = concept.replace("_", " ")
        lines.append(f"- {readable}: short definition and one daily-life example.")
    lines.append("Review question: explain one relation between these concepts.")
    return lines


def main() -> None:
    out = ROOT / "artifacts" / "primary_bootstrap_demo"
    text_dir = out / "texts"
    pdf_dir = out / "pdfs"
    out.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    client = make_client()
    before = client.get("/learn/primary/readiness").json()
    plan = client.get("/learn/primary/plan", params={"weeks": 6}).json()

    write_json(out / "01_readiness_before.json", before)
    write_json(out / "02_weekly_plan.json", plan)

    # Keep the demo deterministic: teach at most first 4 weeks from generated plan.
    taught_records = []
    for week_entry in (plan.get("weekly_plan") or [])[:4]:
        week = int(week_entry.get("week", 0))
        domain = str(week_entry.get("domain", "general"))
        concepts = [str(c) for c in (week_entry.get("focus_concepts") or [])]
        if not concepts:
            continue

        lesson_lines = _lesson_lines(domain, concepts)
        text_path = text_dir / f"week_{week:02d}_{domain}.txt"
        text_path.write_text("\n".join(lesson_lines) + "\n", encoding="utf-8")

        pdf_path = pdf_dir / f"week_{week:02d}_{domain}.pdf"
        write_pdf(pdf_path, f"Week {week} - {domain}", lesson_lines)

        facts = [
            {
                "subject": domain,
                "relation": "knows_concept",
                "object": concept,
                "confidence": 1.0,
            }
            for concept in concepts
        ]
        ingest_facts = client.post(
            "/ingest",
            json={
                "facts": facts,
                "source_document": text_path.name,
                "stage": "validated",
            },
        )
        ingest_text = client.post(
            "/ingest/documents",
            json={
                "content": "\n".join(lesson_lines),
                "source_document": text_path.name,
                "stage": "validated",
                "metadata": {"domain": domain, "week": week},
            },
        )
        ingest_pdf = client.post(
            "/ingest/pdf",
            data={
                "stage": "validated",
                "source_document": pdf_path.name,
                "metadata": json.dumps({"domain": domain, "week": week, "auto_bootstrap": True}),
            },
            files={"file": (pdf_path.name, BytesIO(pdf_path.read_bytes()), "application/pdf")},
        )

        record = {
            "week": week,
            "domain": domain,
            "concepts": concepts,
            "text_file": str(text_path.relative_to(ROOT)),
            "pdf_file": str(pdf_path.relative_to(ROOT)),
            "ingest_facts_status": ingest_facts.status_code,
            "ingest_text_status": ingest_text.status_code,
            "ingest_pdf_status": ingest_pdf.status_code,
        }
        taught_records.append(record)
        write_json(out / f"week_{week:02d}_{domain}.json", record)

    after = client.get("/learn/primary/readiness").json()
    write_json(out / "90_readiness_after.json", after)

    summary = {
        "before_overall": before.get("overall_coverage", 0.0),
        "after_overall": after.get("overall_coverage", 0.0),
        "delta": round(float(after.get("overall_coverage", 0.0)) - float(before.get("overall_coverage", 0.0)), 3),
        "lessons_generated": len(taught_records),
        "records": taught_records,
    }
    write_json(out / "99_summary.json", summary)

    report = [
        "# Primary Bootstrap Demo",
        "",
        "This demo creates lesson text/PDF files from readiness gaps and teaches them automatically.",
        "",
        f"Before coverage: {summary['before_overall']}",
        f"After coverage: {summary['after_overall']}",
        f"Delta: {summary['delta']}",
        f"Lessons generated: {summary['lessons_generated']}",
    ]
    (out / "100_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()