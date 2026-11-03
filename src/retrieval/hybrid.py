"""Hybrid retrieval: reciprocal rank fusion of BM25 + PyThaiNLP and embeddings, and the four variants to compare.

Fusion uses ranks because BM25 scores and cosine similarities are not on the same scale.
"""

from src.retrieval.bm25 import BM25Retriever, tokenize_raw, tokenize_thai
from src.retrieval.corpus import Hit, load_chunks
from src.retrieval.embeddings import EmbeddingRetriever, encode, load_model, load_vectors
from src.retrieval.rerank import AGENT_CANDIDATES, LIVE_CANDIDATES, RerankRetriever, load_scorer

RRF_K = 60  # the constant from the original RRF paper (Cormack et al., 2009)
SEARCH_VARIANT = "reranked_live"  # what plain RAG uses
AGENT_VARIANT = "reranked_10"  # what the agent searches each wording with


class HybridRetriever:
    def __init__(self, bm25, embedding):
        self.methods = {"bm25": bm25, "embedding": embedding}

    def search(self, query, k=5):
        chunks, fused, parts = {}, {}, {}
        for name, retriever in self.methods.items():
            # every chunk, so a chunk only one method ranks highly still has its score from the other
            for rank, hit in enumerate(retriever.search(query, k=len(retriever.chunks)), start=1):
                chunk_id = hit.chunk["chunk_id"]
                chunks[chunk_id] = hit.chunk
                fused[chunk_id] = fused.get(chunk_id, 0) + 1 / (RRF_K + rank)
                parts.setdefault(chunk_id, {})[name] = hit.score
        ranked = sorted(fused, key=fused.get, reverse=True)[:k]
        return [Hit(chunks[i], fused[i], parts[i]) for i in ranked]


def build_retrievers():
    """The variants by name. Needs the index from scripts/build_index.py and loads the embedding and reranking models."""
    chunks = load_chunks()
    model = load_model()
    thai = BM25Retriever(chunks, tokenize_thai)
    embedding = EmbeddingRetriever(chunks, load_vectors(chunks), lambda query: encode(model, [query])[0])
    hybrid = HybridRetriever(thai, embedding)
    score = load_scorer()
    return {
        "bm25_raw": BM25Retriever(chunks, tokenize_raw),
        "bm25_pythainlp": thai,
        "embedding": embedding,
        "hybrid": hybrid,
        "reranked": RerankRetriever(hybrid, score),
        SEARCH_VARIANT: RerankRetriever(hybrid, score, LIVE_CANDIDATES),
        AGENT_VARIANT: RerankRetriever(hybrid, score, AGENT_CANDIDATES),
    }
