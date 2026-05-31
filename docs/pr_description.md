# PR Title
Add staged PDF ingestion, cross-space recall graph, operational controls, and dashboard review UX

## Summary
This PR completes the end-to-end document learning flow:
- PDF upload and extraction with provenance metadata.
- Candidate staging, promotion/rejection lifecycle, and recall.
- Cross-space relation graph output across risk/goal/memory/attention/self/semantic spaces.
- Recall/search APIs with ranking by confidence, recency, frequency, and source quality.
- Dashboard Knowledge Recall panel with space filters and candidate review actions.
- Operational controls: feature flags, ingest rate limiting, and masked ingest event logging.

## Commit Breakdown
1. feat(ingest): add PDF extraction and provenance loader
2. feat(api): add recall graph endpoints and ingest controls
3. feat(dashboard): add knowledge recall and review workflow UI

## API Additions
- POST /ingest/pdf
- POST /ingest/pdfs
- GET /semantic/relations
- GET /semantic/search
- GET /semantic/recall

## Security and Ops
- Feature flags:
  - ENABLE_PDF_INGEST
  - ENABLE_SPACE_RELATIONS
- Ingest rate limiting:
  - INGEST_RATE_LIMIT_MAX_REQUESTS
  - INGEST_RATE_LIMIT_WINDOW_SECONDS
- Ingest event logs with masked sensitive values.

## Validation
Unit/API/E2E/Perf tests were executed:
- /usr/bin/python3 -m unittest tests/test_api.py tests/test_data_loader.py tests/test_pdf_ingestion.py tests/test_space_relations.py tests/test_performance.py
- Result: all tests passed.

## Demo Artifacts
A reproducible demo run is recorded in:
- artifacts/pdf_demo/simple_demo.pdf
- artifacts/pdf_demo/01_ingest_pdf.json
- artifacts/pdf_demo/02_candidates.json
- artifacts/pdf_demo/03_promote.json
- artifacts/pdf_demo/04_recall.json
- artifacts/pdf_demo/05_summary.json
- artifacts/pdf_demo/process_log.md

Script used:
- scripts/pdf_e2e_demo.py
