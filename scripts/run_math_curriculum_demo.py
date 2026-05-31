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
from core.numeracy import CURRICULUM_PHASES  # noqa: E402


LESSONS = {
    "letters": [
        "a b c d e f g h i j",
        "k l m n o p q r s t",
        "u v w x y z",
    ],
    "digits": [
        "0 1 2 3 4 5 6 7 8 9",
        "Numbers represent quantities.",
    ],
    "operations": [
        "Addition uses the plus sign.",
        "Subtraction uses the minus sign.",
        "Multiplication uses the times sign.",
        "Division uses the slash sign.",
    ],
    "real_numbers": [
        "Decimals use the dot symbol, like 1.5.",
        "Fractions use the slash symbol, like 3/4.",
        "Real numbers include integers, decimals, and fractions.",
    ],
    "calculus": [
        "A derivative measures rate of change.",
        "An integral measures accumulation.",
        "Functions can be differentiated and integrated.",
    ],
    "logarithms": [
        "A logarithm is the inverse of exponentiation.",
        "ln means natural logarithm.",
        "Change of base connects different logarithm bases.",
    ],
}


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
    c.drawString(60, 800, title)
    c.setFont("Helvetica", 12)
    y = 770
    for line in lines:
        c.drawString(60, y, line)
        y -= 24
    c.save()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True))


def main() -> None:
    out = ROOT / "artifacts" / "math_curriculum_demo"
    out.mkdir(parents=True, exist_ok=True)
    pdf_dir = out / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    client = make_client()

    before_math = client.get("/semantic/search", params={"query": "44+17", "limit": 1}).json()
    before_calc = client.get("/semantic/search", params={"query": "d/dx x^2", "limit": 1}).json()
    write_json(out / "01_before_math.json", before_math)
    write_json(out / "02_before_calculus.json", before_calc)

    phase_results = []
    for idx, phase in enumerate(CURRICULUM_PHASES, start=1):
        pdf_path = pdf_dir / f"{idx:02d}_{phase}.pdf"
        write_pdf(pdf_path, f"Curriculum Phase: {phase}", LESSONS[phase])

        teach = client.post(
            "/ingest/pdf",
            data={
                "stage": "validated",
                "source_document": pdf_path.name,
                "metadata": json.dumps({
                    "curriculum_phase": phase,
                    "teach_curriculum": True,
                    "curriculum_demo": True,
                }),
            },
            files={"file": (pdf_path.name, BytesIO(pdf_path.read_bytes()), "application/pdf")},
        )
        status = client.get("/learn/curriculum/status")
        phase_payload = {
            "phase": phase,
            "pdf": str(pdf_path.relative_to(ROOT)),
            "teach_status": teach.status_code,
            "teach_payload": teach.json(),
            "status_payload": status.json(),
        }
        phase_results.append(phase_payload)
        write_json(out / f"phase_{idx:02d}_{phase}.json", phase_payload)

    after_math = client.get("/semantic/search", params={"query": "44+17", "limit": 1}).json()
    after_calc = client.get("/semantic/search", params={"query": "d/dx x^2", "limit": 1}).json()
    final_status = client.get("/learn/curriculum/status").json()

    write_json(out / "10_after_math.json", after_math)
    write_json(out / "11_after_calculus.json", after_calc)
    write_json(out / "12_curriculum_status.json", final_status)

    summary = {
        "before_math_top": (before_math.get("facts") or [{}])[0].get("triple"),
        "before_calculus_top": (before_calc.get("facts") or [{}])[0].get("triple"),
        "after_math_top": (after_math.get("facts") or [{}])[0].get("triple"),
        "after_calculus_top": (after_calc.get("facts") or [{}])[0].get("triple"),
        "completed_phases": final_status.get("curriculum", {}).get("completed", []),
        "phase_count": len(phase_results),
    }
    write_json(out / "13_summary.json", summary)

    report = "\n".join([
        "# Math Curriculum Demo",
        "",
        "This demo creates curriculum PDFs and teaches them phase by phase.",
        "",
        f"Before arithmetic: {summary['before_math_top']}",
        f"Before calculus: {summary['before_calculus_top']}",
        f"After arithmetic: {summary['after_math_top']}",
        f"After calculus: {summary['after_calculus_top']}",
        f"Completed phases: {summary['completed_phases']}",
    ])
    (out / "14_report.md").write_text(report + "\n")


if __name__ == "__main__":
    main()
