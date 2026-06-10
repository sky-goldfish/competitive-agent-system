from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.models import KnowledgeItem
from app.db.session import get_db
from app.schemas.knowledge import (
    KnowledgeClearResponse,
    KnowledgeItemResponse,
    KnowledgeRebuildResponse,
)
from app.services.knowledge_service import search_knowledge, upsert_from_evidence

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/items", response_model=list[KnowledgeItemResponse])
def list_knowledge_items(
    q: str | None = Query(default=None),
    product_name: str | None = Query(default=None),
    dimension: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return search_knowledge(
        db,
        query=q,
        product_names=[product_name] if product_name else None,
        dimensions=[dimension] if dimension else None,
        limit=limit,
    )


@router.get("/items/{item_id}", response_model=KnowledgeItemResponse)
def get_knowledge_item(item_id: str, db: Session = Depends(get_db)):
    item = db.get(KnowledgeItem, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge item not found."
        )
    return item


@router.delete("/items", response_model=KnowledgeClearResponse)
def clear_knowledge_items(db: Session = Depends(get_db)):
    deleted_count = db.query(KnowledgeItem).delete(synchronize_session=False)
    db.commit()
    return KnowledgeClearResponse(deleted_count=deleted_count)


@router.post(
    "/rebuild-from-run/{run_id}",
    response_model=KnowledgeRebuildResponse,
)
def rebuild_knowledge_from_run(run_id: str, db: Session = Depends(get_db)):
    try:
        result = upsert_from_evidence(db, run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return KnowledgeRebuildResponse(
        run_id=result.run_id,
        created_count=result.created_count,
        updated_count=result.updated_count,
        skipped_count=result.skipped_count,
    )
