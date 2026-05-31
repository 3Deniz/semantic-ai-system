# PDF E2E Demo Run

1. Sample PDF generated: artifacts/pdf_demo/simple_demo.pdf
2. Ingest endpoint called: POST /ingest/pdf (stage=candidate)
3. Candidate queue listed: GET /ingest/candidates
4. First candidate promoted: POST /ingest/candidates/{id}/promote
5. Recall called: GET /semantic/recall?query=flood

## Output Files
- artifacts/pdf_demo/01_ingest_pdf.json
- artifacts/pdf_demo/02_candidates.json
- artifacts/pdf_demo/03_promote.json
- artifacts/pdf_demo/04_recall.json
- artifacts/pdf_demo/05_summary.json

Summary: {"pdf": "artifacts/pdf_demo/simple_demo.pdf", "ingest_status": 200, "candidate_count": 3, "promoted_candidate_id": "ca9956de-644e-4b5c-8b74-421d47b4739d", "recall_status": 200, "recall_fact_count": 1, "recall_edge_count": 19}