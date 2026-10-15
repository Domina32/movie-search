import asyncio
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio.session import AsyncSession

from config import LOG, PROFILING_ENABLED, configure_logging
from db.models import EmbeddingStatus, Review
from db.session import (
    NormalizedTitleDataShort,
    TitlesAndReviewsNormalizedData,
    async_db,
    fetch_unprocessed_reviews_from_db,
    is_ingest_active,
)
from ingest.tmdb import (
    NormalizedReviewData,
)
from search.chroma import (
    ReviewData,
    chroma,
    store_embeddings,
)
from search.embed import EMBED_BATCH_SIZE, preload_embed_model


def build_review(
    review: NormalizedReviewData,
    title: NormalizedTitleDataShort,
    title_id: UUID,
) -> ReviewData | None:
    """
    Join review with its title data.
    """
    content = review.get("content")
    if not content:
        return None

    return {
        "id": review["id"],
        "content": content,
        "title_id": str(title_id),
        "title": title["title"],
        "tmdb_id": title["tmdb_id"],
        "media_type": title["media_type"].value,
    }


async def embed_and_store_reviews(session: AsyncSession):
    """
    Fetch stored review from db, generate embedding, store into chroma.
    """
    await chroma.connect()
    chroma_collection = chroma.get_collection()
    db_titles_with_reviews: (
        list[tuple[UUID, TitlesAndReviewsNormalizedData]] | None
    ) = []

    keep_polling = True

    while keep_polling:
        db_titles_with_reviews = await fetch_unprocessed_reviews_from_db(
            session, EMBED_BATCH_SIZE
        )

        if db_titles_with_reviews is None:
            keep_polling = await is_ingest_active(session)

            if keep_polling:
                LOG.debug(
                    "Queue empty but ingest active, waiting (batch_size=%d).",
                    EMBED_BATCH_SIZE,
                )
                await asyncio.sleep(10)
            else:
                LOG.debug(
                    "Queue empty and ingest finished (batch_size=%d), stopping.",
                    EMBED_BATCH_SIZE,
                )
        else:
            batch = db_titles_with_reviews
            review_batch = [
                build_review(review, entry["title"], entry_id)
                for entry_id, entry in batch
                for review in entry.get("reviews", [])
            ]
            reviews_valid: list[ReviewData] = []

            for item in review_batch:
                if item is None:
                    continue
                LOG.debug(
                    "%s | %s | tmdb=%s (%s)",
                    item["id"],
                    item["title"],
                    item["tmdb_id"],
                    item["media_type"],
                )
                reviews_valid.append(item)

            review_ids = [r["id"] for r in reviews_valid]

            if review_ids:
                try:
                    await store_embeddings(chroma_collection, reviews_valid)
                except Exception:
                    LOG.exception(
                        "Chroma upsert failed for %d reviews.", len(review_ids)
                    )
                    await session.execute(
                        update(Review)
                        .where(Review.metadata.tables["review"].c.id.in_(review_ids))
                        .values(embedding_status=EmbeddingStatus.failed)
                    )
                    await session.commit()
                else:
                    await session.execute(
                        update(Review)
                        .where(Review.metadata.tables["review"].c.id.in_(review_ids))
                        .values(embedding_status=EmbeddingStatus.completed)
                    )
                    await session.commit()
                    LOG.info(
                        f"Successfully processed {len(reviews_valid)} review embeddings."
                    )


async def main():
    configure_logging()
    async with async_db, async_db.factory()() as session:
        if PROFILING_ENABLED:
            import pyinstrument

            with pyinstrument.profile():
                await embed_and_store_reviews(session)
        else:
            await embed_and_store_reviews(session)


if __name__ == "__main__":
    preload_embed_model()
    asyncio.run(main())
