"""Store embeddings into ChromaDB."""

from typing import Literal, TypedDict

from chromadb import PersistentClient
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Where

from config import LOG, get_chroma_path
from search.embed import EMBED_BATCH, EMBED_MODEL, embed_texts

COLLECTION_NAME = "reviews"


class ReviewData(TypedDict):
    id: str
    content: str
    title_id: str
    title: str
    tmdb_id: int
    media_type: Literal["movie", "tv"]


def initialize_chroma_client(path: str = get_chroma_path()):
    return PersistentClient(path=path)


def get_chroma_collection(
    client: ClientAPI, collection_name: str = COLLECTION_NAME
) -> Collection:
    collection = client.get_or_create_collection(
        name=collection_name, metadata={"embedding_model": EMBED_MODEL}
    )
    return collection


def store_reviews(
    collection: Collection, records: list[ReviewData] | None = None
) -> int:
    """
    Embed locally and upsert into Chroma.
    """
    if not records:
        return 0
    total = 0
    for start in range(0, len(records), EMBED_BATCH):
        batch = records[start : start + EMBED_BATCH]
        embeddings = embed_texts([record["content"] for record in batch])
        collection.upsert(
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


def query_reviews(
    collection: Collection,
    query_vector: list[float],
    n: int = 5,
    media_type: Literal["movie", "tv"] | None = None,
) -> list[ReviewHit]:
    """
    Rank reviews by cosine similarity.
    Score = 1 - distance; kept hit per title is the best-ranked review.
    """
    where: Where | None = {"media_type": media_type} if media_type else None
    total = collection.count()
    if total == 0:
        return []
    best: dict[str, ReviewHit] = {}
    requested = n
    while len(best) < n and requested <= total:
        response = collection.query(
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
