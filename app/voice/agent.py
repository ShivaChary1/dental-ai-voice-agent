"""Custom LiveKit Agent that delegates all reasoning to the LangGraph
conversation graph instead of LiveKit's built-in LLM node.

We override `llm_node` (the documented extension point - see
https://docs.livekit.io/agents/logic/nodes/) rather than implementing a full
`livekit.agents.llm.LLM` subclass: our "LLM" is actually a multi-step
tool-calling LangGraph run with its own Postgres-backed state per call, so the
LiveKit-side `chat_ctx` is only used to read the latest user utterance - all
real conversation state lives in the LangGraph checkpoint keyed by
`call_session_id`.

IMPORTANT: `llm_node` must be an `async def` *generator* (i.e. contain
`yield`). If it's `async def` but never yields and instead `return`s a value,
LiveKit silently treats it as "no response" (dead air) - this is a known
framework gotcha, not a bug in this file.
"""

import asyncio
import uuid
from collections.abc import AsyncIterable

from livekit.agents import Agent, ModelSettings
from livekit.agents import llm as lk_llm

from app.agent.graph import stream_turn
from app.db.models import Clinic
from app.db.session import AsyncSessionLocal

# How long to wait for the first text chunk before speaking a filler phrase.
# Keeps perceived latency low when the turn requires a tool call (RAG lookup,
# availability check, etc.) before any text is generated.
FILLER_TIMEOUT_SECONDS = 0.25

FILLER_PHRASES = {
    "en-IN": "Sure, one moment.",
    "hi-IN": "ठीक है, एक मिनट।",
    "te-IN": "సరే, ఒక్క క్షణం.",
}


class DentalClinicAgent(Agent):
    def __init__(self, *, clinic: Clinic, language: str, call_session_id: uuid.UUID, instructions: str):
        super().__init__(instructions=instructions)
        self._clinic = clinic
        self._language = language
        self._call_session_id = call_session_id

    async def llm_node(
        self,
        chat_ctx: lk_llm.ChatContext,
        tools: list,
        model_settings: ModelSettings,
    ) -> AsyncIterable[lk_llm.ChatChunk]:
        user_text = _last_user_text(chat_ctx)
        if not user_text:
            return

        config = {"configurable": {"thread_id": str(self._call_session_id)}}

        async with AsyncSessionLocal() as db:
            stream = stream_turn(
                db, clinic=self._clinic, language=self._language, config=config, user_text=user_text
            )

            first_chunk_task = asyncio.ensure_future(stream.__anext__())
            try:
                first_text = await asyncio.wait_for(first_chunk_task, timeout=FILLER_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                filler = FILLER_PHRASES.get(self._language, FILLER_PHRASES["en-IN"])
                yield _chunk(filler)
                try:
                    first_text = await first_chunk_task
                except StopAsyncIteration:
                    return
            except StopAsyncIteration:
                return

            yield _chunk(first_text)
            async for piece in stream:
                yield _chunk(piece)


def _chunk(text: str) -> lk_llm.ChatChunk:
    return lk_llm.ChatChunk(
        id=str(uuid.uuid4()),
        delta=lk_llm.ChoiceDelta(role="assistant", content=text),
    )


def _last_user_text(chat_ctx: lk_llm.ChatContext) -> str | None:
    """Pull the most recent user utterance out of LiveKit's chat context.

    `ChatContext.items` holds `ChatMessage` entries with `.role` and
    `.content` (a list of strings/content parts for multimodal messages).
    """
    for item in reversed(chat_ctx.items):
        if getattr(item, "role", None) != "user":
            continue
        content = getattr(item, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text = " ".join(str(part) for part in content if isinstance(part, str))
            if text:
                return text
    return None
