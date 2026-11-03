"""Second-stage reranking: a cross-encoder reads the query and chunk together, so it only sees a short list."""

import hashlib
import sqlite3

from src.retrieval.corpus import ROOT, Hit

MODEL = "BAAI/bge-reranker-v2-m3"
MODEL_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"  # pinned so the results can be reproduced
CANDIDATES = 50  # the best scores in eval, but too slow on CPU to use live
LIVE_CANDIDATES = 20  # plain RAG uses this: about 2.5 times less work per query
AGENT_CANDIDATES = 10  # the agent searches two wordings, so the same 20 pairs in all, and scored better than 20 each
SCORES = ROOT / "data" / "index" / "rerank_scores.sqlite"


def pair_key(query, text):
    return hashlib.sha256(f"{MODEL_REVISION}\0{query}\0{text}".encode()).hexdigest()


def load_scorer(path=SCORES):
    """A function from a query and texts to one relevance score per text, from 0 to 1.

    Scores are kept on disk because a pair always scores the same and takes most of a second to compute on CPU.
    """
    # imported here because it is slow, and BM25 and the tests do not need it
    from sentence_transformers import CrossEncoder
    model = CrossEncoder(MODEL, revision=MODEL_REVISION, max_length=512)
    path.parent.mkdir(parents=True, exist_ok=True)
    # the API answers requests on several threads
    db =sqlite3.connect(path, check_same_thread=False)
    db.execute("CREATE TABLE IF NOT EXISTS scores (pair TEXT PRIMARY KEY, score REAL)")

    def score(query, texts):
        keys = [pair_key(query, t) for t in texts]
        known = {}
        for key in keys:
            known.update(db.execute("SELECT pair, score FROM scores WHERE pair = ?", (key,)).fetchall())
        todo = [(key, t) for key, t in zip(keys, texts) if key not in known]
        if todo:
            new = model.predict([(query, t) for _, t in todo], batch_size=8)
            rows = [(key, float(s)) for (key, _), s in zip(todo, new)]
            known.update(rows)
            db.executemany("INSERT OR REPLACE INTO scores VALUES (?, ?)", rows)
            db.commit()
        return [known[key] for key in keys]

    return score


def search_both(retriever, queries, k=5):
    """The best score per chunk across several wordings of one question."""
    best = {}
    for query in dict.fromkeys(queries):
        for hit in retriever.search(query, k=retriever.candidates):
            chunk_id = hit.chunk["chunk_id"]
            if chunk_id not in best or hit.score > best[chunk_id].score:
                best[chunk_id] = hit
    return sorted(best.values(), key=lambda h: h.score, reverse=True)[:k]


class StatuteWordingRetriever:
    """Search with the question and its statute wording, for evaluating retrieval on its own."""

    def __init__(self, retriever, rewrite):
        self.retriever = retriever
        self.rewrite = rewrite

    def search(self, query, k=5):
        return search_both(self.retriever, [query, self.rewrite(query)], k)


class RerankRetriever:
    def __init__(self, first_pass, score, candidates=CANDIDATES):
        self.first_pass = first_pass
        self.score = score
        self.candidates = candidates

    def search(self, query, k=5):
        hits = self.first_pass.search(query, k=self.candidates)
        if not hits:
            return []
        scores = self.score(query, [h.chunk["text"] for h in hits])
        ranked = sorted(zip(hits, scores), key=lambda pair: pair[1], reverse=True)[:k]
        return [Hit(h.chunk, float(s), h.parts) for h, s in ranked]
