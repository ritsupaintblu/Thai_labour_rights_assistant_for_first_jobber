"""Run from the project root: python -m unittest discover -s tests -t ."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.retrieval.bm25 import BM25Retriever, tokenize_raw, tokenize_thai
from src.retrieval.corpus import load_chunks
from src.retrieval.embeddings import EmbeddingRetriever, load_vectors, save_index
from src.retrieval.hybrid import RRF_K, HybridRetriever
from src.retrieval.metrics import ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank
from src.retrieval.rerank import RerankRetriever

CHUNKS = [
    {"chunk_id": "a", "text": "ลูกจ้างซึ่งเป็นหญิงมีครรภ์มีสิทธิลาเพื่อคลอดบุตร"},
    {"chunk_id": "b", "text": "ลูกจ้างมีสิทธิลาป่วยได้เท่าที่ป่วยจริง"},
    {"chunk_id": "c", "text": "นายจ้างต้องจ่ายค่าชดเชยเมื่อเลิกจ้าง"},
]
# one direction per chunk, so a query vector picks out its chunk
VECTORS = np.eye(3, dtype=np.float32)


def ids(hits):
    return [h.chunk["chunk_id"] for h in hits]


class Tokenizers(unittest.TestCase):
    def test_raw_only_splits_on_whitespace(self):
        self.assertEqual(tokenize_raw("ลาคลอดได้กี่วัน มาตรา 41"), ["ลาคลอดได้กี่วัน", "มาตรา", "41"])

    def test_thai_segments_words(self):
        self.assertIn("ค่าชดเชย", tokenize_thai("นายจ้างต้องจ่ายค่าชดเชย"))

    def test_thai_repairs_a_line_break_inside_a_word(self):
        self.assertIn("ค่าชดเชย", tokenize_thai("จ่ายค่าชด\nเชย"))

    def test_thai_drops_spaces_and_punctuation(self):
        self.assertEqual(tokenize_thai("มาตรา 41 - ลา"), ["มาตรา", "41", "ลา"])


class BM25(unittest.TestCase):
    def test_segmented_query_finds_a_chunk_raw_cannot(self):
        query = "เลิกจ้างได้ค่าชดเชยไหม"
        self.assertEqual(BM25Retriever(CHUNKS, tokenize_raw).search(query), [])
        self.assertEqual(ids(BM25Retriever(CHUNKS, tokenize_thai).search(query))[0], "c")

    def test_no_shared_term_returns_nothing(self):
        self.assertEqual(BM25Retriever(CHUNKS, tokenize_thai).search("ฟุตบอล"), [])

    def test_k_limits_the_results(self):
        self.assertEqual(len(BM25Retriever(CHUNKS, tokenize_thai).search("ลูกจ้างมีสิทธิ", k=1)), 1)


class Embedding(unittest.TestCase):
    def test_ranks_by_similarity(self):
        retriever = EmbeddingRetriever(CHUNKS, VECTORS, lambda q: np.array([0.1, 0.9, 0.2], dtype=np.float32))
        hits = retriever.search("q", k=2)
        self.assertEqual(ids(hits), ["b", "c"])
        self.assertAlmostEqual(hits[0].score, 0.9, places=5)

    def test_refuses_vectors_for_other_chunks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "index.npz"
            save_index(CHUNKS, VECTORS, path)
            self.assertEqual(load_vectors(CHUNKS, path).shape, (3, 3))
            with self.assertRaises(ValueError):
                load_vectors(CHUNKS[:2], path)

    def test_missing_index_says_how_to_build_it(self):
        with self.assertRaisesRegex(FileNotFoundError, "build_index"):
            load_vectors(CHUNKS, Path("does_not_exist.npz"))


class Hybrid(unittest.TestCase):
    def setUp(self):
        bm25 = BM25Retriever(CHUNKS, tokenize_thai)
        # the embedding side prefers chunk b, whatever the query says
        embedding = EmbeddingRetriever(CHUNKS, VECTORS, lambda q: np.array([0.1, 0.9, 0.2], dtype=np.float32))
        self.hybrid = HybridRetriever(bm25, embedding)

    def test_fuses_ranks_from_both_methods(self):
        # c is first in BM25 and second in embeddings; b is first in embeddings only
        hits = self.hybrid.search("ค่าชดเชย", k=3)
        self.assertEqual(ids(hits)[0], "c")
        self.assertAlmostEqual(hits[0].score, 1 / (RRF_K + 1) + 1 / (RRF_K + 2))

    def test_keeps_each_methods_score(self):
        hits = {h.chunk["chunk_id"]: h for h in self.hybrid.search("ค่าชดเชย", k=3)}
        self.assertEqual(set(hits["c"].parts), {"bm25", "embedding"})
        self.assertEqual(set(hits["b"].parts), {"embedding"})  # BM25 did not match it


class Rerank(unittest.TestCase):
    def setUp(self):
        first_pass = BM25Retriever(CHUNKS, tokenize_thai)
        # a scorer that prefers chunks mentioning sick leave, whatever BM25 thought
        score = lambda query, texts: [1.0 if "ลาป่วย" in t else 0.5 for t in texts]
        self.reranked = RerankRetriever(first_pass, score)

    def test_reorders_the_first_pass(self):
        hits = self.reranked.search("ลูกจ้างมีสิทธิลา", k=2)
        self.assertEqual(ids(hits)[0], "b")
        self.assertEqual(hits[0].score, 1.0)
        self.assertEqual(len(hits), 2)

    def test_no_candidates_does_not_call_the_scorer(self):
        self.assertEqual(self.reranked.search("ฟุตบอล"), [])


class Metrics(unittest.TestCase):
    # the worked examples from lecture 8
    def test_recall_and_precision(self):
        ranked, relevant = ["d2", "d7", "d5"], {"d7", "d9"}
        self.assertEqual(recall_at_k(ranked, relevant, 2), 0.5)
        self.assertEqual(precision_at_k(ranked, relevant, 2), 0.5)

    def test_recall_and_reciprocal_rank_can_disagree(self):
        ranked, relevant = ["d8", "d4", "d1"], {"d1"}
        self.assertEqual(recall_at_k(ranked, relevant, 2), 0)
        self.assertAlmostEqual(reciprocal_rank(ranked, relevant), 1 / 3)

    def test_ndcg(self):
        self.assertEqual(ndcg_at_k(["a", "b", "c"], {"a", "b"}, 5), 1)
        self.assertAlmostEqual(ndcg_at_k(["x", "a"], {"a"}, 5), 0.63093, places=4)

    def test_a_repeated_section_counts_once(self):
        ranked, relevant = ["a", "a", "x"], {"a", "b"}
        self.assertEqual(recall_at_k(ranked, relevant, 3), 0.5)
        self.assertAlmostEqual(precision_at_k(ranked, relevant, 3), 1 / 3)
        self.assertLess(ndcg_at_k(ranked, relevant, 3), 1)

    def test_no_hit_scores_zero(self):
        self.assertEqual(reciprocal_rank(["x"], {"a"}), 0)
        self.assertEqual(ndcg_at_k(["x"], {"a"}, 5), 0)


class Corpus(unittest.TestCase):
    def test_only_in_force_chunks_are_loaded(self):
        rows = [{"chunk_id": "a", "status": "in_force"}, {"chunk_id": "b", "status": "superseded"},
                {"chunk_id": "c", "status": "repealed"}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "chunks.jsonl"
            path.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
            self.assertEqual([c["chunk_id"] for c in load_chunks(path)], ["a"])


if __name__ == "__main__":
    unittest.main()
