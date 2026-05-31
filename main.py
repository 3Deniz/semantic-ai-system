import random
import json
from collections import defaultdict, Counter
from config import (
    ACTIONS,
    ACTION_COST as COST,
    ALPHA,
    GAMMA,
    EPSILON,
    EPSILON_DECAY,
    TRAIN_EPISODES,
    STEPS_PER_EPISODE,
    RAIN_PROBABILITY,
    RAIN_FLOOD_PROBABILITY,
    FLOOD_DAMAGE_PROBABILITY,
    DAMAGE_COLLAPSE_PROBABILITY,
    COLLAPSE_CRISIS_PROBABILITY,
    RAIN_CLEAR_PROBABILITY,
    RELEASE_FLOOD_CLEAR_PROBABILITY,
    EVACUATED_RETURN_PROBABILITY,
    POLICY_FILE,
    POLICY_CONFIDENCE_THRESHOLD,
)

# =========================
# ✅ Q TABLE

Q = defaultdict(float)
policy_counter = defaultdict(Counter)

# =========================
# ✅ ENV

def reset_env():
    return {"rain": random.random() < RAIN_PROBABILITY}

def has_threat(state):
    return "flood" in state or "damage" in state or "collapse" in state

# =========================
# ✅ WORLD

def step_world(state):
    s = set(state)

    if "rain" in s and random.random() < RAIN_FLOOD_PROBABILITY:
        s.add("flood")

    if "flood" in s and random.random() < FLOOD_DAMAGE_PROBABILITY:
        s.add("damage")

    if "damage" in s and random.random() < DAMAGE_COLLAPSE_PROBABILITY:
        s.add("collapse")

    if "collapse" in s and random.random() < COLLAPSE_CRISIS_PROBABILITY:
        s.add("crisis")

    # ✅ ACTION EFFECTS
    if "barrier" in s:
        s.discard("flood")
        s.discard("damage")

    if "release" in s and random.random() < RELEASE_FLOOD_CLEAR_PROBABILITY:
        s.discard("flood")

    if "evacuated" in s:
        s.discard("collapse")
        s.discard("crisis")
        # Probabilistic return to normal — models real-world recovery dynamics
        if random.random() < EVACUATED_RETURN_PROBABILITY:
            s.discard("evacuated")

    if "rain" in s and random.random() < RAIN_CLEAR_PROBABILITY:
        s.discard("rain")

    # ✅ Action tokens are transient — remove after effects are applied
    s.discard("barrier")
    s.discard("release")

    return s

# =========================
# ✅ REWARD

def reward_fn(prev, state, action):

    if action == "barrier" and "barrier" in prev:
        return -0.6

    if action == "release" and "flood" not in prev:
        return -0.4

    if action == "evacuate" and not has_threat(prev):
        return -0.5

    if action == "none":
        return 1.2 if not has_threat(prev) else -1.0

    if "crisis" in state:
        return -4

    if "collapse" in state:
        r = -1
    elif "damage" in state:
        r = -0.5
    elif "flood" in state:
        r = -0.2
    else:
        r = 1.0

    return r + COST[action]

# =========================
# ✅ KEY

def get_key(s):
    return tuple(sorted(s))

# =========================
# ✅ ACTION SELECTION

def choose_action(state, epsilon):
    key = get_key(state)

    if random.random() < epsilon:
        return random.choice(ACTIONS)

    return max(ACTIONS, key=lambda a: Q[(key, a)])

# =========================
# ✅ Q UPDATE

def update_q(s, a, r, s2):
    key = get_key(s)
    key2 = get_key(s2)

    best_future = max(Q[(key2, x)] for x in ACTIONS)
    Q[(key, a)] += ALPHA * (r + GAMMA * best_future - Q[(key, a)])

# =========================
# ✅ AGENT

class Agent:

    def __init__(self):
        self.reward = 0

    def act(self, state, epsilon):
        action = choose_action(state, epsilon)

        prev = set(state)
        s = set(state)

        if action == "barrier":
            s.add("barrier")
        elif action == "release":
            s.add("release")
        elif action == "evacuate":
            s.add("evacuated")

        s2 = step_world(s)
        r = reward_fn(prev, s2, action)

        update_q(prev, action, r, s2)

        self.reward += r
        policy_counter[get_key(prev)][action] += 1

        return s2

# =========================
# ✅ TRAIN

def train():
    agent = Agent()
    epsilon = EPSILON

    for _ in range(TRAIN_EPISODES):
        state = set()

        if reset_env()["rain"]:
            state.add("rain")

        for _ in range(STEPS_PER_EPISODE):
            state = agent.act(state, epsilon)

        epsilon *= EPSILON_DECAY

    print("training complete ✅")

# =========================
# ✅ EXPORT

def export_policy():
    policy = {}

    for state, counts in policy_counter.items():
        total = sum(counts.values())
        best, best_count = counts.most_common(1)[0]

        if best_count / total >= POLICY_CONFIDENCE_THRESHOLD:
            policy[str(state)] = best

    with open(POLICY_FILE, "w") as f:
        json.dump(policy, f, indent=2)

    print("policy exported ✅")

# =========================
# ✅ DEPLOY

class DeployAgent:

    def __init__(self):
        with open(POLICY_FILE) as f:
            self.policy = json.load(f)

    def act(self, state):
        key = str(tuple(sorted(state)))
        return self.policy.get(key, "none")

# =========================
# ✅ TEST

