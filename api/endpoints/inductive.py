from fastapi import APIRouter, HTTPException
import api.dependencies as deps
from api.models.requests import (
    InductiveRequest, AskRequest, InductiveFeedbackRequest,
    PredictRequest, AnalogyRequest,
)

router = APIRouter(tags=["inductive"])


@router.post("/learn/inductive")
def learn_inductive(req: InductiveRequest):
    try:
        predicate = req.predicate
        examples = [(s, o) for s, o in req.examples]
        if not predicate or not examples:
            raise HTTPException(status_code=400, detail="Missing predicate or examples")
        learned_rule = deps._inductive_learner.add_examples(predicate, examples)
        if learned_rule:
            return {"ok": True, "predicate": predicate, "rule": {"type": learned_rule.rule_type, "description": learned_rule.description, "confidence": learned_rule.confidence, "examples_used": len(deps._inductive_learner.examples.get(predicate, []))}}
        return {"ok": True, "predicate": predicate, "message": "Need more examples (at least 3)", "examples_used": len(deps._inductive_learner.examples.get(predicate, []))}
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.post("/learn/ask")
def learn_ask(req: AskRequest):
    try:
        predicate = req.predicate
        subject = req.subject
        if not predicate or subject is None:
            raise HTTPException(status_code=400, detail="Missing predicate or subject")
        question = deps._curious_learner.ask(predicate, subject)
        return {"ok": True, "question": question}
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.post("/learn/feedback")
def learn_feedback(req: InductiveFeedbackRequest):
    try:
        predicate = req.predicate
        subject = req.subject
        correct_object = req.correct_object
        if not predicate or subject is None or correct_object is None:
            raise HTTPException(status_code=400, detail="Missing predicate, subject, or correct_object")
        deps._curious_learner.learn_from_feedback(predicate, subject, correct_object)
        learned_rule = deps._inductive_learner.add_examples(predicate, [(subject, correct_object)])
        return {"ok": True, "message": f"Learned: {subject} {predicate} {correct_object}", "pattern_found": learned_rule.description if learned_rule else "Pattern not yet found, need more examples"}
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.post("/learn/predict")
def learn_predict(req: PredictRequest):
    try:
        predicate = req.predicate
        subject = req.subject
        if not predicate or subject is None:
            raise HTTPException(status_code=400, detail="Missing predicate or subject")
        prediction = deps._inductive_learner.predict(predicate, subject)
        confidence = deps._inductive_learner.get_confidence(predicate)
        return {"ok": True, "predicate": predicate, "subject": subject, "prediction": prediction, "confidence": confidence, "has_rule": prediction is not None}
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/learn/rules")
def get_learn_rules():
    try:
        summary = deps._curious_learner.get_learning_summary()
        return {"ok": True, "summary": summary}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.post("/learn/analogy")
def learn_analogy(req: AnalogyRequest):
    try:
        source = req.source
        target = req.target
        if not source or not target:
            raise HTTPException(status_code=400, detail="Missing source or target")
        result = deps._analogy_reasoner.transfer_knowledge(source, target)
        if result:
            for rule in result.get("rules", []):
                deps._inductive_learner.rules[target].append(rule)
            return {"ok": True, "source": source, "target": target, "rules": [{"type": r.rule_type, "description": r.description, "confidence": r.confidence} for r in result.get("rules", [])], "explanation": result.get("explanation")}
        raise HTTPException(status_code=404, detail=f"No analogy found between {source} and {target}")
    except HTTPException:
        raise
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}


@router.get("/learn/inductive/status")
def get_inductive_learning_status():
    try:
        return {"ok": True, "total_examples": sum(len(ex) for ex in deps._inductive_learner.examples.values()), "total_rules": sum(len(rules) for rules in deps._inductive_learner.rules.values()), "predicates_with_rules": list(deps._inductive_learner.rules.keys()), "pending_questions": len(deps._curious_learner.pending_questions), "learning_history_count": len(deps._curious_learner.learning_history)}
    except Exception:
        deps.logger.exception("Request failed")
        return {"error": "Internal server error"}
