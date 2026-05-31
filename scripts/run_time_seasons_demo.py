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
from core.space_relations import DEFAULT_SPACES  # noqa: E402
from core.tms import LiteTMS  # noqa: E402
from learning.jepa import JEPAModel  # noqa: E402


CONCEPTS = [
    "gun",
    "hafta",
    "ay",
    "yil",
    "mevsimler",
    "saat",
    "dakika",
    "saniye",
    "takvim",
    "ayin_gunleri",
    "ay_evreleri",
    "yeniay",
    "ilkdordun",
    "dolunay",
    "sondordun",
    "gunes_tutulmasi",
    "ay_tutulmasi",
    "dunya_donusu",
    "dunya_gunes_cevresinde_dolanma",
    "eksen_egikligi",
    "aci",
]

EXPOSURE_CONCEPTS = list(CONCEPTS)
REINFORCEMENT_CONCEPTS = [
    "gun",
    "hafta",
    "ay",
    "yil",
    "mevsimler",
    "ay_evreleri",
    "gunes_tutulmasi",
    "ay_tutulmasi",
    "eksen_egikligi",
]


LESSON_LINES = [
    "Gun: Dunya kendi ekseni etrafinda dondugu icin gece ve gunduz olusur.",
    "Hafta: Gunler duzenli bir sirada 7 gunde toplanir.",
    "Ay: Yaklasik 30 gunluk zaman birimidir.",
    "Yil: Dunya Gunes etrafinda bir turunu yaklasik 365 gunde tamamlar.",
    "Saat: 60 dakikadan olusur.",
    "Dakika: 60 saniyeden olusur.",
    "Takvim: gunleri, haftalari, aylari ve yillari duzenler.",
    "Mevsimler: Dunya ekseninin egik olmasi ve Gunes etrafinda dolanmasi nedeniyle olusur.",
    "Aci kavrami mevsimleri anlamada kullanilir, detaylar daha sonra derinlestirilecektir.",
    "Ay evreleri: yeniay, ilkdordun, dolunay ve sondordun olarak gozukur.",
    "Gunes tutulmasi: Ay, Dunya ile Gunes arasina girdiginde olur.",
    "Ay tutulmasi: Dunya, Gunes ile Ay arasina girdiginde olur.",
    "Yaz ve kis farklari, Gunes isinlarinin gelis acisi ile ilgilidir.",
    "Ilkbahar ve sonbahar gecis mevsimleridir.",
]


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
    c.drawString(55, 800, title)
    c.setFont("Helvetica", 11)
    y = 772
    for line in lines:
        c.drawString(55, y, line)
        y -= 22
        if y < 60:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = 800
    c.save()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _kg_known_concepts() -> set[str]:
    values: set[str] = set()
    for _s, r, o, _c in getattr(api._kg, "triples", []):
        if str(r).lower() == "knows_concept":
            values.add(str(o).lower())
    return values


def _space_map_for_concept(client: TestClient, concept: str) -> dict[str, object]:
    recall = client.get(
        "/semantic/recall",
        params={
            "query": concept,
            "include_spaces": ",".join(DEFAULT_SPACES),
            "max_edges": 250,
        },
    ).json()
    graph = recall.get("relations_graph", {})
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    concept_node_ids = set()
    needle = concept.lower()
    for node in nodes:
        node_id = str(node.get("id", ""))
        label = str(node.get("label", "")).lower()
        if node_id.endswith(f":{needle}") or label == needle:
            concept_node_ids.add(node_id)

    active_spaces = set()
    for edge in edges:
        src = str(edge.get("source", ""))
        tgt = str(edge.get("target", ""))
        if src in concept_node_ids or tgt in concept_node_ids:
            active_spaces.add(str(edge.get("space", "")))

    return {
        "concept": concept,
        "spaces": sorted(s for s in active_spaces if s),
        "edge_count": int(len(edges)),
    }


def _concept_confidence(concept: str) -> float | None:
    needle = concept.lower()
    values = [
        float(c)
        for s, r, o, c in getattr(api._kg, "triples", [])
        if str(r).lower() == "knows_concept" and str(o).lower() == needle
    ]
    if not values:
        return None
    return max(values)


