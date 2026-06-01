"""core/parser.py — Semantic natural language parser.

Extracts (subject, relation, object) triples from text.

Supported input forms
---------------------
- Standard     : "rain causes flood 0.9"
- Negation     : "barrier does not cause damage"
- Compound obj : "flood causes damage and collapse"
- Dependency   : "model is based on attention" / "encoder uses memory"
- If/then      : "if flood then evacuate"  (→ implies)
- When         : "when crisis, evacuate"   (→ implies)
- Arrow chain  : "rain → flood → crisis"  (→ two triples)
- Bulk         : parse_bulk(["...", "..."])
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Canonical relation-verb vocabulary
# Both the plural/3rd-person-singular and bare-infinitive forms are listed so
# that the parser matches regardless of whether singularization ran first.
# ---------------------------------------------------------------------------
RELATION_MAP: dict[str, str] = {
    # causal
    "causes": "causes",       "cause": "causes",
    "triggers": "triggers",   "trigger": "triggers",
    "produces": "causes",     "produce": "causes",
    "generates": "causes",    "generate": "causes",
    "escalates": "leads_to",  "escalate": "leads_to",
    "results": "causes",      "result": "causes",
    # directional
    "leads": "leads_to",      "lead": "leads_to",
    "leads_to": "leads_to",
    "results_in": "causes",
    "follows": "follows",     "follow": "follows",
    "precedes": "precedes",   "precede": "precedes",
    # preventive / mitigating
    "prevents": "prevents",   "prevent": "prevents",
    "blocks": "prevents",     "block": "prevents",
    "stops": "prevents",      "stop": "prevents",
    "mitigates": "prevents",  "mitigate": "prevents",
    "reduces": "reduces",     "reduce": "reduces",
    "lowers": "reduces",      "lower": "reduces",
    "limits": "reduces",      "limit": "reduces",
    # amplifying
    "increases": "increases", "increase": "increases",
    "amplifies": "increases", "amplify": "increases",
    "worsens": "increases",   "worsen": "increases",
    "raises": "increases",    "raise": "increases",
    "improves": "increases",  "improve": "increases",
    "enhances": "increases",  "enhance": "increases",
    # requirement / dependency
    "requires": "requires",   "require": "requires",
    "needs": "requires",      "need": "requires",
    "demands": "requires",    "demand": "requires",
    # logical
    "implies": "implies",     "imply": "implies",
    "indicates": "implies",   "indicate": "implies",
    "suggests": "implies",    "suggest": "implies",
    # state
    "is": "is",  "are": "is",  "was": "is",  "were": "is",
    # possession
    "has": "has",  "have": "has",  "had": "has",
    # dependency-like relations
    "uses": "uses", "use": "uses",
    "utilizes": "uses", "utilize": "uses",
    "contains": "contains", "contain": "contains",
    "enables": "enables", "enable": "enables",
    "depends": "depends_on", "depend": "depends_on",
}

# Prepositions that may follow a relation verb before the object
_RELATION_PREPOSITIONS = {"to", "in", "into", "from", "with", "by", "at", "on"}

_IF_THEN = re.compile(r"if\s+(.+?)\s+then\s+(.+)", re.I)
_WHEN    = re.compile(r"when\s+(.+?)[,;]\s*(.+)", re.I)
_ARROW_SEP = re.compile(r"\s*[→\->=]+\s*")
_DEP_PATTERNS = [
    (re.compile(r"^(.+?)\s+is\s+based\s+on\s+(.+)$", re.I), "depends_on"),
    (re.compile(r"^(.+?)\s+depends\s+on\s+(.+)$", re.I), "depends_on"),
    (re.compile(r"^(.+?)\s+consists\s+of\s+(.+)$", re.I), "contains"),
    (re.compile(r"^(.+?)\s+is\s+composed\s+of\s+(.+)$", re.I), "contains"),
    (re.compile(r"^(.+?)\s+uses\s+(.+)$", re.I), "uses"),
    (re.compile(r"^(.+?)\s+contains\s+(.+)$", re.I), "contains"),
    (re.compile(r"^(.+?)\s+enables\s+(.+)$", re.I), "enables"),
]

# Trailing verbs that appear after the object in "when" clauses
_TRAILING_VERBS = re.compile(
    r"\s+\b(occurs?|happens?|appears?|takes?\s+place|arises?)\s*$", re.I
)

# Auxiliary verbs to ignore when building the subject of a negated sentence
_AUX_VERBS = {"does", "do", "did"}

# Confidence-level qualifiers that may follow a numeric confidence value
_CONF_QUALIFIERS = frozenset({"high", "low", "medium", "very", "extremely", "likely", "unlikely"})


class SemanticParser:
    """Parse natural-language statements into semantic (subject, relation, object) triples."""

    def __init__(self, enable_spacy_dep: bool = False, spacy_model_name: str = "en_core_web_sm"):
        self.enable_spacy_dep = bool(enable_spacy_dep)
        self.spacy_model_name = spacy_model_name
        self._spacy_nlp = None
        self._spacy_checked = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, text: str, context: Optional[dict] = None) -> Optional[list[dict]]:
        """Parse a single statement.

        Returns a list of triple dicts, or None if parsing fails.
        Each dict has keys: subject, relation, object, negation, confidence.
        """
        original_text = text.strip()
        text = original_text
        if not text:
            return None

        # Extract optional trailing confidence float
        confidence = 0.8
        words = text.split()
        try:
            trailing = float(words[-1])
            if 0.0 <= trailing <= 1.0:
                confidence = trailing
                text = " ".join(words[:-1]).strip()
        except (ValueError, IndexError):
            # Also handle "… 0.95 high" — a float followed by a qualifier word
            if len(words) >= 2 and words[-1].lower() in _CONF_QUALIFIERS:
                try:
                    trailing = float(words[-2])
                    if 0.0 <= trailing <= 1.0:
                        confidence = trailing
                        text = " ".join(words[:-2]).strip()
                except (ValueError, IndexError):
                    pass

        # Try structured patterns first, fall back to free-text
        triples = self._parse_if_then(text, confidence)
        extraction_method = "deterministic_if_then"
        if not triples:
            triples = self._parse_when(text, confidence)
            extraction_method = "deterministic_when"
        if not triples:
            triples = self._parse_arrow(text, confidence)
            extraction_method = "deterministic_arrow"
        if not triples:
            triples = self._parse_dependency(text, confidence)
            extraction_method = "dependency_pattern"
        if not triples:
            triples = self._parse_spacy_dependency(text, confidence)
            extraction_method = "spacy_dependency"
        if not triples:
            triples = self._parse_free(text, confidence)
            extraction_method = "rule_based_free_text"

        if triples:
            for triple in triples:
                triple["source_text"] = original_text
                triple["extraction_method"] = extraction_method
                if context:
                    triple.update(context)

        return triples if triples else None

    def parse_bulk(self, texts: list[str], context: Optional[dict] = None) -> list[dict]:
        """Parse multiple statements and return all extracted triples."""
        results = []
        for t in texts:
            parsed = self.parse(t, context=context)
            if parsed:
                results.extend(parsed)
        return results

    def normalize(self, text: str) -> str:
        """Lowercase, strip articles, collapse whitespace, singularize nouns."""
        text = text.lower().strip()
        text = re.sub(r"\b(a|an|the)\b", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return " ".join(self._singularize(w) for w in text.split())

    # ------------------------------------------------------------------
    # Structured-pattern parsers
    # ------------------------------------------------------------------

    def _parse_if_then(self, text: str, confidence: float) -> Optional[list[dict]]:
        m = _IF_THEN.match(text)
        if not m:
            return None
        subject = self._clean(m.group(1))
        obj     = self._clean(m.group(2))
        return [self._triple(subject, "implies", obj, False, confidence)]

    def _parse_when(self, text: str, confidence: float) -> Optional[list[dict]]:
        m = _WHEN.match(text)
        if not m:
            return None
        subject = self._clean(m.group(1))
        # Strip trailing stand-alone verbs such as "occurs", "happens"
        raw_obj = _TRAILING_VERBS.sub("", m.group(2))
        obj     = self._clean(raw_obj)
        return [self._triple(subject, "implies", obj, False, confidence)]

    def _parse_arrow(self, text: str, confidence: float) -> Optional[list[dict]]:
        parts = [p.strip() for p in _ARROW_SEP.split(text) if p.strip()]
        if len(parts) < 2:
            return None
        results = []
        for i in range(len(parts) - 1):
            subj = self._clean(parts[i])
            obj  = self._clean(parts[i + 1])
            conf = round(confidence * (0.9 ** i), 4)
            results.append(self._triple(subj, "leads_to", obj, False, conf))
        return results

    def _parse_dependency(self, text: str, confidence: float) -> Optional[list[dict]]:
        lower = re.sub(r"\b(a|an|the)\b", "", text.lower())
        lower = re.sub(r"\s+", " ", lower).strip()
        for pattern, relation in _DEP_PATTERNS:
            m = pattern.match(lower)
            if not m:
                continue
            subject = self._clean(m.group(1))
            obj_raw = self._clean(m.group(2))
            if not subject or not obj_raw:
                return None
            obj_parts = [p.strip() for p in obj_raw.split(" and ") if p.strip()]
            return [
                self._triple(
                    subject,
                    relation,
                    self._singularize_phrase(self._lemmatize_phrase(p.split())),
                    False,
                    confidence if i == 0 else round(confidence * 0.9, 4),
                )
                for i, p in enumerate(obj_parts)
            ]
        return None

    def _parse_spacy_dependency(self, text: str, confidence: float) -> Optional[list[dict]]:
        """Optional full dependency parser path (spaCy).

        This is intentionally optional and should never break the default rule-based flow.
        """
        if not self.enable_spacy_dep:
            return None

        nlp = self._ensure_spacy_pipeline()
        if nlp is None:
            return None

        try:
            doc = nlp(text)
        except Exception:
            return None

        triples = []
        seen = set()

        def _span(tok) -> str:
            try:
                return self._clean(" ".join(t.text for t in tok.subtree))
            except Exception:
                return self._clean(tok.text)

        for token in doc:
            if token.pos_ not in ("VERB", "AUX"):
                continue

            subj = None
            obj = None
            for child in token.children:
                if child.dep_ in ("nsubj", "nsubjpass", "csubj") and subj is None:
                    subj = child
                if child.dep_ in ("dobj", "obj", "attr", "oprd", "pobj") and obj is None:
                    obj = child

            if obj is None:
                for child in token.children:
                    if child.dep_ == "prep":
                        pobj = next((g for g in child.children if g.dep_ == "pobj"), None)
                        if pobj is not None:
                            obj = pobj
                            break

            if subj is None or obj is None:
                continue

            subject = _span(subj)
            relation = RELATION_MAP.get(token.lemma_.lower(), token.lemma_.lower())
            object_ = _span(obj)
            negation = any(c.dep_ == "neg" for c in token.children)

            if not subject or not relation or not object_:
                continue
            key = (subject, relation, object_)
            if key in seen:
                continue
            seen.add(key)
            triples.append(self._triple(subject, relation, object_, negation, round(confidence * 0.92, 4)))

        return triples or None

    # ------------------------------------------------------------------
    # Free-text parser
    # ------------------------------------------------------------------

    def _parse_free(self, text: str, confidence: float) -> Optional[list[dict]]:
        # Detect and strip negation — covers 15+ negation patterns
        negation_patterns = [
            r"\bnot\b", r"\bno\b", r"\bnever\b", r"\bcannot\b", r"\bcan't\b",
            r"\bdoes not\b", r"\bdoesn't\b", r"\bdo not\b", r"\bdon't\b",
            r"\bwill not\b", r"\bwon't\b", r"\bis not\b", r"\bisn't\b",
            r"\bare not\b", r"\baren't\b", r"\bwithout\b", r"\blacks\b",
            r"\babsent\b", r"\bmissing\b",
        ]
        negation = False
        text_clean = text
        for pattern in negation_patterns:
            if re.search(pattern, text, re.I):
                negation = True
                text_clean = re.sub(pattern, "", text_clean, flags=re.I)
        # Remove auxiliary verbs that may remain after negation stripping
        aux_verbs = r"\b(does|do|did|can|could|will|would|should|may|might|have|has|had)\b"
        text_clean = re.sub(aux_verbs, "", text_clean, flags=re.I)

        # Lowercase + remove articles (but keep relation verbs intact for lookup)
        lower = re.sub(r"\b(a|an|the)\b", "", text_clean.lower())
        lower = re.sub(r"\s+", " ", lower).strip()
        words = lower.split()

        # Locate the first recognised relation verb
        rel_idx       = None
        rel_canonical = None
        for i, w in enumerate(words):
            base = self._lemmatize_verb(w)
            if w in RELATION_MAP or base in RELATION_MAP:
                rel_idx       = i
                rel_canonical = RELATION_MAP.get(w, RELATION_MAP.get(base, w))
                break

        if rel_idx is None or rel_idx == 0:
            # Fallback: word[0]=subject, word[1]=relation, rest=object
            if len(words) < 3:
                return None
            subject  = self._singularize_phrase(words[:1])
            relation = words[1]
            obj      = self._singularize_phrase(words[2:])
            return [self._triple(subject, relation, obj, negation, confidence)]

        subject_words = [
            w for w in words[:rel_idx]
            if w not in _AUX_VERBS and self._lemmatize_verb(w) not in _AUX_VERBS
        ]
        subject = self._singularize_phrase(subject_words)

        # Skip prepositions that follow some verbs ("leads to", "results in")
        obj_start = rel_idx + 1
        if obj_start < len(words) and words[obj_start] in _RELATION_PREPOSITIONS:
            obj_start += 1

        obj_words = words[obj_start:]
        if not subject or not obj_words:
            return None

        # Expand compound objects split on " and "
        obj_raw = " ".join(obj_words)
        obj_parts = [p.strip() for p in obj_raw.split(" and ") if p.strip()]

        return [
            self._triple(
                subject,
                rel_canonical,
                self._singularize_phrase(p.split()),
                negation,
                confidence if i == 0 else round(confidence * 0.9, 4),
            )
            for i, p in enumerate(obj_parts)
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clean(self, text: str) -> str:
        """Lowercase, strip articles, singularize."""
        text = re.sub(r"\b(a|an|the)\b", "", text.lower())
        text = re.sub(r"\s+", " ", text).strip()
        return self._singularize_phrase(text.split())

    def _singularize_phrase(self, words: list[str]) -> str:
        return " ".join(self._singularize(w) for w in words)

    def _lemmatize_phrase(self, words: list[str]) -> list[str]:
        return [self._lemmatize_verb(w) for w in words]

    def _ensure_spacy_pipeline(self):
        if not self.enable_spacy_dep:
            return None
        if self._spacy_checked:
            return self._spacy_nlp

        self._spacy_checked = True
        try:
            import spacy  # optional dependency

            self._spacy_nlp = spacy.load(self.spacy_model_name)
        except Exception:
            self._spacy_nlp = None
        return self._spacy_nlp

    @staticmethod
    def _lemmatize_verb(word: str) -> str:
        # Lightweight lemmatizer (no heavy external NLP model required).
        irregular = {
            "does": "do",
            "did": "do",
            "done": "do",
            "has": "have",
            "had": "have",
            "was": "be",
            "were": "be",
        }
        if word in irregular:
            return irregular[word]

        if len(word) > 5 and word.endswith("ies"):
            return word[:-3] + "y"
        if len(word) > 4 and word.endswith("ing"):
            stem = word[:-3]
            if len(stem) > 3 and stem[-1] == stem[-2]:
                stem = stem[:-1]
            return stem
        if len(word) > 3 and word.endswith("ed"):
            stem = word[:-2]
            if len(stem) > 3 and stem[-1] == stem[-2]:
                stem = stem[:-1]
            return stem
        if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes", "zes", "oes")):
            return word[:-2]
        if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "is", "us")):
            return word[:-1]
        return word

    @staticmethod
    def _singularize(word: str) -> str:
        if len(word) > 4 and word.endswith("ies"):
            return word[:-3] + "y"
        if len(word) > 4 and word.endswith("es") and word[-3] in "sxz":
            return word[:-2]
        # Skip words whose singular form already ends in -is / -ss / -us
        # (e.g. "crisis", "basis", "focus", "radius")
        if (
            len(word) > 3
            and word.endswith("s")
            and not word.endswith("ss")
            and not word.endswith("is")
            and not word.endswith("us")
        ):
            return word[:-1]
        return word

    @staticmethod
    def _triple(subject: str, relation: str, obj: str,
                negation: bool, confidence: float) -> dict:
        return {
            "subject":    subject,
            "relation":   relation,
            "object":     obj,
            "negation":   negation,
            "confidence": round(float(confidence), 4),
        }
