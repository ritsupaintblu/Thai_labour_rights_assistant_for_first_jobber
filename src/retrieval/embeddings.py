"""Dense retrieval: cosine similarity between the query and the vectors from scripts/build_index.py."""

import numpy as np

from src.retrieval.corpus import ROOT, Hit

MODEL = "BAAI/bge-m3"
MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"  # pinned so the vectors can be rebuilt exactly
INDEX = ROOT / "data" / "index" / "embeddings.npz"


def load_model():
    # imported here because it is slow, and BM25 and the tests do not need it
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL, revision=MODEL_REVISION)


def encode(model, texts):
    """Unit vectors, so a dot product is the cosine similarity."""
    return model.encode(texts, batch_size=16, normalize_embeddings=True, convert_to_numpy=True).astype(np.float32)


def save_index(chunks, vectors, path=INDEX):
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, vectors=vectors, chunk_ids=np.array([c["chunk_id"] for c in chunks]), model=np.array(MODEL_REVISION))


def load_vectors(chunks, path=INDEX):
    """The saved vectors, refused if they do not line up with these chunks or this model."""
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist. Run: python scripts/build_index.py")
    with np.load(path) as saved:
        if saved["chunk_ids"].tolist() != [c["chunk_id"] for c in chunks] or saved["model"].item() != MODEL_REVISION:
            raise ValueError(f"{path} is out of date. Run: python scripts/build_index.py")
        return saved["vectors"]


class EmbeddingRetriever:
    def __init__(self, chunks, vectors, encode_query):
        self.chunks = chunks
        self.vectors = vectors
        self.encode_query = encode_query

    def search(self, query, k=5):
        scores = self.vectors @ self.encode_query(query)
        ranked = np.argsort(-scores, kind="stable")[:k]
        return [Hit(self.chunks[i], float(scores[i])) for i in ranked]
