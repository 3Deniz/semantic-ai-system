"use client";
import dynamic from "next/dynamic";
import type { ReactNode } from "react";
import { useEffect, useEffectEvent, useState, useRef } from "react";
import type {
  ForceGraphMethods,
  LinkObject,
  NodeObject,
} from "react-force-graph-2d";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer
} from "recharts";

const ForceGraph2D = dynamic(
  () => import("react-force-graph-2d"),
  { ssr: false }
);

type GraphNode = { id: string };
type GraphLink = { source: string; target: string };
type RecallNode = { id: string; type: string; label: string };
type RecallEdge = {
  source: string;
  target: string;
  space: string;
  relation_type: string;
  confidence: number;
  provenance?: Record<string, unknown>;
};
type RecallFact = {
  triple: [string, string, string];
  confidence: number;
  score: number;
  ranking: {
    confidence: number;
    recency: number;
    frequency: number;
    source_quality: number;
  };
  provenance?: Record<string, unknown>;
};
type RecallResponse = {
  query: string;
  facts: RecallFact[];
  count: number;
  relations_graph: {
    spaces: string[];
    nodes: RecallNode[];
    edges: RecallEdge[];
  };
};

type ConceptSpaceEmbeddingEntry = {
  vector: number[];
  updates: number;
  last_confidence: number;
  updated_at: number;
  last_relation: string;
};

type ConceptSpaceDiff = {
  left_space: string;
  right_space: string;
  cosine_similarity: number;
  l1_distance: number;
};

type ConceptEmbeddingResponse = {
  concept: string;
  spaces: Record<string, ConceptSpaceEmbeddingEntry>;
  space_differences: ConceptSpaceDiff[];
};

type CurriculumStatus = {
  curriculum: {
    completed: string[];
    missing: string[];
    total_phases: number;
    progress: number;
    phase_metrics: Array<{
      phase: string;
      completed: boolean;
      missing_prerequisites: string[];
      knowledge_count: number;
    }>;
  };
  numeracy: {
    known_digits: string[];
    known_symbols: string[];
    known_concepts: string[];
  };
};
type CandidateItem = {
  id: string;
  triple: [string, string, string];
  confidence: number;
  provenance?: Record<string, unknown>;
  review_status: string;
};
type LearningDebugFact = {
  subject?: string;
  relation?: string;
  object?: string;
  confidence?: number;
  source_type?: string;
  source_document?: string;
};
type LearningDebugPayload = {
  mode?: string;
  phase?: string;
  curriculum_phase?: string;
  source_document?: string;
  stage?: string;
  metadata?: Record<string, unknown>;
  completed_before?: string[];
  completed_after?: string[];
  taught_facts?: LearningDebugFact[];
  phase_metrics?: Array<{
    phase: string;
    completed: boolean;
    missing_prerequisites: string[];
    knowledge_count: number;
  }>;
  files?: string[];
};
type ThoughtStep = {
  stage: string;
  detail: string;
  data?: unknown;
};

// ── Visual stepper for the thought pipeline ──────────────────────────────────
const CURRICULUM_PHASE_ORDER = ["letters", "digits", "operations", "real_numbers", "calculus", "logarithms"];

function getStageStyle(_stageName: string, index: number) {
  const goldenRatio = 0.618033988749895;
  const hue = (index * 360 * goldenRatio) % 360;
  return {
    dot: `hsl(${hue}, 70%, 55%)`,
    label: `hsl(${hue}, 70%, 75%)`,
    line: `hsl(${hue}, 40%, 30%)`,
  };
}

