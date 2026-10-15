"""Store embeddings into ChromaDB."""

import asyncio
from typing import Literal, TypedDict

from chromadb import AsyncHttpClient
from chromadb.api.async_api import AsyncClientAPI
from chromadb.api.models.AsyncCollection import AsyncCollection
from chromadb.api.types import Where

from config import LOG, get_chroma_host_and_port
from search.embed import EMBED_BATCH, embed_texts

COLLECTION_NAME = "reviews"


class ReviewData(TypedDict):
    id: str
    content: str
    title_id: str
    title: str
    tmdb_id: int
    media_type: Literal["movie", "tv"]


class AsyncChromaClient:
    def __init__(self, host: str, port: int, collection_name: str) -> None:
        self.host: str = host
        self.port: int = port
        self.collection_name: str = collection_name
        self._client: AsyncClientAPI | None = None
        self._collection: AsyncCollection | None = None

    async def connect(self) -> None:
        if self._client is None:
            self._client = await AsyncHttpClient(host=self.host, port=self.port)
            self._collection = await self._client.get_or_create_collection(
                name=self.collection_name
            )

    def get_collection(self) -> AsyncCollection:
        if self._collection is None:
            raise RuntimeError("ChromaDB has not been initialized")
        return self._collection


CHROMA_HOST, CHROMA_PORT = get_chroma_host_and_port()
chroma = AsyncChromaClient(
    host=CHROMA_HOST, port=CHROMA_PORT, collection_name="reviews"
)


async def store_reviews(
    collection: AsyncCollection, records: list[ReviewData | None]
) -> int:
    """
    Embed locally and upsert into Chroma.
    """
    total = 0
    for start in range(0, len(records), EMBED_BATCH):
        batch = [
            record
            for record in records[start : start + EMBED_BATCH]
            if record is not None
        ]
        embeddings = await asyncio.to_thread(
            embed_texts, [record["content"] for record in batch]
        )
        await collection.upsert(
            ids=[record["id"] for record in batch],
            embeddings=embeddings,
            documents=[record["content"] for record in batch],
            metadatas=[
                {
                    "title_id": record["title_id"],
                    "title": record["title"],
                    "tmdb_id": record["tmdb_id"],
                    "media_type": record["media_type"],
                }
                for record in batch
            ],
        )
        total += len(batch)
        LOG.info("Chroma upserted %d/%d", total, len(records))
    return total


class ReviewHit(TypedDict):
    review_id: str
    title_id: str
    title: str
    tmdb_id: int
    media_type: str
    snippet: str
    score: float


async def query_reviews(
    collection: AsyncCollection,
    query_vector: list[float],
    n: int = 5,
    media_type: Literal["movie", "tv"] | None = None,
) -> list[ReviewHit]:
    """
    Rank reviews by cosine similarity.
    Score = 1 - distance; kept hit per title is the best-ranked review.
    """
    where: Where | None = {"media_type": media_type} if media_type else None
    total = await collection.count()
    if total == 0:
        return []
    best: dict[str, ReviewHit] = {}
    requested = n
    while len(best) < n and requested <= total:
        response = await collection.query(
            query_embeddings=[query_vector],
            n_results=min(requested, total),
            where=where,
        )
        ids = (response["ids"] or [[]])[0]
        documents = (response["documents"] or [[]])[0]
        metadatas = (response["metadatas"] or [[]])[0]
        distances = (response["distances"] or [[]])[0]
        if not ids:
            break
        for review_id, document, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=True
        ):
            fields = metadata or {}
            title_id = str(fields.get("title_id", ""))
            if title_id in best:
                continue
            raw_tmdb_id = fields.get("tmdb_id", 0)
            tmdb_id = (
                raw_tmdb_id
                if isinstance(raw_tmdb_id, int)
                else int(raw_tmdb_id)
                if isinstance(raw_tmdb_id, float)
                else 0
            )
            best[title_id] = {
                "review_id": review_id,
                "title_id": title_id,
                "title": str(fields.get("title", "")),
                "tmdb_id": tmdb_id,
                "media_type": str(fields.get("media_type", "")),
                "snippet": (document or "")[:500],
                "score": 1.0 - float(distance),
            }
        if len(ids) < min(requested, total):
            break  # index exhausted
        requested *= 2
    return list(best.values())[:n]
