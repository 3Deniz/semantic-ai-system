from fastapi import APIRouter, Query, Security, HTTPException, status, UploadFile, File, Form
import api.dependencies as deps
from api.models.requests import (
    IngestTextsRequest, IngestDocumentRequest, CandidateFactRequest,
    CandidateReviewRequest, IngestFactsRequest,
)

router = APIRouter(tags=["ingest"])


@router.post("/ingest/texts")
def ingest_texts(req: IngestTextsRequest, _auth=Security(deps._require_ingest_key)):
    try:
        deps._check_ingest_rate_limit("ingest_texts")
        loader = deps._get_loader()
        result = loader.ingest_texts_with_context(req.texts, source_document=req.source_document, stage=req.stage)
        deps._log_ingest_event("ingest_texts", "/ingest/texts", {"source_document": req.source_document, "stage": req.stage, "texts": req.texts, "result": result})
        return result
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Ingest texts failed")
        return {"error": "Internal server error"}


@router.post("/ingest/seed")
def ingest_seed(_auth=Security(deps._require_ingest_key)):
    try:
        deps._check_ingest_rate_limit("ingest_seed")
        loader = deps._get_loader()
        result = loader.ingest_seed_knowledge()
        deps._log_ingest_event("ingest_seed", "/ingest/seed", {"result": result})
        return result
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Ingest seed failed")
        return {"error": "Internal server error"}


@router.post("/ingest")
def ingest(req: IngestFactsRequest, _auth=Security(deps._require_ingest_key)):
    try:
        deps._check_ingest_rate_limit("ingest")
        loader = deps._get_loader()
        triples_added = 0
        candidates_added = 0
        candidate_ids = []
        documents_done = 0
        transitions_done = 0
        q_updates = 0
        for fact in req.facts:
            normalized_fact = deps._normalize_teaching_fact(fact)
            if req.stage == "candidate":
                candidate_id = loader.ingest_candidate_triple({**normalized_fact, "source_document": req.source_document})
                if candidate_id:
                    candidates_added += 1
                    candidate_ids.append(candidate_id)
            elif loader.ingest_triple({**normalized_fact, "source_document": req.source_document}):
                triples_added += 1
                deps._update_concept_space_embeddings_from_fact(
                    str(normalized_fact.get("subject", "")), str(normalized_fact.get("relation", "")),
                    str(normalized_fact.get("object", "")), float(normalized_fact.get("confidence", 1.0)),
                    {k: v for k, v in normalized_fact.items() if k not in {"subject", "relation", "object", "confidence", "negation"}},
                )
        if req.texts:
            r = loader.ingest_texts_with_context(req.texts, source_document=req.source_document, stage=req.stage)
            triples_added += r.get("triples", 0)
            candidates_added += r.get("candidates", 0)
            candidate_ids.extend(r.get("candidate_ids", []))
        for document in req.documents:
            r = loader.ingest_document(document.content, source_document=document.source_document or req.source_document or "api_document", stage=document.stage or req.stage, metadata=document.metadata)
            documents_done += r.get("documents", 0)
            triples_added += r.get("triples", 0)
            candidates_added += r.get("candidates", 0)
            candidate_ids.extend(r.get("candidate_ids", []))
        if req.transitions:
            q_updates = loader.ingest_transitions(req.transitions)
            transitions_done = len(req.transitions)
        result = {"triples": triples_added, "candidates": candidates_added, "candidate_ids": candidate_ids, "documents": documents_done, "transitions": transitions_done, "q_updates": q_updates}
        deps._log_ingest_event("ingest", "/ingest", {"source_document": req.source_document, "stage": req.stage, "facts_count": len(req.facts), "texts_count": len(req.texts), "documents_count": len(req.documents), "transitions_count": len(req.transitions), "result": result})
        return result
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Ingest failed")
        return {"error": "Internal server error"}


@router.post("/ingest/documents")
def ingest_documents(req: IngestDocumentRequest, _auth=Security(deps._require_ingest_key)):
    try:
        deps._check_ingest_rate_limit("ingest_documents")
        loader = deps._get_loader()
        result = loader.ingest_document(req.content, source_document=req.source_document or "api_document", stage=req.stage, metadata=req.metadata)
        deps._log_ingest_event("ingest_documents", "/ingest/documents", {"source_document": req.source_document or "api_document", "stage": req.stage, "metadata": req.metadata, "result": result})
        return result
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Ingest documents failed")
        return {"error": "Internal server error"}


