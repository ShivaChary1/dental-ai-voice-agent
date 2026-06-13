import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import AuthedUser, DbSession
from app.db.models import CallSession, CallTurn
from app.schemas.calls import CallLatencySummary, CallSessionDetail, CallSessionOut, CallTurnOut

router = APIRouter(prefix="/calls", tags=["calls"])


@router.get("", response_model=list[CallSessionOut])
async def list_calls(
    db: DbSession,
    user: AuthedUser,
    status_filter: str | None = Query(default=None, alias="status"),
    outcome: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> list[CallSession]:
    stmt = select(CallSession).where(CallSession.clinic_id == user.clinic_id)
    if status_filter:
        stmt = stmt.where(CallSession.status == status_filter)
    if outcome:
        stmt = stmt.where(CallSession.outcome == outcome)
    stmt = stmt.order_by(CallSession.started_at.desc()).limit(limit).offset(offset)
    return list((await db.scalars(stmt)).all())


@router.get("/{call_id}", response_model=CallSessionDetail)
async def get_call(call_id: uuid.UUID, db: DbSession, user: AuthedUser) -> CallSessionDetail:
    call = await db.get(CallSession, call_id)
    if call is None or call.clinic_id != user.clinic_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Call not found")

    turns_stmt = (
        select(CallTurn).where(CallTurn.call_session_id == call_id).order_by(CallTurn.turn_index)
    )
    turns = list((await db.scalars(turns_stmt)).all())

    return CallSessionDetail(
        **CallSessionOut.model_validate(call).model_dump(),
        turns=[CallTurnOut.model_validate(t) for t in turns],
    )


@router.get("/{call_id}/transcript", response_model=list[CallTurnOut])
async def get_transcript(call_id: uuid.UUID, db: DbSession, user: AuthedUser) -> list[CallTurn]:
    call = await db.get(CallSession, call_id)
    if call is None or call.clinic_id != user.clinic_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Call not found")

    stmt = select(CallTurn).where(CallTurn.call_session_id == call_id).order_by(CallTurn.turn_index)
    return list((await db.scalars(stmt)).all())


@router.get("/{call_id}/latency", response_model=CallLatencySummary)
async def get_latency(call_id: uuid.UUID, db: DbSession, user: AuthedUser) -> CallLatencySummary:
    call = await db.get(CallSession, call_id)
    if call is None or call.clinic_id != user.clinic_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Call not found")

    stmt = select(CallTurn).where(
        CallTurn.call_session_id == call_id, CallTurn.role == "assistant", CallTurn.total_ms.is_not(None)
    )
    turns = list((await db.scalars(stmt)).all())

    if not turns:
        return CallLatencySummary(
            call_session_id=call_id,
            turn_count=0,
            avg_total_ms=None,
            p50_total_ms=None,
            p95_total_ms=None,
            avg_stt_ms=None,
            avg_llm_ms=None,
            avg_tts_first_byte_ms=None,
        )

    totals = sorted(t.total_ms for t in turns)

    def _percentile(values: list[int], pct: float) -> float:
        idx = min(len(values) - 1, int(len(values) * pct))
        return float(values[idx])

    def _avg(values: list[int | None]) -> float | None:
        present = [v for v in values if v is not None]
        return sum(present) / len(present) if present else None

    return CallLatencySummary(
        call_session_id=call_id,
        turn_count=len(turns),
        avg_total_ms=_avg(totals),
        p50_total_ms=_percentile(totals, 0.5),
        p95_total_ms=_percentile(totals, 0.95),
        avg_stt_ms=_avg([t.stt_ms for t in turns]),
        avg_llm_ms=_avg([t.llm_ms for t in turns]),
        avg_tts_first_byte_ms=_avg([t.tts_first_byte_ms for t in turns]),
    )
