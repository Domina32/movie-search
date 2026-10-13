"""Store embeddings into ChromaDB."""

from typing import Any, Literal, TypedDict, cast

from chromadb import PersistentClient
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

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
            embeddings=cast(Any, embeddings),
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


# results = collection.query(
#     query_embeddings=[query_vector],  # Pass as a list of queries
#     n_results=5,
# )
