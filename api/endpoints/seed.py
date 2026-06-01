from fastapi import APIRouter
import api.dependencies as deps

router = APIRouter(tags=["seed"])


@router.get("/seed/status")
def seed_status():
    try:
        txt_files = list(deps.SEED_TXT_DIR.glob("*.txt")) if deps.SEED_TXT_DIR.exists() else []
        txt_triple_count = 0
        for s, r, o, c in deps._kg.triples:
            metadata = deps._kg.get_metadata(s, r, o)
            if metadata.get("source_type") == "text_seed":
                txt_triple_count += 1
        completed_phases = deps.get_completed_phases(deps._kg)
        return {
            "status": "ok",
            "seed_txt_directory_exists": deps.SEED_TXT_DIR.exists(),
            "seed_txt_count": len(txt_files),
            "seed_txts": [f.name for f in txt_files],
            "kg_triples_total": len(deps._kg.triples),
            "kg_triples_from_texts": txt_triple_count,
            "completed_curriculum_phases": sorted(completed_phases),
            "all_phases_complete": len(completed_phases) == 6,
        }
    except Exception as e:
        return {"error": str(e)}
