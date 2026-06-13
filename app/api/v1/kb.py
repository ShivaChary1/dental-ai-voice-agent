import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import AuthedUser, DbSession
from app.db.models import KBDocument
from app.schemas.kb import KBDocumentCreate, KBDocumentOut, KBSearchRequest, KBSearchResult
from app.services import kb_service

router = APIRouter(prefix="/kb", tags=["knowledge-base"])


@router.get("/documents", response_model=list[KBDocumentOut])
async def list_documents(db: DbSession, user: AuthedUser) -> list[KBDocument]:
    stmt = select(KBDocument).where(KBDocument.clinic_id == user.clinic_id).order_by(KBDocument.created_at.desc())
    return list((await db.scalars(stmt)).all())


@router.post("/documents", response_model=KBDocumentOut, status_code=status.HTTP_201_CREATED)
async def create_document(payload: KBDocumentCreate, db: DbSession, user: AuthedUser) -> KBDocument:
    return await kb_service.index_document(
        db,
        clinic_id=user.clinic_id,
        title=payload.title,
        content=payload.content,
        language=payload.language,
        source=payload.source,
    )


@router.post("/documents/{document_id}/reindex", response_model=KBDocumentOut)
async def reindex_document(document_id: uuid.UUID, db: DbSession, user: AuthedUser) -> KBDocument:
    document = await kb_service.reindex_document(db, clinic_id=user.clinic_id, document_id=document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, db: DbSession, user: AuthedUser) -> None:
    document = await db.get(KBDocument, document_id)
    if document is None or document.clinic_id != user.clinic_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    await db.delete(document)
    await db.commit()


@router.post("/search", response_model=list[KBSearchResult])
async def search(payload: KBSearchRequest, db: DbSession, user: AuthedUser) -> list[KBSearchResult]:
    results = await kb_service.search_kb(
        db, clinic_id=user.clinic_id, query=payload.query, language=payload.language, top_k=payload.top_k
    )
    return [KBSearchResult(**r) for r in results]
