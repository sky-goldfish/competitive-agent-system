import json
import threading
from contextvars import ContextVar
from datetime import datetime
from uuid import uuid4

from app.db.models import CallTrace
from app.db.session import SessionLocal

_trace_ctx: ContextVar[dict | None] = ContextVar("call_trace_ctx", default=None)
_trace_buffer: list[CallTrace] = []
_buffer_lock = threading.Lock()
_FLUSH_THRESHOLD = 5


def set_trace_context(run_id: str, stage: str = "") -> None:
    flush_traces()
    _trace_ctx.set({"run_id": run_id, "stage": stage})


def update_stage(stage: str) -> None:
    ctx = _trace_ctx.get()
    if ctx is not None:
        ctx["stage"] = stage
    flush_traces()


def clear_trace_context() -> None:
    flush_traces()
    _trace_ctx.set(None)


def flush_traces() -> None:
    with _buffer_lock:
        if not _trace_buffer:
            return
        items = list(_trace_buffer)
        _trace_buffer.clear()
    db = SessionLocal()
    try:
        db.add_all(items)
        db.commit()
    finally:
        db.close()


def get_trace_context() -> dict | None:
    return _trace_ctx.get()


def set_worker_trace_context(ctx: dict | None) -> None:
    if ctx is not None:
        _trace_ctx.set(ctx)


def _get_ctx() -> dict | None:
    return _trace_ctx.get()


def _add_trace(trace: CallTrace) -> None:
    should_flush = False
    with _buffer_lock:
        _trace_buffer.append(trace)
        if len(_trace_buffer) >= _FLUSH_THRESHOLD:
            should_flush = True
    if should_flush:
        flush_traces()


def record_llm_call(
    *,
    provider: str,
    model: str,
    input_data: dict,
    output_data: dict,
    token_count: int | None,
    duration_ms: int,
    started_at: datetime,
    status: str = "completed",
    error: str | None = None,
) -> None:
    ctx = _get_ctx()
    if ctx is None:
        return
    _write_call(
        run_id=ctx["run_id"],
        stage=ctx.get("stage", ""),
        call_type="llm",
        provider=provider,
        model=model,
        input_data=input_data,
        output_data=output_data,
        token_count=token_count,
        duration_ms=duration_ms,
        started_at=started_at,
        status=status,
        error=error,
    )


def record_search_call(
    *,
    provider: str,
    input_data: dict,
    output_data: dict,
    duration_ms: int,
    started_at: datetime,
    status: str = "completed",
    error: str | None = None,
) -> None:
    ctx = _get_ctx()
    if ctx is None:
        return
    _write_call(
        run_id=ctx["run_id"],
        stage=ctx.get("stage", ""),
        call_type="search",
        provider=provider,
        model=None,
        input_data=input_data,
        output_data=output_data,
        token_count=None,
        duration_ms=duration_ms,
        started_at=started_at,
        status=status,
        error=error,
    )


def _write_call(
    *,
    run_id: str,
    stage: str,
    call_type: str,
    provider: str,
    model: str | None,
    input_data: dict,
    output_data: dict,
    token_count: int | None,
    duration_ms: int,
    started_at: datetime,
    status: str,
    error: str | None,
) -> None:
    ended_at = datetime.utcnow()
    trace = CallTrace(
        id=f"{'llmcall' if call_type == 'llm' else 'srccall'}_{uuid4().hex[:12]}",
        run_id=run_id,
        stage=stage,
        call_type=call_type,
        provider=provider,
        model=model,
        input_json=json.dumps(input_data, ensure_ascii=False, default=str),
        output_json=json.dumps(output_data, ensure_ascii=False, default=str),
        token_count=token_count,
        duration_ms=duration_ms,
        status=status,
        error_message=error,
        started_at=started_at,
        ended_at=ended_at,
    )
    _add_trace(trace)
