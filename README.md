# Semantic AI Decision Engine

Hybrid AI reasoning system combining Q-learning, JEPA world modeling, semantic knowledge graphs, cognitive architecture, curriculum learning, inductive learning, and symbolic mathematics.

**Stack:** Python 3.11, FastAPI, NumPy, Next.js dashboard

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    FastAPI (api.py)                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────┐  │
│  │ Cognitive │ │ Semantic │ │   Learning Stack     │  │
│  │ Pipeline  │ │   Stack  │ │                      │  │
│  │ ┌──────┐ │ │ ┌──────┐ │ │ ┌──────┐ ┌────────┐ │  │
│  │ │Thought│ │ │ │Parser│ │ │ │ JEPA │ │Curriculum│ │  │
│  │ │ Loop  │ │ │ ├──────┤ │ │ ├──────┤ ├────────┤ │  │
│  │ ├──────┤ │ │ │  KG   │ │ │ │ Q-Lrn│ │Inductive│ │  │
│  │ │Intent│ │ │ ├──────┤ │ │ ├──────┤ ├────────┤ │  │
│  │ ├──────┤ │ │ │ TMS   │ │ │ │Concept│ │ Numeracy│ │  │
│  │ │Conflict│ │ │ ├──────┤ │ │ ├──────┤ ├────────┤ │  │
│  │ ├──────┤ │ │ │Reason │ │ │ │Rule  │ │Economy  │ │  │
│  │ │Memory│ │ │ └──────┘ │ │ ├──────┤ ├────────┤ │  │
│  │ └──────┘ │ │ Symbolic │ │ │Online│ │Primary  │ │  │
│  │ ┌──────┐ │ │   Math   │ │ └──────┘ └────────┘ │  │
│  │ │Emotion│ │ └──────┘ │ │                        │  │
│  │ └──────┘ │           │ │                        │  │
│  └──────────┘ └──────────┘ └──────────────────────┘  │
│                                                       │
│  /semantic/*  /learn/*  /ingest/*  /memory/*  /seed* │
└─────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
            ┌─────────────┐    ┌─────────────────┐
            │  Next.js    │    │  RL Agent       │
            │  Dashboard  │    │  (main.py)      │
            └─────────────┘    └─────────────────┘
```

---

## Core Components

### Cognitive Pipeline (`cognition/`)

| Module | Purpose |
|---|---|
| **ThoughtLoop** | Full deliberative pipeline: perception → memory → intent → conflict → simulation → decision → feedback |
| **EmotionSpace** | 5-D emotion vector [fear, anger, sadness, surprise, calm] modulated by JEPA prediction surprise |
| **LayeredMemory** | Short-term, working, long-term (pattern-based), failure, and episodic memory layers |
| **ConflictResolver** | Resolves tensions between Q-learning, simulation, and JEPA scoring sources |
| **IntentEngine** | Goal ranking: survival > stability > risk_reduction > consistency > task_completion |
| **MultiSpaceEmbedding** | Embeds state into 6 cognitive spaces: risk, goal, memory, attention, self, semantic + emotion |

### Semantic Stack (`core/`)

| Module | Purpose |
|---|---|
| **SemanticParser** | NL-to-triple parser with dependency, rule-based, and if-then/when patterns |
| **KnowledgeGraph** | Triple store with metadata provenance |
| **LiteTMS** | Truth Maintenance System with confidence decay, conflict detection, candidate review |
| **Reasoner** | Forward inference via transitive `is` relation chaining |
| **SpaceRelationsBuilder** | Cross-space relation graph builder (risk, goal, memory, attention, self, semantic, arithmetic, calculus, curriculum, emotion) |
| **SymbolicMath** | Arithmetic, calculus (derivatives/integrals/logarithms), algebra (matrix determinant), equation solving |
| **NumberParser** | Number decomposition up to 10^12, decimals, scientific notation |
| **DataLoader** | Bulk ingestion of facts, texts, PDFs, transitions; candidate review workflow |
| **InductiveLearner** | Pattern extraction from examples, curious active learning, analogical reasoning |

### Learning Stack (`learning/`)

| Module | Purpose |
|---|---|
| **JEPAModel** | Joint Embedding Predictive Architecture — predicts next-state latent, scores action quality, surprise signal for emotion |
| **CurriculumController** | Autonomic Curriculum Controller — 3 stages: LITERACY → NUMERACY → REASONING, stability-gated progression |
| **ConceptLearner** | Extracts abstract patterns from TMS beliefs (e.g., "X causes flood") |
| **RuleLearner** | Learns if-then rules via `is` relation chaining |
| **OnlineLearner** | Updates belief confidence from user feedback ("correct"/"wrong") with emotion modulation |

### Mathematics Curriculum

6 phased phases: `letters` → `digits` → `operations` → `real_numbers` → `calculus` → `logarithms`

Each phase unlocks new capabilities. Gate enforced by `can_compute_expression()` and `missing_curriculum_phases()`.

### Economy Curriculum

7 phases: `foundations` → `demand_supply` → `elasticity` → `cost_revenue_profit` → `market_structures` → `macro_graphs` → `policy_shocks`

### Primary Readiness

6-domain graduation profile: literacy, mathematics, science, social_studies, economy, digital_and_life_skills (43 concepts total). Includes automated drip-feeding plans.

### Inductive Learning (Child-like Learning)

- **PatternExtractor** — Infers numeric (linear, constant-operation) and string (identity, prefix, suffix) patterns from example pairs
- **InductiveLearner** — Adds examples, detects patterns after 3+ examples, predicts using learned rules
- **CuriousLearner** — Asks questions when uncertain ("What is ...?"), learns from user feedback
- **AnalogicalReasoner** — Transfers knowledge via analogy (addition → multiplication, subtraction → division)

---

## API Endpoints

### System

| Method | Path | Description |
|---|---|---|
| GET | `/` | Status check |
| GET | `/metrics` | System metrics |
| GET | `/loop/health` | Thought-loop artifact health |

### Decision Engine

| Method | Path | Description |
|---|---|---|
| POST | `/think` | Full deliberative thought loop |
| POST | `/decision` | Hybrid decision (RL + simulation + JEPA) |
| POST | `/simulate` | N-step simulation |
| GET | `/explain` | Explain decision for a state |
| GET | `/graph` | Q-table policy graph |
| GET | `/thought_trace` | Recent thought traces |
| GET | `/debug/emotion/jepa` | JEPA-to-emotion debug sequence |

### Semantic Knowledge

| Method | Path | Description |
|---|---|---|
| POST | `/semantic/assert` | Add triple to KG + TMS |
| GET | `/semantic/beliefs` | Active TMS beliefs |
| POST | `/semantic/infer` | Run reasoner inference |
| POST | `/semantic/feedback` | Feedback on belief (correct/wrong) |
| GET | `/semantic/concepts` | Extracted concepts |
| GET | `/semantic/abstractions` | Abstract patterns and rules |
| GET | `/semantic/search` | Scored fact search with provenance |
| GET | `/semantic/recall` | Search + cross-space relations |
| GET | `/semantic/relations` | Cross-space relation graph |
| GET | `/semantic/concept/{concept}/embedding` | Per-space concept embeddings |
| GET | `/semantic/concept/{concept}/trace` | Concept-centered cross-space trace |

### Learning

| Method | Path | Description |
|---|---|---|
| POST | `/learn/process` | Concept learning + curriculum progression |
| POST | `/learn/abstraction/trigger` | Promote abstractions to curriculum |
| POST | `/learn/inductive` | Add examples for inductive learning |
| POST | `/learn/ask` | Curious learner question |
| POST | `/learn/feedback` | Teach the curious learner |
| POST | `/learn/predict` | Predict using learned rules |
| GET | `/learn/rules` | List learned rules |
| POST | `/learn/analogy` | Transfer knowledge by analogy |
| GET | `/learn/inductive/status` | Inductive learner status |
| POST | `/learn/numeracy/basic` | Teach baseline numeracy |
| POST | `/learn/curriculum/phase/{phase}` | Teach curriculum phase |
| POST | `/learn/curriculum/economy/phase/{phase}` | Teach economy phase |
| GET | `/learn/curriculum/status` | Curriculum status |
| GET | `/learn/curriculum/economy/status` | Economy curriculum status |
| GET | `/learn/bootstrap/plan` | Staged learning plan |
| POST | `/learn/reset` | Reset state (soft/hard/full modes) |

### Primary Readiness

| Method | Path | Description |
|---|---|---|
| GET | `/learn/primary/readiness` | Graduation readiness audit |
| GET | `/learn/primary/plan` | Weekly training plan |
| GET | `/learn/primary/drip/plan` | Drip-feed learning plan |
| POST | `/learn/primary/drip/run` | Execute drip feeding |
| GET | `/learn/primary/abstraction/pending` | Pending abstractions |
| POST | `/learn/primary/abstraction/resolve` | Resolve pending abstractions |

### Math

| Method | Path | Description |
|---|---|---|
| POST | `/math/calculate` | Arithmetic (prerequisite-gated) |

### Ingest (API-key protected)

| Method | Path | Description |
|---|---|---|
| POST | `/ingest` | Bulk facts/texts/transitions |
| POST | `/ingest/texts` | Natural language text |
| POST | `/ingest/seed` | Domain seed knowledge |
| POST | `/ingest/documents` | Full document |
| POST | `/ingest/pdf` | Single PDF |
| POST | `/ingest/pdfs` | Batch PDFs |
| GET/POST | `/ingest/candidates` | List/create candidates |
| POST | `/ingest/candidates/{id}/promote` | Promote candidate |
| POST | `/ingest/candidates/{id}/reject` | Reject candidate |

### Memory

| Method | Path | Description |
|---|---|---|
| GET | `/memory/episodic` | Episodic memory entries |
| GET | `/memory/emotional_trend` | Emotion timeline |

### Seed

| Method | Path | Description |
|---|---|---|
| GET | `/seed/status` | Seed knowledge status |

---

## Installation

### Backend

```bash
pip install -r requirements.txt
```

Optional: enable spaCy dependency parser (recommended for academic PDFs):

```bash
pip install spacy
python -m spacy download en_core_web_sm
export ENABLE_SPACY_DEP_PARSER=true
export SPACY_MODEL_NAME=en_core_web_sm
```

Start the API:

```bash
uvicorn api:app --reload
```

API docs at http://127.0.0.1:8000/docs

### Frontend Dashboard

```bash
cd dashboard
npm install
npm run dev
```

Open at http://localhost:3000/dashboard

---

## Usage

### Curriculum-First Learning

Phases are taught in order via API:

```bash
curl -X POST http://127.0.0.1:8000/learn/curriculum/phase/letters
curl -X POST http://127.0.0.1:8000/learn/curriculum/phase/digits
curl -X POST http://127.0.0.1:8000/learn/curriculum/phase/operations
curl http://127.0.0.1:8000/learn/curriculum/status
```

Or teach all numeracy at once:

```bash
curl -X POST http://127.0.0.1:8000/learn/numeracy/basic
```

### Inductive Learning (Pattern Extraction)

```bash
# Learn addition from examples
curl -X POST http://127.0.0.1:8000/learn/inductive \
  -H "Content-Type: application/json" \
  -d '{"predicate":"+","examples":[[2,5],[3,7],[4,9],[5,11]]}'

# Predict using learned rule
curl -X POST http://127.0.0.1:8000/learn/predict \
  -H "Content-Type: application/json" \
  -d '{"predicate":"+","subject":6}'

# Teach via feedback
curl -X POST http://127.0.0.1:8000/learn/feedback \
  -H "Content-Type: application/json" \
  -d '{"predicate":"+","subject":100,"correct_object":105}'

# Transfer knowledge by analogy
curl -X POST http://127.0.0.1:8000/learn/analogy \
  -H "Content-Type: application/json" \
  -d '{"source":"+","target":"*"}'

# List learned rules
curl http://127.0.0.1:8000/learn/rules
```

### Semantic Search

```bash
curl "http://127.0.0.1:8000/semantic/search?query=flood"
curl "http://127.0.0.1:8000/semantic/search?query=2%2B3"
curl "http://127.0.0.1:8000/semantic/search?query=2%5E10"
curl "http://127.0.0.1:8000/semantic/search?query=5!"
curl "http://127.0.0.1:8000/semantic/search?query=%7C-5%7C"
```

### PDF Ingestion

```bash
curl -X POST http://127.0.0.1:8000/ingest/pdf \
  -F "file=@document.pdf" \
  -F 'stage=candidate' \
  -F 'metadata={"curriculum_phase":"letters","teach_curriculum":true}'
```

### Reset Learning State

```bash
# Soft reset (clear memory, keep graph.json)
curl -X POST "http://127.0.0.1:8000/learn/reset?confirm=true&mode=soft"

# Hard reset (clear + reload seed knowledge)
curl -X POST "http://127.0.0.1:8000/learn/reset?confirm=true&mode=hard"

# Full reset (hard + JEPA retrain + curriculum reset)
curl -X POST "http://127.0.0.1:8000/learn/reset?confirm=true&mode=full"
```

### Economy Curriculum

```bash
curl -X POST http://127.0.0.1:8000/learn/curriculum/economy/phase/foundations
curl http://127.0.0.1:8000/learn/curriculum/economy/status
```

### Primary Readiness

```bash
curl http://127.0.0.1:8000/learn/primary/readiness
curl "http://127.0.0.1:8000/learn/primary/drip/run?target_coverage=0.85&max_total_cycles=500"
```

### Seed Knowledge Status

```bash
curl http://127.0.0.1:8000/seed/status
```

---

## Configuration

Key settings in `config.py` and `config/*.json` files:

| File | Configures |
|---|---|
| `config.py` | RL hyperparameters, environment dynamics, JEPA, curriculum, feature flags, rate limits |
| `config/curriculum_phases.json` | Math and economy curriculum phase definitions |
| `config/analogy_map.json` | Analogy mappings for inductive transfer |
| `config/threat_keywords.json` | Threat detection keywords for risk space |

Environment variables: `INGEST_API_KEY`, `ENABLE_SPACY_DEP_PARSER`, `SPACY_MODEL_NAME`.

---

## Tests

```bash
# Run all tests
python -m pytest tests/

# Run specific test file
python -m pytest tests/test_inductive_learner.py -v

# Run with coverage
python -m pytest tests/ --cov=core --cov=learning --cov=cognition
```

**389 tests** across 16 test files covering all modules.

---

## Project Structure

```
semantic-ai-system/
├── api.py                    # FastAPI application (55+ endpoints)
├── main.py                   # RL agent training, Q-learning
├── config.py                 # Central configuration
├── config/                   # JSON config files
│   ├── curriculum_phases.json
│   ├── analogy_map.json
│   └── threat_keywords.json
├── core/                     # Core engine modules
│   ├── parser.py, tms.py, knowledge_graph.py
│   ├── reasoning.py, space_relations.py
│   ├── symbolic_math.py, number_parser.py
│   ├── inductive_learner.py, numeracy.py
│   ├── data_loader.py, pdf_ingestion.py
│   ├── matrix_math.py, negation.py, conflict.py
│   └── economy_curriculum.py, primary_readiness.py
├── learning/                 # Learning modules
│   ├── jepa.py, curriculum.py
│   ├── concept_learning.py, rule_learning.py
│   └── online_learning.py
├── cognition/                # Cognitive architecture
│   ├── thought_loop.py, emotion_space.py
│   ├── layered_memory.py, conflict_resolver.py
│   ├── intent.py, multispace_embedding.py
│   └── __init__.py
├── memory/                   # Memory and persistence
│   ├── graph_store.py, embeddings.py
│   └── concept_space_embeddings.py
├── tests/                    # 389 tests
├── artifacts/                # Seed data, PDFs, demos
│   ├── seed_texts/           # 51 TXT seed files
│   ├── seed_pdfs/
│   └── training_pdfs/        # Generated training materials
├── dashboard/                # Next.js frontend
├── scripts/                  # Demo/validation scripts
└── docs/                     # Technical documentation
```

---

## License

MIT
