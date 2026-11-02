"""The chunks retrieval may return, and the result type every retriever shares."""

import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHUNKS = ROOT / "data" / "processed" / "chunks.jsonl"


@dataclass(frozen=True)
class Hit:
    chunk: dict
    score: float
    # hybrid and reranked: the score from each first-pass method, because a rank fusion score says nothing about relevance
    parts: dict = field(default_factory=dict)


def load_chunks(path=CHUNKS):
    """Only in-force text: superseded and repealed sections must never reach an answer."""
    with open(path, encoding="utf-8") as f:
        return [c for c in map(json.loads, f) if c["status"] == "in_force"]
