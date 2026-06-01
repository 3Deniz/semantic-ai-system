from pydantic import BaseModel
from typing import Optional, Any


class StateRequest(BaseModel):
    state: str


class SimulateRequest(BaseModel):
    state: str
    steps: Optional[int] = 10


class AssertRequest(BaseModel):
    subject: str
    relation: str
    obj: str
    confidence: float = 1.0


class SemanticFeedbackRequest(BaseModel):
    subject: str
    relation: str
    obj: str
    feedback: str  # "correct" or "wrong"


class MathRequest(BaseModel):
    operation: str  # "add", "subtract", "multiply", "divide"
    a: float
    b: float


class IngestTextsRequest(BaseModel):
    texts: list[str]
    source_document: Optional[str] = None
    stage: str = "validated"


class IngestDocumentRequest(BaseModel):
    content: str
    source_document: Optional[str] = None
    stage: str = "candidate"
    metadata: dict = {}


class CandidateFactRequest(BaseModel):
    facts: list[dict] = []
    texts: list[str] = []
    source_document: Optional[str] = None


class CandidateReviewRequest(BaseModel):
    reason: Optional[str] = None


class IngestFactsRequest(BaseModel):
    facts: list[dict] = []
    texts: list[str] = []
    documents: list[IngestDocumentRequest] = []
    transitions: list[dict] = []
    source_document: Optional[str] = None
    stage: str = "validated"


class InductiveRequest(BaseModel):
    predicate: str
    examples: list[list]


class AskRequest(BaseModel):
    predicate: str
    subject: Any


class InductiveFeedbackRequest(BaseModel):
    predicate: str
    subject: Any
    correct_object: Any


class PredictRequest(BaseModel):
    predicate: str
    subject: Any


class AnalogyRequest(BaseModel):
    source: str
    target: str
