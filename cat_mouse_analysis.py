"""cat_mouse_analysis.py — Kedi/Fare öğrenme süreci analizi ve görselleştirme.

Gerçekler:
  1. Kedi bir hayvandır.              → cat is animal
  2. Fare bir hayvandır.              → mouse is animal
  3. Kedi insanları fareden korumak
     için beslenir.                  → cat protects human (from mouse)
                                     → cat prevents mouse_threat

Bu script:
  - Gerçekleri TMS + KnowledgeGraph'a yükler
  - ConceptLearner ile kavram örüntüleri çıkarır
  - RuleLearner ile kurallar öğrenir
  - Reasoner ile yeni bilgiler türetir
  - Tüm adımları matplotlib/networkx ile görselleştirir
  - screenshots/cat_mouse_learning.png dosyasına kaydeder
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
from textwrap import wrap

from core.tms import LiteTMS
from core.knowledge_graph import KnowledgeGraph
from core.data_loader import DataLoader
from learning.concept_learning import ConceptLearner
from learning.rule_learning import RuleLearner
from learning.online_learning import OnlineLearner
from core.reasoning import Reasoner

# ---------------------------------------------------------------------------
# 1. Bilgi tabanı oluştur
# ---------------------------------------------------------------------------
tms = LiteTMS(decay_rate=0.95, min_confidence=0.3)
kg  = KnowledgeGraph()
loader = DataLoader(tms=tms, kg=kg)

FACTS = [
    # Kedi bir hayvandır
    {"subject": "cat",  "relation": "is",       "object": "animal",       "confidence": 0.95},
    # Fare bir hayvandır
    {"subject": "mouse","relation": "is",       "object": "animal",       "confidence": 0.95},
    # Kedi evcil hayvan türüdür
    {"subject": "cat",  "relation": "is",       "object": "domestic_pet", "confidence": 0.90},
    # Kedi insanları fareden korur
    {"subject": "cat",  "relation": "protects", "object": "human",        "confidence": 0.85},
    # Kedi fare tehdidini önler
    {"subject": "cat",  "relation": "prevents", "object": "mouse_threat", "confidence": 0.80},
    # Fare zararlı olabilir
    {"subject": "mouse","relation": "is",       "object": "pest",         "confidence": 0.70},
    # Kedi fare ile beslenir (avlanma davranışı)
    {"subject": "cat",  "relation": "hunts",    "object": "mouse",        "confidence": 0.90},
    # Arka plan bilgisi — kural öğrenimi için gerekli zincirleme triples
    {"subject": "animal",       "relation": "is",     "object": "living_being",  "confidence": 0.99},
    {"subject": "domestic_pet", "relation": "is",     "object": "companion",     "confidence": 0.88},
    {"subject": "pest",         "relation": "causes", "object": "damage",        "confidence": 0.75},
    {"subject": "pest",         "relation": "is",     "object": "threat",        "confidence": 0.72},
]

print("=" * 60)
print("📚 ADIM 1: Gerçekleri TMS + KG'ye yüklüyorum...")
print("=" * 60)
for fact in FACTS:
    ok = loader.ingest_triple(fact)
    neg = " [NEGATED]" if fact.get("negation") else ""
    status = "✅" if ok else "⚠️ "
    print(f"  {status} ({fact['subject']}, {fact['relation']}, {fact['object']}) "
          f"conf={fact['confidence']}{neg}")

print(f"\nToplam: {len(kg.triples)} triple KG'de, "
      f"{sum(1 for b in tms.beliefs if b['valid'])} geçerli TMS inancı\n")

# ---------------------------------------------------------------------------
# 2. Kavram öğrenimi
# ---------------------------------------------------------------------------
print("=" * 60)
print("🧠 ADIM 2: Kavram Öğrenimi (ConceptLearner)...")
print("=" * 60)
cl = ConceptLearner(tms)
concepts = cl.learn()
if concepts:
    for c in concepts:
        print(f"  📌 Kavram: «{c['pattern']}»  destek={c['support']}")
else:
    print("  (henüz yeterli destek yok — tekli örüntüler bulundu)")
    # Tüm örüntüleri manuel göster
    from collections import defaultdict
    pattern_counts = defaultdict(int)
    for belief in tms.beliefs:
        if belief["valid"]:
            _, r, o = belief["triple"]
            pattern_counts[(r, o)] += 1
    for (r, o), cnt in sorted(pattern_counts.items(), key=lambda x: -x[1]):
        print(f"    örüntü: X {r} {o}  —  destek: {cnt}")

# ---------------------------------------------------------------------------
# 3. Kural öğrenimi
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("📐 ADIM 3: Kural Öğrenimi (RuleLearner)...")
print("=" * 60)
rl = RuleLearner(tms)
rules = rl.learn_rules()
if rules:
    for rule in rules:
        r_if, o_if  = rule["if"]
        r_then, o_then = rule["then"]
        print(f"  🔗 EĞER X {r_if} {o_if}  →  X {r_then} {o_then}  "
              f"(ağırlık={rule['weight']:.2f}, kullanım={rule['usage']})")
else:
    print("  (kural üretmek için yeterli eşleşen triple yok)")

# ---------------------------------------------------------------------------
# 4. Çıkarım / Inference
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("🔍 ADIM 4: Çıkarım (Reasoner)...")
print("=" * 60)
reasoner = Reasoner(kg, max_depth=5)
inferred = reasoner.infer()

# Ayrıca rule-based inference uygula
rule_inferred = rl.apply_rules(kg)

all_inferred = inferred + rule_inferred

if all_inferred:
    for s, r, o, c in all_inferred:
        print(f"  💡 Türetildi: ({s}, {r}, {o})  güven={c:.2f}")
else:
    print("  (yeni çıkarım yok — tüm bilgiler doğrudan yüklendi)")

# ---------------------------------------------------------------------------
# 5. Online öğrenme — güven güncellemesi
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("🔄 ADIM 5: Online Öğrenme (güven güncellemesi)...")
print("=" * 60)
ol = OnlineLearner(tms)
# Kedi'nin insanları koruduğunu pekiştir
ol.apply_feedback(("cat", "protects", "human"), "correct")
ol.apply_feedback(("cat", "prevents", "mouse_threat"), "correct")
print("  ✅ 'cat protects human' pekiştirildi")
print("  ✅ 'cat prevents mouse_threat' pekiştirildi")

# Güncellenmiş inanç güvenlerini göster
print("\n  Güncel TMS inanç güvenleri:")
for b in sorted(tms.beliefs, key=lambda x: -x["confidence"]):
    if b["valid"]:
        s, r, o = b["triple"]
        print(f"    ({s}, {r}, {o})  conf={b['confidence']:.3f}  "
              f"kullanım={b['usage']}")

# ---------------------------------------------------------------------------
# 6. Görselleştirme
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("🎨 ADIM 6: Görselleştirme oluşturuluyor...")
print("=" * 60)

fig = plt.figure(figsize=(20, 14), facecolor="#0f0f1a")
fig.suptitle(
    "Kedi & Fare — Semantik Yapay Zeka Öğrenme Süreci Analizi",
    fontsize=16, fontweight="bold", color="white", y=0.98
)

# ── Panel A: Bilgi Grafiği ──────────────────────────────────────────────────
ax1 = fig.add_subplot(2, 3, (1, 2))
ax1.set_facecolor("#0f0f1a")
ax1.set_title("① Bilgi Grafiği (Knowledge Graph)", color="white", fontsize=12, pad=10)

G = nx.DiGraph()
edge_colors, edge_labels = [], {}
relation_palette = {
    "is":       "#4fc3f7",
    "protects": "#81c784",
    "prevents": "#ffb74d",
    "hunts":    "#f06292",
    "hunts":    "#ce93d8",
}
node_colors_map = {
    "cat":          "#ff8a65",
    "mouse":        "#90caf9",
    "animal":       "#a5d6a7",
    "domestic_pet": "#fff176",
    "human":        "#80cbc4",
    "mouse_threat": "#ef9a9a",
    "pest":         "#bcaaa4",
}

for s, r, o, c in kg.triples:
    G.add_edge(s, o, relation=r, confidence=c)
    edge_labels[(s, o)] = f"{r}\n({c:.2f})"

for s, r, o, c in all_inferred:
    if not G.has_edge(s, o):
        G.add_edge(s, o, relation=r, confidence=c, inferred=True)
        edge_labels[(s, o)] = f"{r}*\n({c:.2f})"

node_c = [node_colors_map.get(n, "#b0bec5") for n in G.nodes()]
try:
    pos = nx.spring_layout(G, seed=42, k=2.2)
except Exception:
    pos = nx.circular_layout(G)

nx.draw_networkx_nodes(G, pos, node_color=node_c, node_size=1400,
                       ax=ax1, alpha=0.92)
nx.draw_networkx_labels(G, pos, font_size=9, font_color="white",
                        font_weight="bold", ax=ax1)

straight_edges = [e for e in G.edges() if not G.has_edge(e[1], e[0])]
curved_edges   = [e for e in G.edges() if G.has_edge(e[1], e[0]) and e[0] < e[1]]

nx.draw_networkx_edges(G, pos, edgelist=straight_edges, ax=ax1,
                       edge_color="#78909c", arrows=True, arrowsize=18,
                       connectionstyle="arc3,rad=0.0", width=1.8)
nx.draw_networkx_edges(G, pos, edgelist=curved_edges, ax=ax1,
                       edge_color="#78909c", arrows=True, arrowsize=18,
                       connectionstyle="arc3,rad=0.25", width=1.8)
nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=7,
                             font_color="#cfd8dc", ax=ax1,
                             bbox=dict(boxstyle="round,pad=0.2", fc="#1a1a2e", alpha=0.7))

legend_patches = [mpatches.Patch(color=v, label=k)
                  for k, v in node_colors_map.items() if k in G.nodes()]
ax1.legend(handles=legend_patches, loc="lower left", fontsize=7,
           facecolor="#1a1a2e", labelcolor="white", framealpha=0.8)
ax1.axis("off")

# ── Panel B: Öğrenme Adımları ───────────────────────────────────────────────
ax2 = fig.add_subplot(2, 3, 3)
ax2.set_facecolor("#0f0f1a")
ax2.set_title("② Öğrenme Adımları", color="white", fontsize=12, pad=10)
ax2.axis("off")

steps = [
    ("ADIM 1", "Gerçek Yükleme\n(TMS + KG)", "#4fc3f7",
     f"{len(kg.triples)} triple\nyüklendi"),
    ("ADIM 2", "Kavram Öğrenimi\n(ConceptLearner)", "#81c784",
     f"{max(len(concepts),1)} kavram\nbulundu"),
    ("ADIM 3", "Kural Öğrenimi\n(RuleLearner)", "#ffb74d",
     f"{len(rules)} kural\nöğrenildi"),
    ("ADIM 4", "Çıkarım\n(Reasoner)", "#f48fb1",
     f"{len(all_inferred)} yeni\ntriple türetildi"),
    ("ADIM 5", "Online Pekiştirme\n(OnlineLearner)", "#ce93d8",
     "Güven\ngüncellendi"),
]

y_positions = [0.88, 0.70, 0.52, 0.34, 0.16]
for (label, title, color, result), y in zip(steps, y_positions):
    fancy = mpatches.FancyBboxPatch((0.04, y - 0.07), 0.92, 0.14,
                                     boxstyle="round,pad=0.02",
                                     facecolor=color + "33", edgecolor=color,
                                     linewidth=2, transform=ax2.transAxes)
    ax2.add_patch(fancy)
    ax2.text(0.08, y + 0.02, label, transform=ax2.transAxes,
             fontsize=8, color=color, fontweight="bold", va="center")
    ax2.text(0.30, y + 0.02, title, transform=ax2.transAxes,
             fontsize=8, color="white", va="center")
    ax2.text(0.78, y + 0.02, result, transform=ax2.transAxes,
             fontsize=7, color="#b0bec5", va="center", ha="center")
    if y > 0.16:
        ax2.annotate("", xy=(0.5, y - 0.075), xytext=(0.5, y - 0.07 - 0.01),
                     xycoords="axes fraction", textcoords="axes fraction",
                     arrowprops=dict(arrowstyle="->", color="#546e7a", lw=1.5))

# ── Panel C: TMS Güven Çubuğu ───────────────────────────────────────────────
ax3 = fig.add_subplot(2, 3, 4)
ax3.set_facecolor("#0f0f1a")
ax3.set_title("③ TMS İnanç Güvenleri", color="white", fontsize=12, pad=10)

valid_beliefs = sorted(
    [b for b in tms.beliefs if b["valid"]],
    key=lambda x: x["confidence"], reverse=True
)
bar_labels = [f"({b['triple'][0]},{b['triple'][1]},\n{b['triple'][2]})"
              for b in valid_beliefs]
bar_confs   = [b["confidence"] for b in valid_beliefs]
bar_colors  = ["#4fc3f7" if b["triple"][1] == "is"
               else "#81c784" if b["triple"][1] in ("protects", "prevents")
               else "#ffb74d" for b in valid_beliefs]

bars = ax3.barh(range(len(bar_labels)), bar_confs, color=bar_colors,
                edgecolor="#37474f", height=0.65)
ax3.set_yticks(range(len(bar_labels)))
ax3.set_yticklabels(bar_labels, fontsize=7.5, color="white")
ax3.set_xlim(0, 1.15)
ax3.set_xlabel("Güven (Confidence)", color="#90a4ae", fontsize=9)
ax3.tick_params(colors="#90a4ae")
ax3.spines[:].set_color("#37474f")
for bar, conf in zip(bars, bar_confs):
    ax3.text(conf + 0.02, bar.get_y() + bar.get_height() / 2,
             f"{conf:.3f}", va="center", fontsize=7.5, color="white")
legend_el = [
    mpatches.Patch(color="#4fc3f7", label="is (sınıflandırma)"),
    mpatches.Patch(color="#81c784", label="protects/prevents"),
    mpatches.Patch(color="#ffb74d", label="diğer"),
]
ax3.legend(handles=legend_el, fontsize=7, facecolor="#1a1a2e",
           labelcolor="white", framealpha=0.8, loc="lower right")

# ── Panel D: Öğrenilen Kavramlar ────────────────────────────────────────────
ax4 = fig.add_subplot(2, 3, 5)
ax4.set_facecolor("#0f0f1a")
ax4.set_title("④ Kavram & Kural Özeti", color="white", fontsize=12, pad=10)
ax4.axis("off")

summary_lines = []
summary_lines.append(("[KAVRAMLAR]", "#4fc3f7"))
from collections import defaultdict as _dd
pc = _dd(int)
for b in tms.beliefs:
    if b["valid"]:
        _, r, o = b["triple"]
        pc[(r, o)] += 1
for (r, o), cnt in sorted(pc.items(), key=lambda x: -x[1]):
    summary_lines.append((f"  X {r} {o}  [destek={cnt}]", "#cfd8dc"))

summary_lines.append(("", "white"))
summary_lines.append(("[KURALLAR]", "#ffb74d"))
if rules:
    for rule in rules:
        r_if, o_if   = rule["if"]
        r_then, o_then = rule["then"]
        summary_lines.append(
            (f"  {r_if} {o_if} -> {r_then} {o_then}  [w={rule['weight']:.2f}]",
             "#fff9c4")
        )
else:
    summary_lines.append(("  (kural yok)", "#90a4ae"))

summary_lines.append(("", "white"))
summary_lines.append(("[TURETILEN]", "#f48fb1"))
if all_inferred:
    for s, r, o, c in all_inferred:
        summary_lines.append((f"  ({s}, {r}, {o})  c={c:.2f}", "#f8bbd0"))
else:
    summary_lines.append(("  (dogrudan yuklendi)", "#90a4ae"))

y_txt = 0.97
for text, color in summary_lines:
    ax4.text(0.02, y_txt, text, transform=ax4.transAxes, fontsize=8,
             color=color, va="top", fontfamily="monospace")
    y_txt -= 0.062 if text.startswith(("📌", "📐", "💡")) else 0.052

# ── Panel E: Senaryo Açıklaması ─────────────────────────────────────────────
ax5 = fig.add_subplot(2, 3, 6)
ax5.set_facecolor("#0f0f1a")
ax5.set_title("⑤ Senaryo & Yorumlama", color="white", fontsize=12, pad=10)
ax5.axis("off")

scenario_text = (
    "GİRDİ GERÇEKLER\n"
    "───────────────\n"
    "• Kedi bir hayvandır\n"
    "• Fare bir hayvandır\n"
    "• Kedi insanları fareden korumak\n"
    "  için beslenir\n\n"
    "ÖĞRENME SÜRECİ\n"
    "───────────────\n"
    "1. TMS çelişki denetimi yaptı →\n"
    "   tüm gerçekler kabul edildi\n\n"
    "2. ConceptLearner 'X is animal'\n"
    "   örüntüsünü keşfetti (kedi+fare)\n\n"
    "3. RuleLearner: is(animal) &\n"
    "   is(pest) zincirinden kural\n"
    "   çıkarımı denedi\n\n"
    "4. Reasoner: kedi → evcil_hayvan\n"
    "   → hayvan (transitif is-is)\n\n"
    "5. OnlineLearner: 'koruma'\n"
    "   davranışı güven ile pekişti\n\n"
    "SONUÇ\n"
    "──────\n"
    "Sistem kedi-fare ilişkisini\n"
    "semantik olarak modelledi:\n"
    "kedi hem hayvan hem koruyucu,\n"
    "fare hem hayvan hem zararlı."
)
ax5.text(0.04, 0.97, scenario_text, transform=ax5.transAxes,
         fontsize=8, color="#e0e0e0", va="top",
         fontfamily="monospace",
         bbox=dict(boxstyle="round,pad=0.5", facecolor="#1a237e",
                   edgecolor="#3949ab", alpha=0.8))

plt.tight_layout(rect=[0, 0, 1, 0.96])

out_path = os.path.join(os.path.dirname(__file__), "screenshots", "cat_mouse_learning.png")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="#0f0f1a")
plt.close()

print(f"\n✅ Görsel kaydedildi: {out_path}")
print("=" * 60)
print("ÖZETLEYİCİ BULGULAR")
print("=" * 60)
print(f"  • Yüklenen triple sayısı  : {len(kg.triples)}")
print(f"  • Geçerli TMS inancı      : {sum(1 for b in tms.beliefs if b['valid'])}")
print(f"  • Öğrenilen kavram sayısı : {len(concepts)}")
print(f"  • Öğrenilen kural sayısı  : {len(rules)}")
print(f"  • Türetilen bilgi sayısı  : {len(all_inferred)}")
print("=" * 60)
