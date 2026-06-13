"""Clinic knowledge-base indexing and retrieval (pgvector-backed RAG)."""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KBChunk, KBDocument
from app.services.embeddings import embed_documents, embed_query

_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 150


def _split_into_chunks(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Paragraph-aware sliding-window chunker.

    Clinic FAQ/policy docs are short, so this simple approach avoids pulling in
    a heavy text-splitting dependency.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 1 <= size:
            current = f"{current}\n{para}".strip()
        else:
            if current:
                chunks.append(current)
            if len(para) <= size:
                current = para
            else:
                for i in range(0, len(para), size - overlap):
                    chunks.append(para[i : i + size])
                current = ""
    if current:
        chunks.append(current)
    return chunks


async def index_document(
    db: AsyncSession,
    *,
    clinic_id: uuid.UUID,
    title: str,
    content: str,
    language: str = "en-IN",
    source: str | None = None,
) -> KBDocument:
    document = KBDocument(
        clinic_id=clinic_id, title=title, content=content, language=language, source=source
    )
    db.add(document)
    await db.flush()

    chunks = _split_into_chunks(content)
    if chunks:
        embeddings = await embed_documents(chunks)
        for chunk_text, embedding in zip(chunks, embeddings, strict=True):
            db.add(
                KBChunk(
                    document_id=document.id,
                    clinic_id=clinic_id,
                    chunk_text=chunk_text,
                    language=language,
                    embedding=embedding,
                    chunk_metadata={"title": title, "source": source},
                )
            )

    await db.commit()
    await db.refresh(document)
    return document


async def reindex_document(db: AsyncSession, *, clinic_id: uuid.UUID, document_id: uuid.UUID) -> KBDocument | None:
    document = await db.scalar(
        select(KBDocument).where(KBDocument.id == document_id, KBDocument.clinic_id == clinic_id)
    )
    if document is None:
        return None

    await db.execute(
        KBChunk.__table__.delete().where(KBChunk.document_id == document_id)
    )

    chunks = _split_into_chunks(document.content)
    if chunks:
        embeddings = await embed_documents(chunks)
        for chunk_text, embedding in zip(chunks, embeddings, strict=True):
            db.add(
                KBChunk(
                    document_id=document.id,
                    clinic_id=clinic_id,
                    chunk_text=chunk_text,
                    language=document.language,
                    embedding=embedding,
                    chunk_metadata={"title": document.title, "source": document.source},
                )
            )

    await db.commit()
    return document


async def search_kb(
    db: AsyncSession,
    *,
    clinic_id: uuid.UUID,
    query: str,
    top_k: int = 4,
    language: str | None = None,
) -> list[dict]:
    """Cosine-similarity search over the clinic's KB chunks.

    Returns dicts (not ORM rows) so this can be called directly from a
    LangGraph tool without leaking session-bound objects.
    """
    query_embedding = await embed_query(query)

    stmt = (
        select(
            KBChunk.id,
            KBChunk.document_id,
            KBChunk.chunk_text,
            KBDocument.title,
            KBChunk.embedding.cosine_distance(query_embedding).label("distance"),
        )
        .join(KBDocument, KBDocument.id == KBChunk.document_id)
        .where(KBChunk.clinic_id == clinic_id)
    )
    if language:
        stmt = stmt.where(KBChunk.language == language)

    stmt = stmt.order_by("distance").limit(top_k)

    rows = (await db.execute(stmt)).all()
    return [
        {
            "chunk_id": row.id,
            "document_id": row.document_id,
            "title": row.title,
            "chunk_text": row.chunk_text,
            "score": 1 - row.distance,
        }
        for row in rows
    ]
