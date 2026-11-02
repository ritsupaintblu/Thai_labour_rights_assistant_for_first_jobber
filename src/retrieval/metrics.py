"""Retrieval metrics for one query. `ranked` is best first, `relevant` a set, and each can be a section key.

Two parts of one section can both be returned, so a repeated item counts once.
"""

import math


def recall_at_k(ranked, relevant, k):
    return len(set(ranked[:k]) & relevant) / len(relevant)


def precision_at_k(ranked, relevant, k):
    return len(set(ranked[:k]) & relevant) / k


def reciprocal_rank(ranked, relevant):
    return next((1 / rank for rank, item in enumerate(ranked, start=1) if item in relevant), 0.0)


def ndcg_at_k(ranked, relevant, k):
    seen = set()
    dcg = 0.0
    for rank, item in enumerate(ranked[:k], start=1):
        if item in relevant and item not in seen:
            seen.add(item)
            dcg += 1 / math.log2(rank + 1)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
    return dcg / ideal
