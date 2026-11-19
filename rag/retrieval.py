import json
import math
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from .domain import Chunk, Cosine, Embedder, Hit, Result
from .text import terms


def cosine(query, chunk):
    if len(query) != len(chunk):
        raise ValueError('Embedding dimensions changed. Rebuild the index for the configured model.')
    dot = math.fsum(a * b for a, b in zip(query, chunk))
    query_norm = math.sqrt(math.fsum(a * a for a in query))
    chunk_norm = math.sqrt(math.fsum(b * b for b in chunk))
    score = dot / (query_norm * chunk_norm) if query_norm and chunk_norm else 0.0
    return Cosine(dot, query_norm, chunk_norm, max(-1.0, min(1.0, score)))


class VectorStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, document TEXT, page INTEGER, text TEXT, vector TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, result TEXT NOT NULL)')

    def replace(self, signature: str, entries: list[tuple[Chunk, list[float]]]):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM chunks')
            db.executemany('INSERT INTO chunks VALUES (?, ?, ?, ?, ?)', [
                (chunk.id, chunk.document, chunk.page, chunk.text, json.dumps(vector)) for chunk, vector in entries
            ])
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?, ?)', ('embedder', signature))

    def load(self, signature: str):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('BEGIN')
            row = db.execute("SELECT value FROM metadata WHERE key = 'embedder'").fetchone()
            if row is None:
                raise ValueError('No indexed PDFs. Run the ingest command first.')
            if row[0] != signature:
                raise ValueError(f'Index uses {row[0]}. Run ingest for {signature} or pick a separate --db path.')
            return [(Chunk(*record[:4]), json.loads(record[4])) for record in db.execute('SELECT * FROM chunks')]

    def save_run(self, result: Result) -> int:
        with closing(sqlite3.connect(self.path)) as db, db:
            cursor = db.execute('INSERT INTO runs (result) VALUES (?)', (json.dumps(asdict(result)),))
            return cursor.lastrowid

    def recent(self, limit: int) -> list[dict]:
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute('SELECT id, created_at, result FROM runs ORDER BY id DESC LIMIT ?', (limit,))
            return [dict(id=number, timestamp=stamp, **json.loads(result)) for number, stamp, result in rows]


class HybridRetriever:
    def __init__(self, store: VectorStore, embedder: Embedder, dense_weight: float = 0.65):
        self.embedder = embedder
        self.dense_weight = dense_weight
        entries = store.load(embedder.signature)
        counts = [Counter(terms(chunk.text)) for chunk, _ in entries]
        document_frequency = Counter(word for count in counts for word in count)
        self.idf = {word: 1 + math.log((len(entries) + 1) / (frequency + 1)) for word, frequency in document_frequency.items()}
        self.entries = [(chunk, vector, self._weights(count)) for (chunk, vector), count in zip(entries, counts)]

    def _weights(self, count):
        return {word: (1 + math.log(frequency)) * self.idf[word] for word, frequency in count.items() if word in self.idf}

    @staticmethod
    def _sparse_cosine(query, document):
        dot = math.fsum(weight * document.get(word, 0.0) for word, weight in query.items())
        norm = math.sqrt(math.fsum(weight ** 2 for weight in query.values()) * math.fsum(weight ** 2 for weight in document.values()))
        return dot / norm if norm else 0.0

    def search(self, query: str, limit: int = 4) -> list[Hit]:
        query_vector = self.embedder.embed([query])[0]
        query_sparse = self._weights(Counter(terms(query)))
        hits = []
        for chunk, vector, sparse_vector in self.entries:
            math_trace = cosine(query_vector, vector)
            sparse = self._sparse_cosine(query_sparse, sparse_vector)
            score = self.dense_weight * max(0, math_trace.score) + (1 - self.dense_weight) * sparse
            if score > 0:
                hits.append(Hit(chunk, math_trace, sparse, score))
        return sorted(hits, key=lambda item: (-item.score, item.chunk.id))[:limit]