@router.post("/ingest/pdf")
async def ingest_pdf(
    file: UploadFile = File(...),
    source_document: str | None = Form(default=None),
    stage: str = Form(default="candidate"),
    metadata: str | None = Form(default=None),
    debug: bool = Query(default=False),
    _auth=Security(deps._require_ingest_key),
):
    try:
        deps._require_feature(deps.ENABLE_PDF_INGEST, "pdf_ingest")
        deps._check_ingest_rate_limit("ingest_pdf")
        if not file.filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing file name.")
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only PDF files are supported.")
        payload = await file.read()
        if len(payload) > deps.PDF_MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="PDF exceeds size limit.")
        parsed_metadata = {}
        if metadata:
            try:
                parsed_metadata = deps.json.loads(metadata)
            except deps.json.JSONDecodeError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="metadata must be valid JSON.") from exc
        curriculum_phase = str(parsed_metadata.get("curriculum_phase", "")).strip().lower()
        curriculum_track = deps._resolve_curriculum_track(parsed_metadata.get("curriculum_track"), curriculum_phase) if curriculum_phase else "math"
        teach_curriculum = bool(parsed_metadata.get("teach_curriculum")) and bool(curriculum_phase)
        if curriculum_phase:
            missing_prev = deps._track_missing_prerequisite_phases(curriculum_track, deps._track_completed_phases(curriculum_track), curriculum_phase)
            if missing_prev:
                raise HTTPException(status_code=409, detail={"error": "Prerequisite phases missing", "missing": missing_prev})
        loader = deps._get_loader()
        completed_before = sorted(deps.get_completed_phases(deps._kg))
        archive_info = deps._archive_pdf_if_needed(payload, source_document=source_document or file.filename, metadata=parsed_metadata)
        result = loader.ingest_pdf_document(payload, source_document=source_document or file.filename, stage=stage, metadata=parsed_metadata)
        if teach_curriculum:
            curriculum_payload = {"track": curriculum_track, "phase": curriculum_phase, "taught": deps._inject_track_phase(curriculum_track, curriculum_phase, source_document=source_document or file.filename, source_type="pdf_curriculum"), "completed_phases": sorted(deps._track_completed_phases(curriculum_track))}
            result["curriculum"] = curriculum_payload
            if debug:
                result["debug"] = {"mode": "pdf_upload", "source_document": source_document or file.filename, "stage": stage, "metadata": parsed_metadata, "archive": archive_info, "completed_before": completed_before, "completed_after": curriculum_payload["completed_phases"], "curriculum_track": curriculum_track, "curriculum_phase": curriculum_phase}
        deps._log_ingest_event("ingest_pdf", "/ingest/pdf", {"source_document": source_document or file.filename, "stage": stage, "metadata": parsed_metadata, "size_bytes": len(payload), "result": result})
        return result
    except deps.PDFIngestionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Ingest PDF failed")
        return {"error": "Internal server error"}


