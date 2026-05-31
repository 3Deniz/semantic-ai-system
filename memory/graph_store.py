import json

class GraphStore:
    def __init__(self, path='graph.json'):
        self.path = path

    def save(self, graph):
        with open(self.path, 'w') as f:
            json.dump(graph.triples, f, indent=2)

    def load(self, graph):
        try:
            with open(self.path, 'r') as f:
                # JSON stores arrays as lists; convert back to tuples
                # so that tuple comparisons in KnowledgeGraph/conflict/rule_learning work correctly
                graph.triples = [tuple(t) for t in json.load(f)]
        except FileNotFoundError:
            pass
