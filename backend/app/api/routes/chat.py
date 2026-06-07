from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.chat import ChatMessageResponse, ChatRequest, ChatResponse
from app.services.chat_service import (
    ChatError,
    list_chat_messages,
)
from app.services.revision_service import create_revision, execute_revision_run

router = APIRouter(prefix="/runs/{run_id}/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def send_chat_message(
    run_id: str,
    payload: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        revision, message = create_revision(db, run_id, payload.message)
        background_tasks.add_task(execute_revision_run, revision.id)
        return ChatResponse(
            message=ChatMessageResponse.model_validate(message),
            report_version=message.report_version,
            intent=message.intent,
            action_type=message.action_type,
        )
    except ChatError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("", response_model=list[ChatMessageResponse])
def get_chat_messages(run_id: str, db: Session = Depends(get_db)):
    messages = list_chat_messages(db, run_id)
    return [ChatMessageResponse.model_validate(msg) for msg in messages]
