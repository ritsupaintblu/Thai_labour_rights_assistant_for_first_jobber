"""Embed the in-force chunks into data/index/embeddings.npz. Rerun after rebuilding the chunks.

BM25 needs no saved index: it is built from the chunks at startup.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.retrieval.corpus import ROOT, load_chunks
from src.retrieval.embeddings import INDEX, encode, load_model, save_index


def main():
    chunks = load_chunks()
    vectors = encode(load_model(), [c["text"] for c in chunks])
    save_index(chunks, vectors)
    print(f"Embedded {len(chunks)} chunks into {INDEX.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
