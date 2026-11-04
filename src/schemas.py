"""The answer format. Draft is what the model may say; Answer adds the facts only code may fill in."""

from typing import Literal

from pydantic import BaseModel, Field


class CitationRef(BaseModel):
    law: str
    section: str


class Draft(BaseModel):
    answer: str = Field(min_length=1)
    citations: list[CitationRef] = []
    confidence: Literal["high", "medium", "low"] = "medium"
    not_found: bool = False
    clarifying_question: str | None = None
    correction: str | None = None


class Citation(BaseModel):
    """A law section, or for a rate, the announcement's clause with law left empty."""
    law: str | None
    section: str
    amendment_no: int | None = None
    effective_date: str | None = None
    source: str


class Calculation(BaseModel):
    kind: str
    value: float
    unit: str
    formula: str
    legal_basis: str
    explanation: str = ""  # each step in Thai, written by calculate, not the model


class Answer(BaseModel):
    answer: str
    citations: list[Citation] = []
    calculation: Calculation | None = None
    as_of: str
    confidence: Literal["high", "medium", "low"]
    not_found: bool = False
    clarifying_question: str | None = None
    correction: str | None = None
