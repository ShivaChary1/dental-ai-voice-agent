"""Redis pub/sub helpers for live-call dashboard updates.

The voice worker publishes small JSON events (call started/ended, per-turn
summaries) to a per-clinic channel; the `/ws/live-calls` endpoint relays them
to connected dashboard clients. Keeping this on Redis (rather than in-process)
means the API and voice-worker processes can scale independently.
"""

import json
import uuid
from typing import Any

import redis.asyncio as redis

from app.config import settings

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _channel(clinic_id: uuid.UUID | str) -> str:
    return f"live-calls:{clinic_id}"


async def publish_call_event(clinic_id: uuid.UUID | str, event: dict[str, Any]) -> None:
    r = get_redis()
    await r.publish(_channel(clinic_id), json.dumps(event, default=str))


async def subscribe_call_events(clinic_id: uuid.UUID | str):
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(_channel(clinic_id))
    return pubsub
