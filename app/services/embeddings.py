"""Thin wrapper around the embedding provider used for the clinic KB.

Kept isolated so the embedding model/provider can change without touching
indexing or retrieval call sites.
"""

import voyageai
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

_client: voyageai.AsyncClient | None = None


def _get_client() -> voyageai.AsyncClient:
    global _client
    if _client is None:
        _client = voyageai.AsyncClient(api_key=settings.voyage_api_key)
    return _client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4))
async def embed_documents(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    client = _get_client()
    result = await client.embed(
        texts, model=settings.embedding_model, input_type="document", output_dimension=settings.embedding_dim
    )
    return result.embeddings


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4))
async def embed_query(text: str) -> list[float]:
    client = _get_client()
    result = await client.embed(
        [text], model=settings.embedding_model, input_type="query", output_dimension=settings.embedding_dim
    )
    return result.embeddings[0]