@router.post("/ingest/pdfs")
async def ingest_pdfs(
    files: list[UploadFile] = File(...),
    stage: str = Form(default="candidate"),
    metadata: str | None = Form(default=None),
    debug: bool = Query(default=False),
    _auth=Security(deps._require_ingest_key),
):
    try:
        deps._require_feature(deps.ENABLE_PDF_INGEST, "pdf_ingest")
        deps._check_ingest_rate_limit("ingest_pdfs")
        if not files:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one PDF file is required.")
        if len(files) > deps.PDF_MAX_BATCH_FILES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Too many files in batch.")
        parsed_metadata = {}
        if metadata:
            try:
                parsed_metadata = deps.json.loads(metadata)
            except deps.json.JSONDecodeError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="metadata must be valid JSON.") from exc
        curriculum_phase = str(parsed_metadata.get("curriculum_phase", "")).strip().lower()
        teach_curriculum = bool(parsed_metadata.get("teach_curriculum")) and bool(curriculum_phase)
        if curriculum_phase:
            if curriculum_phase not in deps.CURRICULUM_PHASES:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown curriculum_phase: {curriculum_phase}")
            missing_prev = deps.missing_prerequisite_phases(deps.get_completed_phases(deps._kg), curriculum_phase)
            if missing_prev:
                raise HTTPException(status_code=409, detail={"error": "Prerequisite phases missing", "missing": missing_prev})
        completed_before = sorted(deps.get_completed_phases(deps._kg))
        loader = deps._get_loader()
        total_size = 0
        aggregate = {"documents": 0, "pages": 0, "sentences": 0, "triples": 0, "transitions": 0, "q_updates": 0, "candidates": 0, "candidate_ids": [], "skipped": 0, "failed": 0, "failed_documents": []}
        for upload in files:
            filename = upload.filename or "uploaded.pdf"
            if not filename.lower().endswith(".pdf"):
                raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=f"Unsupported file type: {filename}")
            payload = await upload.read()
            total_size += len(payload)
            archive_info = deps._archive_pdf_if_needed(payload, source_document=filename, metadata=parsed_metadata)
            if total_size > deps.PDF_MAX_BATCH_TOTAL_BYTES:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Batch size exceeds limit.")
            if len(payload) > deps.PDF_MAX_FILE_SIZE_BYTES:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"{filename} exceeds per-file size limit.")
            try:
                result = loader.ingest_pdf_document(payload, source_document=filename, stage=stage, metadata=parsed_metadata)
                if debug:
                    result.setdefault("debug", {})
                    result["debug"].update({"archive": archive_info, "source_document": filename})
                for key in ("documents", "pages", "sentences", "triples", "transitions", "q_updates", "candidates", "skipped", "failed"):
                    aggregate[key] += int(result.get(key, 0))
                aggregate["candidate_ids"].extend(result.get("candidate_ids", []))
            except deps.PDFIngestionError:
                aggregate["failed"] += 1
                aggregate["failed_documents"].append({"name": filename, "error": "parse_failure"})
        if teach_curriculum:
            curriculum_payload = {"phase": curriculum_phase, "taught": deps._inject_curriculum_phase(curriculum_phase, source_document=curriculum_phase, source_type="pdf_curriculum"), "completed_phases": sorted(deps.get_completed_phases(deps._kg))}
            aggregate["curriculum"] = curriculum_payload
            if debug:
                aggregate["debug"] = {"mode": "pdf_batch", "stage": stage, "metadata": parsed_metadata, "completed_before": completed_before, "completed_after": curriculum_payload["completed_phases"], "curriculum_phase": curriculum_phase, "files": [upload.filename or "uploaded.pdf" for upload in files]}
        deps._log_ingest_event("ingest_pdfs", "/ingest/pdfs", {"documents": len(files), "stage": stage, "metadata": parsed_metadata, "total_size": total_size, "result": aggregate})
        return aggregate
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Batch ingest PDFs failed")
        return {"error": "Internal server error"}


@router.post("/ingest/candidates")
def ingest_candidates(req: CandidateFactRequest, _auth=Security(deps._require_ingest_key)):
    try:
        deps._check_ingest_rate_limit("ingest_candidates")
        loader = deps._get_loader()
        candidate_ids = []
        for fact in req.facts:
            candidate_id = loader.ingest_candidate_triple({**fact, "source_document": req.source_document})
            if candidate_id:
                candidate_ids.append(candidate_id)
        if req.texts:
            result = loader.ingest_texts_with_context(req.texts, source_document=req.source_document, stage="candidate")
            candidate_ids.extend(result.get("candidate_ids", []))
        result = {"candidates": len(candidate_ids), "candidate_ids": candidate_ids}
        deps._log_ingest_event("ingest_candidates", "/ingest/candidates", {"source_document": req.source_document, "facts_count": len(req.facts), "texts_count": len(req.texts), "result": result})
        return result
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Ingest candidates failed")
        return {"error": "Internal server error"}


@router.get("/ingest/candidates")
def list_ingest_candidates(limit: int = Query(default=50, ge=1, le=200), _auth=Security(deps._require_ingest_key)):
    try:
        loader = deps._get_loader()
        candidates = loader.get_review_queue()[:limit]
        return {"candidates": candidates, "count": len(candidates)}
    except Exception:
        deps.logger.exception("List candidates failed")
        return {"error": "Internal server error"}


@router.post("/ingest/candidates/{candidate_id}/promote")
def promote_ingest_candidate(candidate_id: str, _auth=Security(deps._require_ingest_key)):
    try:
        deps._check_ingest_rate_limit("promote_candidate")
        loader = deps._get_loader()
        if not loader.promote_candidate(candidate_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found or not pending.")
        result = {"ok": True, "candidate_id": candidate_id}
        deps._log_ingest_event("promote_candidate", "/ingest/candidates/{candidate_id}/promote", result)
        return result
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Promote candidate failed")
        return {"error": "Internal server error"}


@router.post("/ingest/candidates/{candidate_id}/reject")
def reject_ingest_candidate(candidate_id: str, req: CandidateReviewRequest, _auth=Security(deps._require_ingest_key)):
    try:
        deps._check_ingest_rate_limit("reject_candidate")
        loader = deps._get_loader()
        if not loader.reject_candidate(candidate_id, req.reason):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found or not pending.")
        result = {"ok": True, "candidate_id": candidate_id}
        deps._log_ingest_event("reject_candidate", "/ingest/candidates/{candidate_id}/reject", {"candidate_id": candidate_id, "reason": req.reason})
        return result
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Reject candidate failed")
        return {"error": "Internal server error"}
