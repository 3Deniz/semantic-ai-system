class KnowledgeGraph:
    def __init__(self):
        self.triples = []
        self.metadata = {}

    def add(self, s, r, o, confidence, metadata=None):
        triple = (s, r, o, confidence)
        key = (s, r, o)

        exists = False
        for t in self.triples:
            if t[:3] == triple[:3]:
                exists = True
                if confidence > t[3]:
                    self.triples.remove(t)
                    self.triples.append(triple)
                    if metadata is not None:
                        self.metadata[key] = dict(metadata)
                break

        if not exists:
            self.triples.append(triple)
            self.metadata[key] = dict(metadata or {})

        if exists and metadata is not None and key not in self.metadata:
            self.metadata[key] = dict(metadata)

    def get_metadata(self, s, r, o):
        return self.metadata.get((s, r, o), {})

    def show(self):
        for t in self.triples:
            print(t)
