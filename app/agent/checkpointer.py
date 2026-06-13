"""Shared LangGraph Postgres checkpointer.

A single connection pool is kept open for the lifetime of the process so each
conversation turn doesn't pay a new-connection cost - that would blow the
latency budget on its own. `setup()` runs once and creates the checkpoint
tables if they don't exist yet (safe to call repeatedly).
"""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import settings

_saver: AsyncPostgresSaver | None = None
_pool_cm = None


async def get_checkpointer() -> AsyncPostgresSaver:
    global _saver, _pool_cm
    if _saver is None:
        _pool_cm = AsyncPostgresSaver.from_conn_string(settings.database_url_psycopg)
        _saver = await _pool_cm.__aenter__()
        await _saver.setup()
    return _saver


async def close_checkpointer() -> None:
    global _saver, _pool_cm
    if _pool_cm is not None:
        await _pool_cm.__aexit__(None, None, None)
        _saver = None
        _pool_cm = None
