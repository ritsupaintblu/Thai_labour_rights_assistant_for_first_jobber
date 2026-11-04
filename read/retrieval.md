# Retrieval: What Was Done

Nov 2, 2026 · @riri

## Summary

Eight retrieval variants were built and scored on the 82 questions with gold sections. The agent's variant, `statute_both`, finds a gold section in the top 5 for 90% of them.

| Variant | Method | recall@5 | MRR | Seconds per query (CPU) |
| --- | --- | ---: | ---: | ---: |
| `bm25_raw` | BM25, whitespace split (baseline) | 0.018 | 0.015 | 0.00 |
| `bm25_pythainlp` | BM25 with PyThaiNLP `newmm` segmentation | 0.504 | 0.357 | 0.01 |
| `embedding` | `BAAI/bge-m3` cosine similarity | 0.764 | 0.683 | 0.29 |
| `hybrid` | Reciprocal rank fusion (k = 60) of the two above | 0.713 | 0.579 | 0.27 |
| `reranked` | Top 50 of `hybrid`, reranked by `BAAI/bge-reranker-v2-m3` | 0.841 | 0.812 | 35.58 |
| `reranked_live` | The same with the top 20 (plain RAG) | 0.795 | 0.755 | about 21 |
| `reranked_10` | The same with the top 10 | 0.740 | 0.740 | not measured |
| **`statute_both`** | `reranked_10` on the question and its statute wording (agent) | **0.900** | 0.797 | about 21 |

| File | Change |
| --- | --- |
| `scripts/build_index.py` | New: embeds in-force chunks into `data/index/embeddings.npz` (not committed) |
| `src/retrieval/` | New: `corpus`, `bm25`, `embeddings`, `hybrid`, `rerank`, `metrics` |
| `eval/run_retrieval.py`, `eval/results_retrieval.csv` | Eval 1: recall@k, precision@k, MRR, nDCG, overall and by question type |
| `eval/sweep_min_score.py` | Chooses the refusal floor for plain RAG |
| `tests/test_retrieval.py` | New: 20 tests |

## Problems found and fixes

| Problem | Fix |
| --- | --- |
| Thai has no spaces, so raw BM25 found almost nothing (recall@5 0.018) | Segment words with PyThaiNLP `newmm` |
| PDF line breaks fall inside Thai words | Removed before segmenting |
| Hybrid scored below embeddings alone (0.713 vs 0.764) | Rerank its top candidates with a cross-encoder |
| Reranking 50 took 35.6 s a query on CPU | 20 candidates for plain RAG; the agent reranks 10 for each of its two wordings |
| Everyday wording scored low: one section got 0.035 for one wording and 0.999 for another | The model rewrites the question in statute wording; each section keeps its best score across both |
| A rank-fusion score says nothing about relevance | Each hit keeps every method's own score in `parts` |
| An index could be stale after rebuilding chunks or changing the model | The index stores chunk IDs and the model revision; a mismatch is refused |
| Upstream models can change | Both models are pinned to a revision |
| Repeated questions reranked again | Scores are cached in `data/index/` by model revision, query and text |
| A score floor refused answerable questions: at the best floor, 0.10, it refused 16 of 18 out-of-scope but also 12 of 82 answerable | Plain RAG keeps 0.10; the agent refuses from the content instead |

## How it works now

1. `build_index.py` embeds every `in_force` chunk with `bge-m3`. The first run downloads the model (4.3 GB).
2. A query is scored by BM25 + PyThaiNLP and by embeddings over all chunks, then fused with RRF.
3. The top candidates are reranked by `bge-reranker-v2-m3`, which gives a relevance score from 0 to 1.

Only `in_force` chunks are searched. Two parts of a long section can both appear.

```python
from src.retrieval.hybrid import build_retrievers

hits = build_retrievers()["reranked"].search("ลาคลอดได้กี่วัน", k=5)
```

## Verification

| Check | Result |
| --- | --- |
| `tests/test_retrieval.py` | 20 tests pass |
| Questions with no gold section in the `reranked` top 5 | 9; five of them (`T09`, `T16`, `T17`, `T20`, `C20`) take their figures from rate announcements, which `get_rate` covers |

## Open issues

| Issue | Effect | Next step |
| --- | --- | --- |
| The settings were chosen on the same 82 questions | Scores may be optimistic | Score retrieval on the held-out sets |
| Times in `results_retrieval.csv` reuse cached scores | They are not real search times | Time a cold run |
| Reranking takes about 21 s a question | Most of the API's response time | A GPU or a smaller reranker |
| Chunks flagged `partly_amended_by` are still searched | Outdated paragraphs of two Acts can be returned | Filter or merge them |

To build the index and score retrieval:

```bash
python scripts/build_index.py
python eval/run_retrieval.py
python eval/sweep_min_score.py
```