def main() -> None:
    out = ROOT / "artifacts" / "time_seasons_demo"
    docs = out / "docs"
    out.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)

    client = make_client()

    before = client.get("/learn/primary/readiness").json()
    before_known = _kg_known_concepts()
    write_json(out / "01_readiness_before.json", before)

    txt_path = docs / "time_and_seasons_lesson.txt"
    txt_path.write_text("\n".join(LESSON_LINES) + "\n", encoding="utf-8")

    pdf_path = docs / "time_and_seasons_lesson.pdf"
    write_pdf(pdf_path, "Time and Seasons Lesson", LESSON_LINES)

    concept_facts_exposure = [
        {
            "subject": "science",
            "relation": "knows_concept",
            "object": concept,
            "confidence": 0.55,
            "teaching_kind": "concept_seed",
        }
        for concept in EXPOSURE_CONCEPTS
    ]
    concept_facts_reinforcement = [
        {
            "subject": "science",
            "relation": "knows_concept",
            "object": concept,
            "confidence": 0.95,
            "teaching_kind": "rule",
        }
        for concept in REINFORCEMENT_CONCEPTS
    ]
    rule_facts = [
        {
            "subject": "gun",
            "relation": "caused_by",
            "object": "dunya_donusu",
            "confidence": 0.95,
            "teaching_kind": "rule",
        },
        {
            "subject": "yil",
            "relation": "caused_by",
            "object": "dunya_gunes_cevresinde_dolanma",
            "confidence": 0.95,
            "teaching_kind": "rule",
        },
        {
            "subject": "mevsimler",
            "relation": "caused_by",
            "object": "eksen_egikligi",
            "confidence": 0.95,
            "teaching_kind": "rule",
        },
        {
            "subject": "saat",
            "relation": "equals",
            "object": "60_dakika",
            "confidence": 0.95,
            "teaching_kind": "rule",
        },
        {
            "subject": "dakika",
            "relation": "equals",
            "object": "60_saniye",
            "confidence": 0.95,
            "teaching_kind": "rule",
        },
        {
            "subject": "hafta",
            "relation": "equals",
            "object": "7_gun",
            "confidence": 0.95,
            "teaching_kind": "rule",
        },
    ]

    ingest_facts_exposure = client.post(
        "/ingest",
        json={
            "facts": concept_facts_exposure + rule_facts,
            "source_document": txt_path.name,
            "stage": "validated",
        },
    )
    ingest_facts_reinforcement = client.post(
        "/ingest",
        json={
            "facts": concept_facts_reinforcement,
            "source_document": "time_and_seasons_reinforcement.txt",
            "stage": "validated",
        },
    )
    ingest_text = client.post(
        "/ingest/documents",
        json={
            "content": "\n".join(LESSON_LINES),
            "source_document": txt_path.name,
            "stage": "validated",
            "metadata": {"topic": "time_seasons", "language": "tr"},
        },
    )
    ingest_pdf = client.post(
        "/ingest/pdf",
        data={
            "stage": "validated",
            "source_document": pdf_path.name,
            "metadata": json.dumps({"topic": "time_seasons", "language": "tr", "demo": True}),
        },
        files={"file": (pdf_path.name, BytesIO(pdf_path.read_bytes()), "application/pdf")},
    )

    after = client.get("/learn/primary/readiness").json()
    after_known = _kg_known_concepts()
    write_json(out / "90_readiness_after.json", after)

    new_known = sorted(after_known - before_known)
    tracked_new_concepts = [c for c in CONCEPTS if c in new_known]
    concept_space_map = [_space_map_for_concept(client, concept) for concept in CONCEPTS]

    summary = {
        "topic": "time_and_seasons",
        "documents": {
            "text": str(txt_path.relative_to(ROOT)),
            "pdf": str(pdf_path.relative_to(ROOT)),
        },
        "ingest_status": {
            "facts_exposure": ingest_facts_exposure.status_code,
            "facts_reinforcement": ingest_facts_reinforcement.status_code,
            "text": ingest_text.status_code,
            "pdf": ingest_pdf.status_code,
        },
        "new_known_concepts": tracked_new_concepts,
        "concept_space_map": concept_space_map,
        "concept_confidence": [
            {
                "concept": concept,
                "confidence": _concept_confidence(concept),
                "learning_stage": "reinforced" if concept in REINFORCEMENT_CONCEPTS else "exposed",
                "abstraction_pending": concept not in REINFORCEMENT_CONCEPTS,
            }
            for concept in CONCEPTS
        ],
    }
    write_json(out / "99_summary.json", summary)

    report_lines = [
        "# Time and Seasons Demo",
        "",
        "Generated lesson documents were ingested and concept-space visibility was measured.",
        "",
        f"Text document: {summary['documents']['text']}",
        f"PDF document: {summary['documents']['pdf']}",
        (
            "Ingest status (facts_exposure/facts_reinforcement/text/pdf): "
            f"{ingest_facts_exposure.status_code}/{ingest_facts_reinforcement.status_code}/{ingest_text.status_code}/{ingest_pdf.status_code}"
        ),
        "",
        "## Concept -> Confidence",
    ]
    for item in summary["concept_confidence"]:
        report_lines.append(
            f"- {item['concept']}: confidence={item['confidence']} stage={item['learning_stage']}"
        )

    report_lines.extend([
        "",
        "## Concept -> Spaces",
    ])
    for item in concept_space_map:
        report_lines.append(f"- {item['concept']}: {', '.join(item['spaces']) if item['spaces'] else 'no_direct_edges'}")
    (out / "100_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()