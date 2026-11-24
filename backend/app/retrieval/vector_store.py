"""Semantic Pgvector retrieval using a local 384-dimensional FastEmbed model."""
from __future__ import annotations

from functools import lru_cache

from sqlalchemy import text

from app.db.database import engine

EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _embedding_model():
    # Model weights are fetched on first use and then cached by FastEmbed.
    from fastembed import TextEmbedding

    return TextEmbedding(model_name="BAAI/bge-small-en-v1.5")


def embed_text(value: str) -> list[float]:
    vector = next(iter(_embedding_model().embed([value])))
    if len(vector) != EMBEDDING_DIM:
        raise ValueError(f"Expected {EMBEDDING_DIM}-dimension embedding, received {len(vector)}")
    return [float(v) for v in vector]


def upsert_document(title: str, body: str, source: str, jurisdiction: str, version: str,
                    effective_date: str | None = None) -> None:
    vector = _to_pgvector_literal(embed_text(f"{title}\n{body}"))
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO knowledge_base (title, body, source, jurisdiction, version, effective_date, embedding)
            VALUES (:title, :body, :source, :jurisdiction, :version, :effective_date, CAST(:embedding AS vector))
        """), {"title": title, "body": body, "source": source, "jurisdiction": jurisdiction,
               "version": version, "effective_date": effective_date, "embedding": vector})


def search_knowledge_base(query: str, top_k: int = 4, jurisdiction: str | None = None) -> list[dict]:
    vector = _to_pgvector_literal(embed_text(query))
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT id, title, body, source, jurisdiction, effective_date, version,
                   (embedding <=> CAST(:embedding AS vector)) AS distance
            FROM knowledge_base
            WHERE embedding IS NOT NULL
              AND (:jurisdiction IS NULL OR jurisdiction IS NULL OR jurisdiction = 'GLOBAL' OR jurisdiction = :jurisdiction)
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """), {"embedding": vector, "top_k": top_k, "jurisdiction": jurisdiction}).mappings().all()
    result = []
    for row in rows:
        item = dict(row)
        item["similarity"] = max(0.0, min(1.0, 1.0 - float(item.pop("distance"))))
        result.append(item)
    return result


def _to_pgvector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in vec) + "]"
