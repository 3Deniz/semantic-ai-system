# 🧠 Semantic AI Decision Engine

🚀 Interactive AI reasoning system with real-time graph exploration and explainable decision-making

![Python](https://img.shields.io/badge/Python-3.10-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green)
![Next.js](https://img.shields.io/badge/Next.js-Frontend-black)
![Status](https://img.shields.io/badge/status-active-success)
![AI](https://img.shields.io/badge/AI-Reinforcement%20Learning-purple)
[License](https://img.shields.io/badge/license-MIT-blue)

Multi-space cognitive AI with emotion, episodic memory, abstraction, and curriculum learning.

---

## 🎭 7 Cognitive Spaces

- risk, goal, memory, attention, self, semantic, **emotion**
- Each state is embedded into all 7 spaces simultaneously
- Emotion space: [fear, anger, sadness, surprise, calm] vector
- JEPA prediction surprise modulates emotion (surprise → fear/arousal)

---

## 📚 Episodic Memory

- Every decision stored with timestamp, action, reward, outcome, and **emotion vector**
- Retrieve: `GET /memory/episodic?limit=50`
- Emotional trend analysis: `GET /memory/emotional_trend?window=20`

---

## 🧠 Abstraction Layer

- **ConceptLearner** extracts patterns (e.g., "X causes flood")
- **RuleLearner** builds if-then rules from abstract patterns
- Abstraction level (0-1) computed from subject diversity
- Gated by curriculum stage 2 (**REASONING**)
- Promote abstractions: `POST /learn/abstraction/trigger`

---

## 🔄 JEPA → Emotion

- Prediction surprise modulates the emotion vector
- High surprise + high risk → increased fear
- Low surprise + low risk → increased calm
- Debug: `GET /debug/emotion/jepa`

---

## 📊 Dashboard (Next.js)

- **Emotion Timeline** – line chart of fear/anger/sadness/surprise/calm over episodes
- **Emotion Heatmap** – state×emotion intensity matrix
- **Abstraction Panel** – view abstract patterns & rules, trigger promotion
- **Episodic Memory Panel** – scrollable episode list with emotion labels
- **Graph Controls** – Pause/Resume auto-refresh, Refresh Now button
- **Node Selection Persistence** – selected node stays after graph refresh

---

## 🎓 Curriculum Learning (ACC)

6 phases: letters → digits → operations → real_numbers → calculus → logarithms

Each phase unlocks new capabilities. The system will not produce arithmetic or calculus results before the required phases are taught.

Phases can be taught via API:

```bash
curl -X POST http://127.0.0.1:8000/learn/curriculum/phase/letters
curl -X POST http://127.0.0.1:8000/learn/curriculum/phase/digits
curl -X POST http://127.0.0.1:8000/learn/curriculum/phase/operations
curl -X POST http://127.0.0.1:8000/learn/curriculum/phase/real_numbers
curl -X POST http://127.0.0.1:8000/learn/curriculum/phase/calculus
curl http://127.0.0.1:8000/learn/curriculum/status
```

---

## 🧪 API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/think` | POST | Run deliberative thought loop |
| `/semantic/recall` | GET | Multi-space knowledge recall with emotion edges |
| `/semantic/abstractions` | GET | List abstract patterns and rules |
| `/learn/abstraction/trigger` | POST | Promote abstractions to curriculum |
| `/memory/episodic` | GET | Retrieve episodic memory with emotion |
| `/memory/emotional_trend` | GET | Emotional trend over time |
| `/debug/emotion/jepa` | GET | Test JEPA→emotion mapping |
| `/learn/curriculum/phase/{phase}` | POST | Teach curriculum phase |
| `/semantic/concept/{concept}/embedding` | GET | Per-space concept embeddings |
| `/semantic/concept/{concept}/trace` | GET | Concept-centered cross-space trace |
| `/learn/primary/readiness` | GET | Primary-school readiness audit |
| `/learn/primary/drip/plan` | GET | Generate drip learning plan |
| `/learn/primary/drip/run` | POST | Run immediate drip feeding |

---

## 🏗 Architecture

AI Pipeline:

- RL Engine (Python)
- FastAPI (API Layer)
- Next.js Dashboard (React)
- Interactive Graph Visualization

Flow:

RL Engine → API → Dashboard → Graph

---

## 🛠 Tech Stack

### Backend
- Python
- FastAPI
- Custom RL Engine
- spaCy (optional advanced dependency parser)

### Frontend
- Next.js
- React
- Recharts
- react-force-graph

---

## ⚙️ Installation

### Backend

```bash
pip install -r requirements.txt
```

Optional: enable full dependency parser quality mode (recommended for academic PDFs):

```bash
pip install --break-system-packages spacy
pip install --break-system-packages https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
```

Feature flags:

```bash
export ENABLE_SPACY_DEP_PARSER=true
export SPACY_MODEL_NAME=en_core_web_sm
```

Run API:

```bash
uvicorn api:app --reload
```

### Frontend

```bash
cd dashboard
npm install
npm run dev
```

Open the dashboard at http://localhost:3000/dashboard

API docs at http://127.0.0.1:8000/docs

---

## 🌐 Usage

### Quick Flow: PDF → Learn → Observe

1. Upload a PDF via `POST /ingest/pdf` (stage=candidate).
2. Open dashboard Candidate Review and promote relevant triples.
3. Use Knowledge Recall query and space filters.
4. In Concept Explorer, click a concept symbol to inspect related concepts across spaces.
5. Track learning quality with score/confidence cards and space distribution chart.

### Curriculum-First Learning Flow

The math stack is curriculum-gated. Phases must be taught in order.

Useful endpoints:

```bash
curl -X POST http://127.0.0.1:8000/learn/curriculum/phase/letters?debug=true
curl http://127.0.0.1:8000/learn/curriculum/status
```

You can also teach via PDF import:

```bash
curl -X POST http://127.0.0.1:8000/ingest/pdf \
	-F "file=@artifacts/math_curriculum_demo/pdfs/01_letters.pdf;type=application/pdf" \
	-F 'stage=validated' \
	-F 'metadata={"curriculum_phase":"letters","teach_curriculum":true}'
```

### Economy Graph Learning Flow

Economy concepts are taught into existing semantic and curriculum layers:

1. foundations → demand_supply → elasticity → cost_revenue_profit → market_structures → macro_graphs → policy_shocks

```bash
curl -X POST http://127.0.0.1:8000/learn/curriculum/economy/phase/foundations
curl http://127.0.0.1:8000/learn/curriculum/economy/status
```

### Primary-School Readiness Audit

```bash
curl http://127.0.0.1:8000/learn/primary/readiness
curl "http://127.0.0.1:8000/learn/primary/drip/run?target_coverage=0.85&max_total_cycles=500"
```

### Debug Learning Traces

```bash
curl -X POST "http://127.0.0.1:8000/learn/curriculum/phase/letters?debug=true"
curl -X POST "http://127.0.0.1:8000/learn/numeracy/basic?debug=true"
```

### Validation Commands

```bash
python3 -m unittest tests/test_parser.py tests/test_api.py
python3 scripts/run_math_curriculum_demo.py
python3 scripts/run_time_seasons_demo.py
python3 scripts/run_avize_space_trace_demo.py
curl "http://127.0.0.1:8000/learn/bootstrap/plan"
```

Reset learning state:

```bash
curl -X POST "http://127.0.0.1:8000/learn/reset?confirm=true"
```

---

## 🔬 Example Representation

State:
('rain', 'flood')

Decision:
(state) → (state:action)

---

## 📈 Metrics

- Nodes → Unique states learned
- Edges → State-action relationships
- Inference/sec → Learning speed
- Conflicts → Ambiguous states
- Cycles → Potential loop patterns

---

## 🧠 Future Improvements

- Cycle detection & loop highlighting
- Explainable reasoning panel
- Risk heatmaps
- Real-time training updates
- Temporal inference analysis

---

## 💡 Highlights

This project goes beyond traditional ML models by providing a full AI observability and explainability platform with emotion, episodic memory, and curriculum-gated abstraction.

---

## 📄 License

MIT
