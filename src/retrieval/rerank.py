"""Second-stage reranking: a cross-encoder reads the query and chunk together, so it only sees a short list."""

from src.retrieval.corpus import Hit

MODEL = "BAAI/bge-reranker-v2-m3"
MODEL_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"  # pinned so the results can be reproduced
CANDIDATES = 50  # a wider list than 20 scored better in eval, and took longer


def load_scorer():
    """A function from a query and texts to one relevance score per text, from 0 to 1."""
    # imported here because it is slow, and BM25 and the tests do not need it
    from sentence_transformers import CrossEncoder
    model = CrossEncoder(MODEL, revision=MODEL_REVISION, max_length=512)
    return lambda query, texts: model.predict([(query, t) for t in texts], batch_size=8)


class RerankRetriever:
    def __init__(self, first_pass, score):
        self.first_pass = first_pass
        self.score = score

    def search(self, query, k=5):
        hits = self.first_pass.search(query, k=CANDIDATES)
        if not hits:
            return []
        scores = self.score(query, [h.chunk["text"] for h in hits])
        ranked = sorted(zip(hits, scores), key=lambda pair: pair[1], reverse=True)[:k]
        return [Hit(h.chunk, float(s), h.parts) for h, s in ranked]
