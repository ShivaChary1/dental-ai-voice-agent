"""LiveKit Agents worker entrypoint for the dental clinic voice assistant.

Run with:
    python -m app.voice.worker dev      # connect to a local/dev LiveKit room
    python -m app.voice.worker start    # production worker, polls for jobs

Room naming contract (web-widget v1, no SIP/PSTN):
    The frontend that issues the LiveKit access token names the room
    "<clinic_slug>--<anything>" and may attach JSON job metadata:
        {"language": "hi-IN", "caller_phone": "+91..."}
    `language` defaults to the clinic's `default_language`; `caller_phone` is
    optional (web callers may not have one) and is only used to look up/create
    a patient record once they give their number in conversation.
"""

import json
import time
from datetime import datetime

from dotenv import load_dotenv
from livekit.agents import AgentSession, JobContext, RoomInputOptions, WorkerOptions, cli
from livekit.plugins import sarvam, silero
from sqlalchemy import select

from app.agent.graph import get_final_state
from app.agent.prompts import build_system_prompt
from app.db.models import CallSession, CallTurn, Clinic
from app.db.session import AsyncSessionLocal
from app.logging_config import configure_logging, get_logger
from app.services.realtime import publish_call_event
from app.voice.agent import DentalClinicAgent

load_dotenv()
configure_logging()
logger = get_logger(__name__)


async def _resolve_clinic(db, room_name: str) -> Clinic | None:
    slug = room_name.split("--", 1)[0]
    return await db.scalar(select(Clinic).where(Clinic.slug == slug))


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    job_metadata: dict = {}
    if ctx.job.metadata:
        try:
            job_metadata = json.loads(ctx.job.metadata)
        except json.JSONDecodeError:
            logger.warning("invalid_job_metadata", raw=ctx.job.metadata)

    async with AsyncSessionLocal() as db:
        clinic = await _resolve_clinic(db, ctx.room.name)
        if clinic is None:
            logger.error("unknown_clinic_for_room", room=ctx.room.name)
            return

        language = job_metadata.get("language") or clinic.default_language
        caller_phone = job_metadata.get("caller_phone")

        call_session = CallSession(
            clinic_id=clinic.id,
            room_name=ctx.room.name,
            caller_id=caller_phone,
            language=language,
            status="active",
        )
        db.add(call_session)
        await db.commit()
        await db.refresh(call_session)

    instructions = build_system_prompt(clinic, language)
    agent = DentalClinicAgent(
        clinic=clinic, language=language, call_session_id=call_session.id, instructions=instructions
    )

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=sarvam.STT(language=language, model="saaras:v3", high_vad_sensitivity=True),
        tts=sarvam.TTS(target_language_code=language, model="bulbul:v3", speech_sample_rate=22050),
    )

    turn_index = 0
    turn_started_at: float | None = None
    pending_metrics: dict[str, float] = {}

    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:
        m = ev.metrics
        kind = type(m).__name__
        if kind == "EOUMetrics":
            pending_metrics["stt_ms"] = round(getattr(m, "end_of_utterance_delay", 0.0) * 1000)
        elif kind == "LLMMetrics":
            pending_metrics["llm_ms"] = round(getattr(m, "ttft", 0.0) * 1000)
        elif kind == "TTSMetrics":
            pending_metrics["tts_first_byte_ms"] = round(getattr(m, "ttfb", 0.0) * 1000)
        logger.debug("metrics_collected", kind=kind, call_session_id=str(call_session.id))

    @session.on("conversation_item_added")
    def _on_item(ev) -> None:
        nonlocal turn_index, turn_started_at, pending_metrics

        item = ev.item
        role = getattr(item, "role", None)
        text = getattr(item, "text_content", None) or str(getattr(item, "content", ""))
        if not text:
            return

        now = time.monotonic()
        total_ms = None
        if role == "user":
            turn_started_at = now
            pending_metrics = {}
        elif role == "assistant" and turn_started_at is not None:
            total_ms = round((now - turn_started_at) * 1000)

        turn_index += 1
        turn = CallTurn(
            call_session_id=call_session.id,
            turn_index=turn_index,
            role=role or "unknown",
            text=text,
            stt_ms=pending_metrics.get("stt_ms") if role == "assistant" else None,
            llm_ms=pending_metrics.get("llm_ms") if role == "assistant" else None,
            tts_first_byte_ms=pending_metrics.get("tts_first_byte_ms") if role == "assistant" else None,
            total_ms=total_ms,
        )

        async def _persist() -> None:
            async with AsyncSessionLocal() as db:
                db.add(turn)
                await db.commit()
            await publish_call_event(
                clinic.id,
                {
                    "type": "turn",
                    "call_session_id": str(call_session.id),
                    "role": turn.role,
                    "text": turn.text,
                    "total_ms": turn.total_ms,
                },
            )

        ctx.create_task(_persist())

    await session.start(
        room=ctx.room,
        agent=agent,
        room_input_options=RoomInputOptions(),
    )

    await publish_call_event(
        clinic.id, {"type": "call_started", "call_session_id": str(call_session.id), "language": language}
    )

    async def _on_shutdown() -> None:
        async with AsyncSessionLocal() as db:
            cs = await db.get(CallSession, call_session.id)
            if cs is None:
                return
            try:
                final_state = await get_final_state(
                    db,
                    clinic=clinic,
                    language=language,
                    config={"configurable": {"thread_id": str(call_session.id)}},
                )
                cs.outcome = final_state.get("outcome", "no_outcome")
            except Exception:  # noqa: BLE001 - never block shutdown on bookkeeping
                logger.exception("final_state_lookup_failed", call_session_id=str(call_session.id))

            cs.status = "completed"
            cs.ended_at = datetime.utcnow()
            await db.commit()

        await publish_call_event(
            clinic.id, {"type": "call_ended", "call_session_id": str(call_session.id), "outcome": cs.outcome}
        )

    ctx.add_shutdown_callback(_on_shutdown)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
