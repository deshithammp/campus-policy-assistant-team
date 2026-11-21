from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Chunk:
    id: str
    document: str
    page: int
    text: str

    @property
    def source(self) -> str:
        return f"{self.document}, p. {self.page}"


@dataclass(frozen=True)
class Cosine:
    dot: float
    query_norm: float
    chunk_norm: float
    score: float


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    cosine: Cosine
    sparse: float
    score: float


@dataclass(frozen=True)
class Claim:
    text: str
    chunk_id: str
    quote: str


@dataclass
class Result:
    question: str
    claims: list[Claim] = field(default_factory=list)
    evidence: list[Hit] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    def answer(self) -> str:
        sources = {hit.chunk.id: hit.chunk.source for hit in self.evidence}
        lines = [f"- {claim.text} [{sources[claim.chunk_id]}]" for claim in self.claims]
        if self.missing:
            lines += ["The indexed PDFs did not provide enough evidence for: " + " | ".join(self.missing)]
        return "\n".join(lines)


class Embedder(Protocol):
    signature: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Search(Protocol):
    def search(self, query: str, limit: int) -> list[Hit]: ...


class Synthesizer(Protocol):
    def answer(self, question: str, evidence: list[Claim]) -> list[Claim]: ...