def run_deploy():
    agent = DeployAgent()

    state = set()
    if reset_env()["rain"]:
        state.add("rain")

    total = 0

    for i in range(12):
        action = agent.act(state)
        print(f"STEP {i} | STATE {state} → ACTION {action}")

        s = set(state)

        if action == "barrier":
            s.add("barrier")
        elif action == "release":
            s.add("release")
        elif action == "evacuate":
            s.add("evacuated")

        s2 = step_world(s)
        total += reward_fn(state, s2, action)

        state = s2

    print("\nTOTAL REWARD:", round(total, 2))

# =========================

if __name__ == "__main__":
    # =========================
    # ✅ SEMANTIC STACK (CLI only)
    # Lazy-initialised so that `import main` in api.py stays fast.

    _cli_tms     = None
    _cli_kg      = None
    _cli_loader  = None

    def _ensure_semantic():
        """Initialise the semantic stack once for interactive CLI use."""
        global _cli_tms, _cli_kg, _cli_loader
        if _cli_loader is not None:
            return
        from core.tms import LiteTMS
        from core.knowledge_graph import KnowledgeGraph
        from core.data_loader import DataLoader
        from config import TMS_DECAY_RATE, TMS_MIN_CONFIDENCE
        _cli_tms    = LiteTMS(decay_rate=TMS_DECAY_RATE, min_confidence=TMS_MIN_CONFIDENCE)
        _cli_kg     = KnowledgeGraph()
        _cli_loader = DataLoader(tms=_cli_tms, kg=_cli_kg)

    def _cmd_teach(sentence: str):
        """Parse a natural-language statement and inject it into the knowledge base."""
        _ensure_semantic()
        result = _cli_loader.ingest_texts([sentence])
        n = result["triples"]
        if n:
            print(f"✅ {n} triple(s) ingested from: {sentence!r}")
        else:
            print(f"⚠️  Could not parse: {sentence!r}")

    def _cmd_load(path: str):
        """Load a data file (JSON/JSONL/CSV/TXT) and inject its contents."""
        _ensure_semantic()
        try:
            result = _cli_loader.load_file(path)
            print(
                f"✅ Loaded {path!r} — "
                f"triples={result['triples']}, "
                f"transitions={result['transitions']}, "
                f"q_updates={result['q_updates']}"
            )
        except FileNotFoundError as exc:
            print(f"❌ {exc}")
        except Exception as exc:
            print(f"❌ Error loading file: {exc}")

    def _cmd_seed():
        """Inject built-in domain knowledge for the flood/disaster domain."""
        _ensure_semantic()
        result = _cli_loader.ingest_seed_knowledge()
        print(f"✅ Seed knowledge injected — {result['triples']} triples")

    def _cmd_status():
        """Print a summary of current learning state."""
        q_states  = len({k[0] for k in Q.keys()})
        q_entries = len(Q)
        policies  = len(policy_counter)
        print(f"Q-table  : {q_entries} entries across {q_states} states")
        print(f"Policy   : {policies} states have action counts")
        if _cli_tms is not None:
            valid = sum(1 for b in _cli_tms.beliefs if b["valid"])
            total = len(_cli_tms.beliefs)
            print(f"TMS      : {valid}/{total} valid beliefs")
        if _cli_kg is not None:
            print(f"KG       : {len(_cli_kg.triples)} triples")

    def _cmd_episodes(n_str: str):
        """Run N additional training episodes."""
        try:
            n = int(n_str)
        except ValueError:
            print("Usage: episodes <N>")
            return
        agent   = Agent()
        epsilon = EPSILON
        for _ in range(n):
            state = set()
            if reset_env()["rain"]:
                state.add("rain")
            for _ in range(STEPS_PER_EPISODE):
                state = agent.act(state, epsilon)
            epsilon *= EPSILON_DECAY
        print(f"✅ {n} extra episodes done")

    # =========================
    HELP = (
        "commands:\n"
        "  train              — run full RL training\n"
        "  episodes <N>       — run N more training episodes\n"
        "  export             — export policy to policy.json\n"
        "  deploy             — run 12-step deployment demo\n"
        "  seed               — inject built-in domain knowledge\n"
        "  load <file>        — load JSON/JSONL/CSV/TXT data file\n"
        "  teach <sentence>   — teach a single fact (natural language)\n"
        "  status             — show Q-table + knowledge-base summary\n"
        "  help               — show this message\n"
        "  exit / quit        — exit"
    )

    print("🧠 Semantic AI Decision Engine — interactive CLI")
    print(HELP)

    while True:
        try:
            raw = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue

        parts = raw.split(None, 1)
        cmd   = parts[0].lower()
        arg   = parts[1] if len(parts) > 1 else ""

        if cmd == "train":
            train()
        elif cmd == "episodes":
            _cmd_episodes(arg)
        elif cmd == "export":
            export_policy()
        elif cmd == "deploy":
            run_deploy()
        elif cmd == "seed":
            _cmd_seed()
        elif cmd == "load":
            if arg:
                _cmd_load(arg)
            else:
                print("Usage: load <file>")
        elif cmd == "teach":
            if arg:
                _cmd_teach(arg)
            else:
                print("Usage: teach <sentence>")
        elif cmd == "status":
            _cmd_status()
        elif cmd in ("help", "?"):
            print(HELP)
        elif cmd in ("exit", "quit", "q"):
            break
        else:
            print(f"Unknown command: {cmd!r}  (type 'help' for list)")