function ThoughtStepper({ steps }: { steps: ThoughtStep[] }) {
  return (
    <ol className="relative ml-2">
      {steps.map((step, i) => {
        const style = getStageStyle(step.stage, i);
        const isLast = i === steps.length - 1;
        return (
          <li key={i} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
                style={{ backgroundColor: style.dot }}
              >
                {i + 1}
              </span>
              {!isLast && (
                <span
                  className="mt-1 mb-1 w-px grow border-l-2 border-dashed"
                  style={{ borderColor: style.line }}
                />
              )}
            </div>
            <div className={`pb-4 ${isLast ? "pb-0" : ""}`}>
              <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: style.label }}>
                {step.stage}
              </div>
              <div className="mt-0.5 text-sm text-gray-300 leading-snug">{step.detail}</div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

type ThoughtTrace = {
  state: string[];
  spaces: Record<string, number[]>;
  memory_context: {
    working?: Record<string, unknown>;
    similar_failures?: Array<Record<string, unknown>>;
    long_term_patterns?: Array<Record<string, unknown>>;
  };
  intent: Array<Record<string, unknown>>;
  dominant_goal: string;
  tensions: Array<Record<string, unknown>>;
  resolution: string;
  candidates: Record<string, {
    score: number;
    q: number;
    sim: number;
    jepa: number;
    projected_reward: number;
  }>;
  action: string;
  confidence: number;
  jepa_surprise: number;
  explanation: string[];
  thought_path?: ThoughtStep[];
};

// ✅ CARD
type CardProps = { children: ReactNode };

const Card = ({ children }: CardProps) => (
  <div className="bg-[#0f172a] border border-[#1f2937] p-4 rounded-2xl shadow-xl backdrop-blur-md">
    {children}
  </div>
);

const CardContent = ({ children }: CardProps) => <div>{children}</div>;

export default function Dashboard() {
  const fgRef = useRef<ForceGraphMethods | undefined>(undefined);
  const hasBootstrappedRef = useRef(false);

  const [metrics, setMetrics] = useState({
    nodes: 0,
    edges: 0,
    inference: 0,
    conflicts: 0,
    cycles: 0
  });

  const [graph, setGraph] = useState({
    nodes: [] as NodeObject<GraphNode>[],
    links: [] as LinkObject<GraphNode, GraphLink>[]
  });

  const [selection, setSelection] = useState<null | {
    trace: ThoughtTrace;
  }>(null);
  const [recallQuery, setRecallQuery] = useState("flood");
  const [recallLoading, setRecallLoading] = useState(false);
  const [recallError, setRecallError] = useState("");
  const [selectedSpaces, setSelectedSpaces] = useState<string[]>([
    "risk",
    "goal",
    "memory",
    "attention",
    "self",
    "semantic",
  ]);
  const [recallData, setRecallData] = useState<RecallResponse | null>(null);
  const [selectedConcept, setSelectedConcept] = useState<string>("");
  const [conceptEmbedding, setConceptEmbedding] = useState<ConceptEmbeddingResponse | null>(null);
  const [conceptEmbeddingLoading, setConceptEmbeddingLoading] = useState(false);
  const [relationDirection, setRelationDirection] = useState<"all" | "incoming" | "outgoing">("all");
  const [reviewQueue, setReviewQueue] = useState<CandidateItem[]>([]);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [curriculumStatus, setCurriculumStatus] = useState<CurriculumStatus | null>(null);
  const [curriculumLoading, setCurriculumLoading] = useState(false);
  const [learningDebug, setLearningDebug] = useState<LearningDebugPayload | null>(null);
  const [learningDebugLoading, setLearningDebugLoading] = useState(false);
  const [learningDebugPhase, setLearningDebugPhase] = useState<string>("letters");
  const [episodicMemory, setEpisodicMemory] = useState<Array<Record<string, unknown>>>([]);
  const [emotionalTrend, setEmotionalTrend] = useState<{ avg_vector: number[]; count: number } | null>(null);
  const [abstractions, setAbstractions] = useState<{ abstract_patterns: Array<Record<string, unknown>>; abstract_rules: Array<Record<string, unknown>> } | null>(null);
  const [abstractionLoading, setAbstractionLoading] = useState(false);
  const [emotionTimelineData, setEmotionTimelineData] = useState<Array<Record<string, unknown>>>([]);
  const [heatmapData, setHeatmapData] = useState<Array<{ state: string; fear: number; anger: number; sadness: number; surprise: number; calm: number }>>([]);
  const [heatmapSelected, setHeatmapSelected] = useState<{ state: string; emotion: string } | null>(null);
  const [heatmapEpisodes, setHeatmapEpisodes] = useState<Array<Record<string, unknown>>>([]);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const ALL_SPACES = ["risk", "goal", "memory", "attention", "self", "semantic", "arithmetic", "calculus", "curriculum", "emotion"];

  const formatState = (value: string) => (value.includes(":") ? value.split(":")[0] : value);

  const fetchAll = () => {
    // ✅ METRICS SAFE
    fetch("http://127.0.0.1:8000/metrics")
      .then((res) => res.json())
      .then((data) => {
        if (!data || typeof data !== "object") return;
        setMetrics({
          nodes: data.nodes || 0,
          edges: data.edges || 0,
          inference: data.inference || 0,
          conflicts: data.conflicts || 0,
          cycles: data.cycles || 0
        });
      })
      .catch((e) => console.error("METRICS ERROR:", e));

    // ✅ GRAPH SAFE (CRASH FIX)
    fetch("http://127.0.0.1:8000/graph")
      .then((res) => res.json())
      .then((data) => {
        if (!data || typeof data !== "object") {
          setGraph({ nodes: [], links: [] });
          return;
        }

        const safeNodes = Array.isArray(data.nodes) ? data.nodes : [];
        const safeEdges = Array.isArray(data.edges)
          ? data.edges.filter(
              (e: unknown): e is { source: string; target: string } =>
                typeof e === "object" &&
                e !== null &&
                typeof (e as { source?: unknown }).source === "string" &&
                typeof (e as { target?: unknown }).target === "string"
            )
          : [];

        const nodes = safeNodes
          .filter((n: unknown): n is string => typeof n === "string")
          .map((n: string) => ({ id: n }));
        const links = safeEdges.map((e: { source: string; target: string }) => ({
          source: e.source,
          target: e.target
        })) as LinkObject<GraphNode, GraphLink>[];

        setGraph({ nodes, links });
        if (selectedNodeId) {
          const stillExists = nodes.some((n: GraphNode) => n.id === selectedNodeId);
          if (!stillExists) { setSelectedNodeId(null); setSelection(null); }
        }
      })
      .catch((e) => {
        console.error("GRAPH ERROR:", e);
        setGraph({ nodes: [], links: [] });
      });

    };

  const fetchRecall = (options?: { query?: string; includeAllSpaces?: boolean; maxDepth?: number; preserveSelectedConcept?: boolean }) => {
    const query = (options?.query ?? recallQuery).trim();
    if (!query) return;
    setRecallLoading(true);
    setRecallError("");

    const includeSpaces = options?.includeAllSpaces ? ALL_SPACES : selectedSpaces;
    const maxDepth = options?.maxDepth ?? 2;

    const params = new URLSearchParams({
      query,
      include_spaces: includeSpaces.join(","),
      max_edges: "250",
      max_depth: String(maxDepth),
    });

    fetch(`http://127.0.0.1:8000/semantic/recall?${params.toString()}`)
      .then((res) => {
        if (!res.ok) throw new Error(`recall failed: ${res.status}`);
        return res.json();
      })
      .then((data) => {
        const typed = data as RecallResponse;
        setRecallData(typed);

        const firstConcept =
          typed?.relations_graph?.nodes?.[0]?.label ||
          typed?.facts?.[0]?.triple?.[0] ||
          "";
        if (firstConcept && !options?.preserveSelectedConcept) {
          const normalizedFirstConcept = String(firstConcept).toLowerCase();
          setSelectedConcept(normalizedFirstConcept);
          fetchConceptEmbedding(normalizedFirstConcept);
        }
      })
      .catch((e) => {
        setRecallError(String(e));
      })
      .finally(() => {
        setRecallLoading(false);
      });
  };

  const fetchReviewQueue = () => {
    setReviewLoading(true);
    fetch("http://127.0.0.1:8000/ingest/candidates")
      .then((res) => res.json())
      .then((data) => {
        const candidates = Array.isArray(data?.candidates) ? data.candidates : [];
        setReviewQueue(candidates as CandidateItem[]);
      })
      .catch(() => {
        setReviewQueue([]);
      })
      .finally(() => setReviewLoading(false));
  };

  const fetchEpisodicMemory = () => {
    fetch("http://127.0.0.1:8000/memory/episodic?limit=20")
      .then((res) => res.json())
      .then((data) => {
        if (data && Array.isArray(data.episodes)) {
          setEpisodicMemory(data.episodes);
        }
      })
      .catch(() => setEpisodicMemory([]));
  };

  const fetchEmotionBundle = () => {
    fetch("http://127.0.0.1:8000/memory/emotional_trend?n=20")
      .then((res) => res.json())
      .then((data) => {
        if (!data || typeof data !== "object") {
          setEmotionalTrend(null);
          setHeatmapData([]);
          setEmotionTimelineData([]);
          return;
        }

        if (Array.isArray(data.avg_vector)) {
          setEmotionalTrend(data);
          const labels = ["fear", "anger", "sadness", "surprise", "calm"];
          const row: { state: string; fear: number; anger: number; sadness: number; surprise: number; calm: number } = {
            state: "all",
            fear: 0,
            anger: 0,
            sadness: 0,
            surprise: 0,
            calm: 0,
          };
          labels.forEach((l, i) => {
            (row as unknown as Record<string, number>)[l] = data.avg_vector[i] || 0;
          });
          setHeatmapData([row]);
        } else {
          setEmotionalTrend(null);
          setHeatmapData([]);
        }

        if (Array.isArray(data.timeline)) {
          setEmotionTimelineData(data.timeline);
        } else {
          setEmotionTimelineData([]);
        }
      })
      .catch(() => {
        setEmotionalTrend(null);
        setHeatmapData([]);
        setEmotionTimelineData([]);
      });
  };

  const fetchEmotionalTrend = () => {
    fetchEmotionBundle();
  };

  const fetchAbstractions = () => {
    setAbstractionLoading(true);
    fetch("http://127.0.0.1:8000/semantic/abstractions")
      .then((res) => res.json())
      .then((data) => setAbstractions(data))
      .catch(() => setAbstractions(null))
      .finally(() => setAbstractionLoading(false));
  };

  const triggerAbstraction = () => {
    setAbstractionLoading(true);
    fetch("http://127.0.0.1:8000/learn/abstraction/trigger", { method: "POST" })
      .then(() => fetchAbstractions())
      .catch(() => setAbstractionLoading(false));
  };

  const fetchHeatmapData = () => {
    fetchEmotionBundle();
  };

  const fetchEmotionTimeline = () => {
    fetchEmotionBundle();
  };

  const fetchCurriculumStatus = () => {
    setCurriculumLoading(true);
    fetch("http://127.0.0.1:8000/learn/curriculum/status")
      .then((res) => res.json())
      .then((data) => {
        if (data && data.curriculum) {
          setCurriculumStatus(data as CurriculumStatus);
        }
      })
      .catch(() => {
        setCurriculumStatus(null);
      })
      .finally(() => setCurriculumLoading(false));
  };

  const fetchLearningDebug = (mode: "numeracy" | "curriculum") => {
    setLearningDebugLoading(true);
    const endpoint = mode === "numeracy"
      ? "http://127.0.0.1:8000/learn/numeracy/basic?debug=true"
      : `http://127.0.0.1:8000/learn/curriculum/phase/${learningDebugPhase}?debug=true`;

    fetch(endpoint, { method: "POST" })
      .then((res) => res.json())
      .then((data) => {
        setLearningDebug((data?.debug || null) as LearningDebugPayload | null);
      })
      .catch(() => {
        setLearningDebug(null);
      })
      .finally(() => setLearningDebugLoading(false));
  };

  const fetchConceptEmbedding = (concept: string) => {
    const normalized = concept.trim().toLowerCase();
    if (!normalized) {
      setConceptEmbedding(null);
      return;
    }
    setConceptEmbeddingLoading(true);
    fetch(`http://127.0.0.1:8000/semantic/concept/${encodeURIComponent(normalized)}/embedding`)
      .then((res) => {
        if (!res.ok) throw new Error(`concept embedding failed: ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setConceptEmbedding(data as ConceptEmbeddingResponse);
      })
      .catch(() => {
        setConceptEmbedding(null);
      })
      .finally(() => setConceptEmbeddingLoading(false));
  };

  const focusConcept = (concept: string) => {
    const normalized = concept.trim().toLowerCase();
    if (!normalized) return;
    setSelectedConcept(normalized);
    setRecallQuery(normalized);
    fetchConceptEmbedding(normalized);
    fetchRecall({ query: normalized, includeAllSpaces: true, maxDepth: 3, preserveSelectedConcept: true });
  };

  const toggleSpace = (space: string) => {
    setSelectedSpaces((prev) => {
      if (prev.includes(space)) {
        return prev.filter((s) => s !== space);
      }
      return [...prev, space];
    });
  };

  const promoteCandidate = (candidateId: string) => {
    fetch(`http://127.0.0.1:8000/ingest/candidates/${candidateId}/promote`, {
      method: "POST",
    })
      .then(() => fetchReviewQueue())
      .catch((e) => console.error("PROMOTE ERROR", e));
  };

  const rejectCandidate = (candidateId: string) => {
    fetch(`http://127.0.0.1:8000/ingest/candidates/${candidateId}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "dashboard_review" }),
    })
      .then(() => fetchReviewQueue())
      .catch((e) => console.error("REJECT ERROR", e));
  };

  const bootstrapKnowledgePanels = useEffectEvent(() => {
    fetchRecall();
    fetchReviewQueue();
    fetchCurriculumStatus();
    fetchEpisodicMemory();
    fetchAbstractions();
    fetchEmotionBundle();
  });

  useEffect(() => {
    fetchAll();
    const interval = setInterval(() => {
      if (autoRefresh) fetchAll();
    }, 12000);
    return () => { clearInterval(interval); };
  }, [autoRefresh]);

  useEffect(() => {
    if (hasBootstrappedRef.current) return;
    hasBootstrappedRef.current = true;
    bootstrapKnowledgePanels();
  }, []);

  const chartData = [
    { name: "Inference", value: metrics.inference },
    { name: "Conflicts", value: metrics.conflicts },
    { name: "Cycles", value: metrics.cycles }
  ];

  const normalizedConcept = selectedConcept.trim().toLowerCase();
  const recallEdges = recallData?.relations_graph?.edges || [];
  const recallFacts = recallData?.facts || [];

  const spaceEdgeDistribution = Object.entries(
    recallEdges.reduce((acc, edge) => {
      const space = edge.space || "unknown";
      acc[space] = (acc[space] || 0) + 1;
      return acc;
    }, {} as Record<string, number>)
  ).map(([space, count]) => ({ space, count }));

  const averageFactScore = recallFacts.length
    ? recallFacts.reduce((sum, item) => sum + Number(item.score || 0), 0) / recallFacts.length
    : 0;

  const averageEdgeConfidence = recallEdges.length
    ? recallEdges.reduce((sum, edge) => sum + Number(edge.confidence || 0), 0) / recallEdges.length
    : 0;

  const curriculumPhaseChartData = (curriculumStatus?.curriculum.phase_metrics || []).map((item) => ({
    phase: item.phase,
    knowledge: item.knowledge_count,
    completed: item.completed ? 1 : 0,
  }));

  const conceptUniverse = Array.from(
    new Set(
      [
        ...(recallData?.relations_graph?.nodes || []).flatMap((n) => [n.label, n.id]),
        ...recallEdges.flatMap((e) => [e.source, e.target]),
      ]
        .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
        .map((item) => item.toLowerCase())
    )
  ).sort();

  const relatedBySpace = recallEdges.reduce((acc, edge) => {
    const source = String(edge.source || "").toLowerCase();
    const target = String(edge.target || "").toLowerCase();
    if (!normalizedConcept || (source !== normalizedConcept && target !== normalizedConcept)) {
      return acc;
    }
    const related = source === normalizedConcept ? String(edge.target) : String(edge.source);
    const space = edge.space || "unknown";
    if (!acc[space]) {
      acc[space] = [];
    }
    const direction = source === normalizedConcept ? "out" : "in";
    if (relationDirection === "incoming" && direction !== "in") {
      return acc;
    }
    if (relationDirection === "outgoing" && direction !== "out") {
      return acc;
    }
    acc[space].push({
      concept: related,
      relation: edge.relation_type,
      confidence: Number(edge.confidence || 0),
      direction,
    });
    return acc;
  }, {} as Record<string, Array<{ concept: string; relation: string; confidence: number; direction: "in" | "out" }>>);

  const miniGraphLinks = Object.entries(relatedBySpace)
    .flatMap(([space, links]) =>
      links.map((link) => ({
        space,
        concept: link.concept,
        relation: link.relation,
        confidence: link.confidence,
        direction: link.direction,
      }))
    )
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, 12);

  const handleNodeClick = (node: NodeObject) => {
    const nodeId = String(node.id);
    setSelectedNodeId(nodeId);
    const state = formatState(nodeId);

    fetch("http://127.0.0.1:8000/think", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ state }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (!data || typeof data !== "object") return;
        setSelection({
          trace: {
            state: Array.isArray(data.state) ? data.state : [],
            spaces: data.spaces || {},
            memory_context: data.memory_context || {},
            intent: Array.isArray(data.intent) ? data.intent : [],
            dominant_goal: data.dominant_goal || "task_completion",
            tensions: Array.isArray(data.tensions) ? data.tensions : [],
            resolution: data.resolution || "",
            candidates: data.candidates || {},
            action: data.action || "unknown",
            confidence: typeof data.confidence === "number" ? data.confidence : 0,
            jepa_surprise: typeof data.jepa_surprise === "number" ? data.jepa_surprise : 0,
            explanation: Array.isArray(data.explanation) ? data.explanation : [],
            thought_path: Array.isArray(data.thought_path) ? data.thought_path : [],
          },
        });
      })
      .catch((e) => console.error("EXPLAIN ERROR:", e));
  };

  return (
    <div className="p-6 grid grid-cols-1 md:grid-cols-3 gap-6 bg-[#020617] min-h-screen text-white">

      {/* ✅ METRICS */}
      {[
        { title: "Graph Nodes", value: metrics.nodes, color: "text-cyan-400" },
        { title: "Active Edges", value: metrics.edges, color: "text-purple-400" },
        { title: "Inference/sec", value: metrics.inference, color: "text-pink-400" }
      ].map((item, i) => (
        <Card key={i}>
          <CardContent>
            <p className="text-gray-400 text-sm">{item.title}</p>
            <h2 className={`text-4xl font-bold ${item.color}`}>
              {item.value}
            </h2>
          </CardContent>
        </Card>
      ))}

      {/* ✅ CHART */}
      <div className="md:col-span-2">
        <Card>
          <CardContent>
            <h2 className="text-xl mb-3">Reasoning Metrics</h2>

            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={chartData}>
                <XAxis stroke="#94a3b8" tick={{ fill: "#e2e8f0" }} dataKey="name" />
                <YAxis stroke="#94a3b8" tick={{ fill: "#e2e8f0" }} />
                <Tooltip contentStyle={{ backgroundColor: "#020617" }} />
                <Bar dataKey="value" fill="#7c3aed" />
              </BarChart>
            </ResponsiveContainer>

          </CardContent>
        </Card>
      </div>

      {/* ✅ STATUS */}
      <Card>
        <CardContent>
          <h2 className="text-lg mb-2">Engine Status</h2>

          <div className="flex items-center gap-2 text-emerald-400 text-lg font-semibold">
            <div className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse"></div>
            {metrics.nodes > 0 ? "Running" : "Disconnected"}
          </div>

          <p className="text-gray-400 mt-3 text-sm">
            Live reasoning engine active
          </p>
        </CardContent>
      </Card>

      {/* ✅ GRAPH */}
      <div className="md:col-span-2">
        <Card>
          <CardContent>
            <div className="flex items-center mb-3">
              <h2 className="text-xl">🧠 AI State Graph</h2>
              <div className="ml-auto flex gap-2">
                <button onClick={() => setAutoRefresh(!autoRefresh)} className={`px-3 py-1 rounded text-sm font-medium ${autoRefresh ? "bg-emerald-600" : "bg-amber-600"}`}>
                  {autoRefresh ? "⏸ Pause Auto-Refresh" : "▶ Resume Auto-Refresh"}
                </button>
                <button onClick={() => { fetchAll(); bootstrapKnowledgePanels(); }} className="px-3 py-1 rounded text-sm font-medium bg-cyan-600">
                  🔄 Refresh Now
                </button>
              </div>
            </div>

            <div className="h-[520px] bg-black rounded">
              <ForceGraph2D
                ref={fgRef}
                graphData={graph}
                nodeRelSize={8}
                nodeLabel={(n) => String(n.id)}

                nodeColor={(node) => {
                  if (node?.id === undefined || node?.id === null) return "#888";
                  const nodeId = String(node.id);

                  if (nodeId.includes("crisis")) return "#ff0040";
                  if (nodeId.includes("collapse")) return "#fb923c";
                  if (nodeId.includes("damage")) return "#fde047";
                  if (nodeId.includes("flood")) return "#22d3ee";
                  return "#34d399";
                }}

                linkColor={(link: any) => {
                  const confidence = (link as any).confidence ?? 0.5;
                  const r = 71 + Math.floor(confidence * 184);
                  const g = 85 + Math.floor(confidence * 170);
                  const b = 105 + Math.floor(confidence * 150);
                  return `rgb(${r}, ${g}, ${b})`;
                }}
                linkWidth={(link: any) => {
                  const confidence = (link as any).confidence ?? 0.5;
                  return 1 + confidence * 2;
                }}
                linkDirectionalParticles={(link: any) => {
                  const confidence = (link as any).confidence ?? 0.5;
                  return confidence > 0.8 ? 2 : 0;
                }}
                linkDirectionalParticleSpeed={0.02}

                cooldownTicks={100}

                onEngineStop={() => fgRef.current?.zoomToFit(400)}

                backgroundColor="#000"

                onNodeClick={handleNodeClick}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ✅ REASON PANEL */}
      <Card>
        <CardContent>
          <h2 className="text-lg text-indigo-300 mb-3">🧠 Reasoning</h2>

          {selection ? (
            <>
              {/* STATE */}
              <div className="text-sm text-gray-400 mb-1">STATE</div>
              <div className="bg-black p-2 rounded text-xs break-all mb-3">
                {selection.trace.state.join(", ")}
              </div>

              {/* THOUGHT PATH – visual stepper */}
              <div className="text-sm text-gray-400 mb-2">THOUGHT PATH</div>
              <div className="mb-4">
                <ThoughtStepper steps={selection.trace.thought_path ?? []} />
              </div>

              {/* WHY */}
              <div className="text-sm text-gray-400 mb-1">WHY</div>
              <ul className="text-sm space-y-1 mb-3">
                {selection.trace.explanation.map((e, i) => (
                  <li key={i} className="text-cyan-300">• {e}</li>
                ))}
              </ul>

              {/* INTENT */}
              <div className="text-sm text-gray-400 mb-1">INTENT</div>
              <div className="space-y-1 mb-3 text-sm">
                <div className="bg-[#020617] px-2 py-1 rounded">
                  Dominant goal: {selection.trace.dominant_goal}
                </div>
                {selection.trace.intent.map((item, i) => (
                  <div key={i} className="bg-black px-2 py-1 rounded text-gray-300">
                    {JSON.stringify(item)}
                  </div>
                ))}
              </div>

              {/* MEMORY */}
              <div className="text-sm text-gray-400 mb-1">MEMORY CONTEXT</div>
              <pre className="space-y-1 mb-3 text-xs bg-black px-2 py-2 rounded overflow-auto">
                {JSON.stringify(selection.trace.memory_context, null, 2)}
              </pre>

              {/* RULE SCORES */}
              <div className="text-sm text-gray-400 mb-1">CANDIDATES</div>
              <div className="space-y-1 mb-3 text-sm">
                {Object.entries(selection.trace.candidates || {}).map(([a, s]) => (
                  <div key={a} className="bg-[#020617] px-2 py-1 rounded">
                    <div className="flex justify-between">
                      <span>{a}</span>
                      <span>{Number(s.score).toFixed(2)}</span>
                    </div>
                    <div className="text-xs text-gray-400">
                      q={Number(s.q).toFixed(2)} sim={Number(s.sim).toFixed(2)} jepa={Number(s.jepa).toFixed(2)} projected={Number(s.projected_reward).toFixed(2)}
                    </div>
                  </div>
                ))}
              </div>

              {/* SIMULATION / DECISION */}
              <div className="text-sm text-gray-400 mb-1">DECISION</div>
              <div className="space-y-1 text-sm bg-black px-2 py-2 rounded">
                <div>Action: <span className="text-yellow-300">{selection.trace.action}</span></div>
                <div>Confidence: {selection.trace.confidence.toFixed(2)}</div>
                <div>JEPA surprise: {selection.trace.jepa_surprise.toFixed(2)}</div>
                <div className="text-gray-400 text-xs">{selection.trace.resolution}</div>
              </div>
            </>
          ) : (
            <p className="text-gray-500">
              Click a node to analyze AI reasoning
            </p>
          )}
        </CardContent>
      </Card>

      {/* ✅ KNOWLEDGE RECALL */}
      <div className="md:col-span-2">
        <Card>
          <CardContent>
            <h2 className="text-xl mb-3">Knowledge Recall</h2>
            <div className="flex flex-col gap-3">
              <div className="flex gap-2">
                <input
                  value={recallQuery}
                  onChange={(e) => setRecallQuery(e.target.value)}
                  placeholder="Search learned knowledge"
                  className="flex-1 rounded bg-black border border-slate-700 px-3 py-2 text-sm"
                />
                <button
                  onClick={() => fetchRecall()}
                  className="rounded bg-cyan-600 hover:bg-cyan-500 px-3 py-2 text-sm font-semibold"
                  disabled={recallLoading}
                >
                  {recallLoading ? "Loading..." : "Recall"}
                </button>
              </div>

              <div className="flex flex-wrap gap-2">
                {ALL_SPACES.map((space) => (
                  <button
                    key={space}
                    onClick={() => toggleSpace(space)}
                    className={`px-2 py-1 rounded text-xs border ${selectedSpaces.includes(space)
                      ? "bg-emerald-700 border-emerald-500"
                      : "bg-slate-900 border-slate-700"
                    }`}
                  >
                    {space}
                  </button>
                ))}
              </div>

              {recallError ? <div className="text-red-400 text-sm">{recallError}</div> : null}

              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                <div className="rounded border border-slate-800 bg-black p-2">
                  <div className="text-gray-400">Facts</div>
                  <div className="text-cyan-300 text-lg font-semibold">{recallFacts.length}</div>
                </div>
                <div className="rounded border border-slate-800 bg-black p-2">
                  <div className="text-gray-400">Edges</div>
                  <div className="text-cyan-300 text-lg font-semibold">{recallEdges.length}</div>
                </div>
                <div className="rounded border border-slate-800 bg-black p-2">
                  <div className="text-gray-400">Avg fact score</div>
                  <div className="text-cyan-300 text-lg font-semibold">{averageFactScore.toFixed(3)}</div>
                </div>
                <div className="rounded border border-slate-800 bg-black p-2">
                  <div className="text-gray-400">Avg edge conf</div>
                  <div className="text-cyan-300 text-lg font-semibold">{averageEdgeConfidence.toFixed(3)}</div>
                </div>
              </div>

              <div className="rounded border border-slate-800 bg-black p-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-sm text-gray-300">Curriculum Progress</div>
                  <button
                    onClick={fetchCurriculumStatus}
                    className="rounded bg-slate-700 hover:bg-slate-600 px-2 py-1 text-[11px]"
                    disabled={curriculumLoading}
                  >
                    {curriculumLoading ? "Refreshing..." : "Refresh"}
                  </button>
                </div>
                {curriculumStatus ? (
                  <>
                    <div className="text-xs text-cyan-300 mb-1">
                      Progress: {(curriculumStatus.curriculum.progress * 100).toFixed(0)}% ({curriculumStatus.curriculum.completed.length}/{curriculumStatus.curriculum.total_phases})
                    </div>
                    <div className="w-full h-2 bg-slate-900 rounded mb-2">
                      <div
                        className="h-2 bg-cyan-500 rounded"
                        style={{ width: `${Math.max(0, Math.min(100, curriculumStatus.curriculum.progress * 100))}%` }}
                      />
                    </div>
                    <div className="text-[11px] text-emerald-300 mb-1">Completed: {curriculumStatus.curriculum.completed.join(", ") || "-"}</div>
                    <div className="text-[11px] text-amber-300 mb-1">Missing: {curriculumStatus.curriculum.missing.join(", ") || "-"}</div>
                    <div className="text-[11px] text-slate-400">
                      Digits={curriculumStatus.numeracy.known_digits.length} Symbols={curriculumStatus.numeracy.known_symbols.length} Concepts={curriculumStatus.numeracy.known_concepts.length}
                    </div>
                    <div className="mt-3 rounded border border-slate-800 bg-[#020617] p-2">
                      <div className="text-[11px] text-gray-300 mb-2">Phase-by-Phase Knowledge Growth</div>
                      <ResponsiveContainer width="100%" height={180}>
                        <BarChart data={curriculumPhaseChartData}>
                          <XAxis stroke="#94a3b8" tick={{ fill: "#e2e8f0", fontSize: 10 }} dataKey="phase" />
                          <YAxis stroke="#94a3b8" tick={{ fill: "#e2e8f0", fontSize: 10 }} />
                          <Tooltip contentStyle={{ backgroundColor: "#020617" }} />
                          <Bar dataKey="knowledge" fill="#f59e0b" />
                        </BarChart>
                      </ResponsiveContainer>
                      <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px]">
                        {(curriculumStatus.curriculum.phase_metrics || []).map((item) => (
                          <div key={item.phase} className="rounded border border-slate-700 px-2 py-1">
                            <div className="flex items-center justify-between">
                              <span className="text-cyan-300">{item.phase}</span>
                              <span className={item.completed ? "text-emerald-300" : "text-amber-300"}>
                                {item.completed ? "mastered" : "pending"}
                              </span>
                            </div>
                            <div className="text-slate-400">knowledge={item.knowledge_count}</div>
                            <div className="text-slate-500 truncate">
                              prereq_missing={item.missing_prerequisites.join(", ") || "-"}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="text-xs text-gray-500">No curriculum status available.</div>
                )}
              </div>

              <div className="rounded border border-slate-800 bg-black p-3">
                <div className="flex items-center justify-between mb-2 gap-2">
                  <div>
                    <div className="text-sm text-gray-300">Learning Debug Timeline</div>
                    <div className="text-[11px] text-gray-500">Inspect how curriculum and numeracy learning steps were recorded.</div>
                  </div>
                  <button
                    onClick={() => fetchLearningDebug("numeracy")}
                    className="rounded bg-slate-700 hover:bg-slate-600 px-2 py-1 text-[11px]"
                    disabled={learningDebugLoading}
                  >
                    {learningDebugLoading ? "Loading..." : "Load Debug"}
                  </button>
                </div>

                <div className="flex flex-wrap items-center gap-2 mb-3 text-[11px]">
                  <span className="text-gray-400">Phase:</span>
                  {CURRICULUM_PHASE_ORDER.map((phase) => (
                    <button
                      key={phase}
                      onClick={() => setLearningDebugPhase(phase)}
                      className={`rounded border px-2 py-1 ${learningDebugPhase === phase
                        ? "bg-cyan-700 border-cyan-500 text-white"
                        : "bg-slate-900 border-slate-700 text-gray-300"
                      }`}
                    >
                      {phase}
                    </button>
                  ))}
                  <button
                    onClick={() => fetchLearningDebug("curriculum")}
                    className="rounded bg-emerald-700 hover:bg-emerald-600 px-2 py-1 text-white"
                    disabled={learningDebugLoading}
                  >
                    Debug selected phase
                  </button>
                </div>

                {learningDebug ? (
                  <div className="space-y-3">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px]">
                      <div className="rounded border border-slate-700 px-2 py-2">
                        <div className="text-cyan-300">Mode</div>
                        <div className="text-gray-200">{learningDebug.mode || "-"}</div>
                      </div>
                      <div className="rounded border border-slate-700 px-2 py-2">
                        <div className="text-cyan-300">Phase</div>
                        <div className="text-gray-200">{learningDebug.phase || learningDebug.curriculum_phase || "-"}</div>
                      </div>
                      <div className="rounded border border-slate-700 px-2 py-2">
                        <div className="text-cyan-300">Completed Before</div>
                        <div className="text-gray-200">{(learningDebug.completed_before || []).join(", ") || "-"}</div>
                      </div>
                      <div className="rounded border border-slate-700 px-2 py-2">
                        <div className="text-cyan-300">Completed After</div>
                        <div className="text-gray-200">{(learningDebug.completed_after || []).join(", ") || "-"}</div>
                      </div>
                    </div>

                    <div className="rounded border border-slate-700 p-2">
                      <div className="text-[11px] text-gray-300 mb-2">Taught Facts Timeline</div>
                      <ol className="space-y-2 text-[11px] max-h-56 overflow-auto">
                        {(learningDebug.taught_facts || []).map((fact, index) => (
                          <li key={`${fact.subject}-${fact.relation}-${fact.object}-${index}`} className="rounded border border-slate-800 bg-[#020617] px-2 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-cyan-300">Step {index + 1}</span>
                              <span className="text-gray-500">{fact.source_type || "curriculum"}</span>
                            </div>
                            <div className="text-gray-200 mt-1">
                              {fact.subject} -{fact.relation}-&gt; {fact.object}
                            </div>
                            <div className="text-gray-500 mt-1">
                              confidence={Number(fact.confidence ?? 0).toFixed(2)} source={fact.source_document || "-"}
                            </div>
                          </li>
                        ))}
                      </ol>
                    </div>

                    <div className="rounded border border-slate-700 p-2">
                      <div className="text-[11px] text-gray-300 mb-2">Phase Metrics Snapshot</div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px]">
                        {(learningDebug.phase_metrics || []).map((item) => (
                          <div key={item.phase} className="rounded border border-slate-800 px-2 py-1">
                            <div className="flex items-center justify-between">
                              <span className="text-emerald-300">{item.phase}</span>
                              <span className={item.completed ? "text-emerald-300" : "text-amber-300"}>
                                {item.completed ? "done" : "pending"}
                              </span>
                            </div>
                            <div className="text-slate-400">knowledge={item.knowledge_count}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="text-xs text-gray-500">Click Load Debug to inspect the latest learning trace.</div>
                )}
              </div>

              <div className="rounded border border-slate-800 bg-black p-3">
                <div className="text-sm text-gray-300 mb-2">Space Edge Distribution</div>
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={spaceEdgeDistribution}>
                    <XAxis stroke="#94a3b8" tick={{ fill: "#e2e8f0", fontSize: 11 }} dataKey="space" />
                    <YAxis stroke="#94a3b8" tick={{ fill: "#e2e8f0", fontSize: 11 }} />
                    <Tooltip contentStyle={{ backgroundColor: "#020617" }} />
                    <Bar dataKey="count" fill="#06b6d4" />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="rounded border border-slate-800 bg-black p-3">
                <div className="text-sm text-gray-300 mb-2">Concept Explorer (click a concept symbol)</div>
                <div className="flex items-center gap-2 mb-3 text-xs">
                  <span className="text-gray-400">Direction:</span>
                  {[
                    { key: "all", label: "All" },
                    { key: "incoming", label: "Incoming" },
                    { key: "outgoing", label: "Outgoing" },
                  ].map((option) => (
                    <button
                      key={option.key}
                      onClick={() => setRelationDirection(option.key as "all" | "incoming" | "outgoing")}
                      className={`rounded px-2 py-1 border ${relationDirection === option.key
                        ? "bg-emerald-700 border-emerald-500 text-white"
                        : "bg-slate-900 border-slate-700 text-gray-300"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <div className="flex flex-wrap gap-2 mb-3 max-h-28 overflow-auto">
                  {conceptUniverse.slice(0, 120).map((concept) => (
                    <button
                      key={concept}
                      onClick={() => focusConcept(concept)}
                      className={`rounded px-2 py-1 text-xs border ${normalizedConcept === concept
                        ? "bg-cyan-700 border-cyan-500 text-white"
                        : "bg-slate-900 border-slate-700 text-gray-200"
                      }`}
                    >
                      {concept}
                    </button>
                  ))}
                </div>
                <div className="text-xs text-gray-400 mb-2">
                  Selected: <span className="text-cyan-300">{normalizedConcept || "-"}</span>
                </div>

                <div className="rounded border border-slate-700 p-2 mb-3 bg-[#020617]">
                  <div className="text-xs text-gray-300 mb-2">Space Embedding Card</div>
                  {conceptEmbeddingLoading ? (
                    <div className="text-xs text-gray-500">Loading concept embeddings...</div>
                  ) : !conceptEmbedding || Object.keys(conceptEmbedding.spaces || {}).length === 0 ? (
                    <div className="text-xs text-gray-500">No persistent per-space embedding for selected concept yet.</div>
                  ) : (
                    <div className="space-y-2">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px]">
                        {Object.entries(conceptEmbedding.spaces)
                          .sort((a, b) => b[1].updates - a[1].updates)
                          .map(([space, payload]) => (
                            <div key={space} className="rounded border border-slate-800 px-2 py-1">
                              <div className="flex items-center justify-between">
                                <span className="text-cyan-300">{space}</span>
                                <span className="text-gray-400">updates={payload.updates}</span>
                              </div>
                              <div className="text-gray-400">last_conf={Number(payload.last_confidence || 0).toFixed(3)}</div>
                            </div>
                          ))}
                      </div>

                      <div className="rounded border border-slate-800 p-2">
                        <div className="text-[11px] text-gray-300 mb-1">Space Similarity Matrix (top differences)</div>
                        <div className="max-h-24 overflow-auto space-y-1 text-[11px]">
                          {(conceptEmbedding.space_differences || [])
                            .sort((a, b) => a.cosine_similarity - b.cosine_similarity)
                            .slice(0, 8)
                            .map((diff, idx) => (
                              <div key={`${diff.left_space}-${diff.right_space}-${idx}`} className="text-gray-300">
                                {diff.left_space} vs {diff.right_space}: cos={diff.cosine_similarity.toFixed(3)} l1={diff.l1_distance.toFixed(3)}
                              </div>
                            ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                <div className="rounded border border-slate-700 p-2 mb-3 bg-[#020617]">
                  <div className="text-xs text-gray-300 mb-2">Mini Relation Graph</div>
                  {!normalizedConcept || miniGraphLinks.length === 0 ? (
                    <div className="text-xs text-gray-500">No graph data for selected concept.</div>
                  ) : (
                    <svg viewBox="0 0 320 260" className="w-full h-64">
                      <circle cx="160" cy="130" r="22" fill="#0891b2" />
                      <text x="160" y="134" textAnchor="middle" fontSize="10" fill="#e2e8f0">
                        {normalizedConcept.slice(0, 14)}
                      </text>
                      {miniGraphLinks.map((item, idx) => {
                        const angle = (2 * Math.PI * idx) / miniGraphLinks.length;
                        const x = 160 + Math.cos(angle) * 96;
                        const y = 130 + Math.sin(angle) * 96;
                        const mx = (160 + x) / 2;
                        const my = (130 + y) / 2;
                        const stroke = item.direction === "out" ? "#22c55e" : "#f59e0b";
                        const label = String(item.concept).slice(0, 16);
                        const relationLabel = String(item.relation || "rel").slice(0, 14);
                        return (
                          <g key={`${item.space}-${item.concept}-${idx}`}>
                            <line x1="160" y1="130" x2={x} y2={y} stroke={stroke} strokeWidth="1.5" />
                            <text
                              x={mx}
                              y={my - 4}
                              textAnchor="middle"
                              fontSize="7"
                              fill="#cbd5e1"
                              stroke="#020617"
                              strokeWidth="0.8"
                              paintOrder="stroke"
                            >
                              {relationLabel}
                            </text>
                            <circle cx={x} cy={y} r="16" fill="#0f172a" stroke={stroke} strokeWidth="1.5" />
                            <text x={x} y={y + 3} textAnchor="middle" fontSize="8" fill="#e2e8f0">
                              {label}
                            </text>
                          </g>
                        );
                      })}
                    </svg>
                  )}
                  <div className="mt-1 text-[10px] text-gray-400">
                    Green = outgoing, Amber = incoming
                  </div>
                </div>

                {Object.keys(relatedBySpace).length === 0 ? (
                  <div className="text-xs text-gray-500">No related concepts in selected spaces.</div>
                ) : (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                    {Object.entries(relatedBySpace).map(([space, links]) => (
                      <div key={space} className="rounded border border-slate-700 p-2">
                        <div className="text-xs text-emerald-300 mb-1">[{space}] related concepts</div>
                        <div className="max-h-32 overflow-auto space-y-1 text-xs">
                          {links.slice(0, 20).map((link, idx) => (
                            <div key={`${space}-${idx}`} className="text-gray-300">
                              {link.direction === "out" ? "->" : "<-"} {link.concept} ({link.relation}, {link.confidence.toFixed(3)})
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                <div className="bg-black rounded p-3">
                  <div className="text-sm text-gray-300 mb-2">Top Facts</div>
                  <div className="max-h-72 overflow-auto space-y-2 text-xs">
                    {(recallData?.facts || []).slice(0, 10).map((fact, idx) => (
                      <div key={idx} className="border border-slate-800 rounded p-2">
                        <div className="text-cyan-300">{fact.triple.join(" | ")}</div>
                        <div className="text-gray-400 mt-1">
                          score={fact.score.toFixed(3)} conf={fact.confidence.toFixed(3)} recency={fact.ranking.recency.toFixed(2)} freq={fact.ranking.frequency.toFixed(2)}
                        </div>
                        {fact.triple[1] === "requires_learning" ? (
                          <div className="mt-2 rounded border border-amber-700 bg-[#1f1605] p-2 text-[11px] text-amber-200">
                            Numeracy Gate: hesap yapmadan once bu tokenlari ogrenmem gerekiyor: {fact.triple[2]}
                          </div>
                        ) : null}
                        {Array.isArray(fact.provenance?.["solution_trace"]) && (fact.provenance?.["solution_trace"] as unknown[]).length > 0 ? (
                          <div className="mt-2 rounded border border-slate-700 bg-[#020617] p-2">
                            <div className="text-[11px] text-emerald-300 mb-1">Solution Trace</div>
                            <ol className="list-decimal pl-4 space-y-1 text-[11px] text-slate-300">
                              {(fact.provenance?.["solution_trace"] as unknown[]).slice(0, 8).map((step, sIdx) => (
                                <li key={sIdx}>{String(step)}</li>
                              ))}
                            </ol>
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="bg-black rounded p-3">
                  <div className="text-sm text-gray-300 mb-2">Relation Edges + Provenance</div>
                  <div className="max-h-72 overflow-auto space-y-2 text-xs">
                    {(recallData?.relations_graph?.edges || []).slice(0, 18).map((edge, idx) => (
                      <div key={idx} className="border border-slate-800 rounded p-2">
                        <div>
                          <span className="text-pink-300">[{edge.space}]</span> {edge.source} -{edge.relation_type}-&gt; {edge.target}
                        </div>
                        <div className="text-gray-400">confidence={Number(edge.confidence).toFixed(3)}</div>
                        <div className="text-gray-500">
                          source_document={String(edge.provenance?.["source_document"] ?? "-")} page={String(edge.provenance?.["page_index"] ?? "-")} paragraph={String(edge.provenance?.["paragraph_index"] ?? "-")} sentence={String(edge.provenance?.["sentence_index"] ?? "-")} review={String(edge.provenance?.["review_status"] ?? "-")}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ✅ CANDIDATE REVIEW */}
      <Card>
        <CardContent>
          <h2 className="text-lg mb-3">Candidate Review</h2>
          <button
            onClick={fetchReviewQueue}
            className="mb-3 rounded bg-slate-700 hover:bg-slate-600 px-2 py-1 text-xs"
            disabled={reviewLoading}
          >
            {reviewLoading ? "Refreshing..." : "Refresh Queue"}
          </button>

          <div className="max-h-[520px] overflow-auto space-y-2">
            {reviewQueue.length === 0 ? (
              <div className="text-gray-500 text-sm">No pending candidates</div>
            ) : (
              reviewQueue.map((item) => (
                <div key={item.id} className="rounded border border-slate-700 p-2 bg-black text-xs">
                  <div className="text-cyan-300 mb-1">{item.triple.join(" | ")}</div>
                  <div className="text-gray-400 mb-2">
                    confidence={Number(item.confidence).toFixed(3)} source={String(item.provenance?.["source_document"] ?? "-")}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => promoteCandidate(item.id)}
                      className="rounded bg-emerald-700 hover:bg-emerald-600 px-2 py-1"
                    >
                      Promote
                    </button>
                    <button
                      onClick={() => rejectCandidate(item.id)}
                      className="rounded bg-rose-700 hover:bg-rose-600 px-2 py-1"
                    >
                      Reject
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>

      {/* ✅ EPISODIC MEMORY */}
      <Card>
        <CardContent>
          <h2 className="text-lg mb-3">Episodic Memory</h2>
          <button
            onClick={fetchEpisodicMemory}
            className="mb-3 rounded bg-slate-700 hover:bg-slate-600 px-2 py-1 text-xs"
          >
            Refresh
          </button>
          <div className="max-h-80 overflow-auto space-y-2">
            {episodicMemory.length === 0 ? (
              <div className="text-gray-500 text-sm">No episodes recorded yet.</div>
            ) : (
              episodicMemory.map((ep, idx) => {
                const state = Array.isArray(ep.state) ? (ep.state as string[]).join(", ") : String(ep.state || "");
                const outcome = Array.isArray(ep.outcome) ? (ep.outcome as string[]).join(", ") : String(ep.outcome || "");
                const emotion = ep.emotion as number[] | null;
                const emotionLabel = emotion
                  ? ["fear","anger","sadness","surprise","calm"].filter((_, i) => (emotion[i] || 0) > 0.3).join("+") || "neutral"
                  : "none";
                return (
                  <div key={idx} className="rounded border border-slate-700 p-2 bg-black text-xs">
                    <div className="flex justify-between text-gray-400 mb-1">
                      <span>#{episodicMemory.length - idx}</span>
                      <span className="text-cyan-300">{emotionLabel}</span>
                    </div>
                    <div className="text-gray-200">state: {state || "-"}</div>
                    <div className="text-gray-200">action: {String(ep.action || "")}</div>
                    <div className="text-gray-200">reward: {String(ep.reward ?? "")}</div>
                    <div className="text-gray-400">outcome: {outcome || "-"}</div>
                  </div>
                );
              })
            )}
          </div>
        </CardContent>
      </Card>

      {/* ✅ EMOTIONAL TREND */}
      <Card>
        <CardContent>
          <h2 className="text-lg mb-3">Emotional Trend</h2>
          <button
            onClick={fetchEmotionalTrend}
            className="mb-3 rounded bg-slate-700 hover:bg-slate-600 px-2 py-1 text-xs"
          >
            Refresh
          </button>
          {emotionalTrend && emotionalTrend.count > 0 ? (
            <>
              <div className="text-xs text-gray-400 mb-2">
                Average over last {emotionalTrend.count} episodes
              </div>
              <div className="grid grid-cols-5 gap-1 mb-3">
                {["fear","anger","sadness","surprise","calm"].map((label, i) => {
                  const val = emotionalTrend.avg_vector[i] || 0;
                  const pct = Math.round(val * 100);
                  return (
                    <div key={label} className="text-center">
                      <div className="text-[10px] text-gray-400 uppercase">{label}</div>
                      <div className="text-lg font-bold text-cyan-300">{pct}%</div>
                    </div>
                  );
                })}
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={[
                  { name: "fear", value: emotionalTrend.avg_vector[0] || 0 },
                  { name: "anger", value: emotionalTrend.avg_vector[1] || 0 },
                  { name: "sadness", value: emotionalTrend.avg_vector[2] || 0 },
                  { name: "surprise", value: emotionalTrend.avg_vector[3] || 0 },
                  { name: "calm", value: emotionalTrend.avg_vector[4] || 0 },
                ]}>
                  <XAxis stroke="#94a3b8" tick={{ fill: "#e2e8f0", fontSize: 10 }} dataKey="name" />
                  <YAxis stroke="#94a3b8" tick={{ fill: "#e2e8f0", fontSize: 10 }} domain={[0, 1]} />
                  <Tooltip contentStyle={{ backgroundColor: "#020617" }} />
                  <Bar dataKey="value" fill="#f472b6" />
                </BarChart>
              </ResponsiveContainer>
            </>
          ) : (
            <div className="text-gray-500 text-sm">No emotional trend data available.</div>
          )}
        </CardContent>
      </Card>

      {/* ✅ EMOTION TIMELINE */}
      <Card>
        <CardContent>
          <h2 className="text-lg mb-3">Emotion Timeline</h2>
          <button onClick={fetchEmotionTimeline} className="mb-3 rounded bg-slate-700 hover:bg-slate-600 px-2 py-1 text-xs">Refresh</button>
          {emotionTimelineData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={emotionTimelineData as Array<Record<string, unknown>>}>
                <XAxis
                  dataKey="episode"
                  tick={{ fontSize: 10 }}
                  interval="preserveStartEnd"
                />
                <YAxis
                  domain={[0, 1]}
                  tickCount={5}
                  tickFormatter={(v: number) => v.toFixed(1)}
                />
                <Tooltip />
                <Line type="monotone" dataKey="fear" stroke="#ef4444" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="anger" stroke="#f97316" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="sadness" stroke="#3b82f6" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="surprise" stroke="#eab308" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="calm" stroke="#22c55e" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="text-gray-500 text-sm">No timeline data yet.</div>
          )}
        </CardContent>
      </Card>

      {/* ✅ EMOTION HEATMAP */}
      <Card>
        <CardContent>
          <h2 className="text-lg mb-3">Emotion Heatmap</h2>
          <button onClick={fetchHeatmapData} className="mb-3 rounded bg-slate-700 hover:bg-slate-600 px-2 py-1 text-xs">Refresh</button>
          {heatmapData.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-400">
                    <th className="p-1 text-left">state</th>
                    {["fear","anger","sadness","surprise","calm"].map((l) => (
                      <th key={l} className="p-1">{l}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {heatmapData.map((row, ri) => (
                    <tr key={ri} className="border-t border-slate-700">
                      <td className="p-1 text-cyan-300">{row.state}</td>
                      {["fear","anger","sadness","surprise","calm"].map((l) => {
                        const val = (row as Record<string, unknown>)[l] as number || 0;
                        const hex = val > 0.5 ? "#ef4444" : val > 0.2 ? "#f97316" : "#22c55e";
                        return (
                          <td
                            key={l}
                            className="p-1 text-center cursor-pointer hover:opacity-80"
                            style={{ backgroundColor: hex, opacity: 0.3 + val * 0.7 }}
                            onClick={() => setHeatmapSelected({ state: row.state, emotion: l })}
                            title={`${row.state} ${l}: ${(val * 100).toFixed(0)}%`}
                          >
                            {(val * 100).toFixed(0)}%
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              {heatmapSelected && (
                <div className="mt-2 text-xs text-gray-400">
                  Selected: <span className="text-cyan-300">{heatmapSelected.state}</span> /{" "}
                  <span className="text-cyan-300">{heatmapSelected.emotion}</span>
                </div>
              )}
            </div>
          ) : (
            <div className="text-gray-500 text-sm">No heatmap data yet.</div>
          )}
        </CardContent>
      </Card>

      {/* ✅ ABSTRACTION PANEL */}
      <Card>
        <CardContent>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg">Abstraction Layer</h2>
            <button
              onClick={triggerAbstraction}
              disabled={abstractionLoading}
              className="rounded bg-indigo-700 hover:bg-indigo-600 px-2 py-1 text-xs disabled:opacity-50"
            >
              {abstractionLoading ? "Processing..." : "Trigger Abstraction"}
            </button>
          </div>
          <button onClick={fetchAbstractions} className="mb-3 rounded bg-slate-700 hover:bg-slate-600 px-2 py-1 text-xs">Refresh</button>
          {abstractions ? (
            <div className="max-h-80 overflow-auto space-y-2">
              {abstractions.abstract_patterns?.length > 0 && (
                <div>
                  <h3 className="text-sm text-gray-400 mb-1">Abstract Patterns ({abstractions.abstract_patterns.length})</h3>
                  {abstractions.abstract_patterns.map((p, i) => (
                    <div key={i} className="rounded border border-slate-700 p-2 bg-black text-xs mb-1">
                      <div className="text-cyan-300">{String(p.pattern || p.id || "")}</div>
                      <div className="text-gray-400">subjects: {String(p.subjects || p.subject_count || "")}</div>
                      <div className="text-gray-400">abstraction: {typeof p.abstraction_level === "number" ? (p.abstraction_level * 100).toFixed(0) + "%" : String(p.abstraction_level || "")}</div>
                    </div>
                  ))}
                </div>
              )}
              {abstractions.abstract_rules?.length > 0 && (
                <div>
                  <h3 className="text-sm text-gray-400 mb-1 mt-2">Abstract Rules ({abstractions.abstract_rules.length})</h3>
                  {abstractions.abstract_rules.map((r, i) => (
                    <div key={i} className="rounded border border-slate-700 p-2 bg-black text-xs mb-1">
                      <div className="text-cyan-300">{String(r.rule || "")}</div>
                      <div className="text-gray-400">abstraction: {typeof r.abstraction === "number" ? (r.abstraction * 100).toFixed(0) + "%" : String(r.abstraction || "")}</div>
                      <div className="text-gray-400">context: {String(r.context || "")}</div>
                    </div>
                  ))}
                </div>
              )}
              {(!abstractions.abstract_patterns || abstractions.abstract_patterns.length === 0) &&
               (!abstractions.abstract_rules || abstractions.abstract_rules.length === 0) && (
                <div className="text-gray-500 text-sm">No abstractions available. Try triggering abstraction above.</div>
              )}
            </div>
          ) : (
            <div className="text-gray-500 text-sm">No abstraction data. Refresh to load.</div>
          )}
        </CardContent>
      </Card>

    </div>
  );
}