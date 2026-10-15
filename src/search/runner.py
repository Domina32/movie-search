import asyncio
from asyncio import TaskGroup
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio.session import AsyncSession

from config import LOG, PROFILING_ENABLED
from db.models import EmbeddingStatus, Review
from db.session import (
    NormalizedTitleDataShort,
    TitlesAndReviewsNormalizedData,
    async_db,
    fetch_unprocessed_reviews_from_db,
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
    """Join review with its title data."""
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
    is_first_fetch = True

    try:
        while is_first_fetch or (
            db_titles_with_reviews is not None and len(db_titles_with_reviews) > 0
        ):
            is_first_fetch = False
            db_titles_with_reviews = await fetch_unprocessed_reviews_from_db(
                session, EMBED_BATCH_SIZE
            )
            if db_titles_with_reviews is None:
                LOG.debug("No reviews found waiting for embedding.")
                return

            async with TaskGroup() as tg:
                review_batch = [
                    build_review(review, record["title"], title_id)
                    for title_id, record in db_titles_with_reviews
                    for review in record.get("reviews", [])
                ]
                reviews_valid: list[ReviewData] = []
                for record in review_batch:
                    if record is None:
                        continue
                    LOG.debug("%s | %s", record["id"], record["title"])
                    reviews_valid.append(record)
                stored_task = store_embeddings(chroma_collection, reviews_valid)
                tg.create_task(stored_task)

                review_ids = [r["id"] for r in reviews_valid]

                await session.execute(
                    update(Review)
                    .where(Review.metadata.tables["review"].c.id.in_(review_ids))
                    .values(embedding_status=EmbeddingStatus.completed)
                )
                await session.commit()
                LOG.info(
                    f"Successfully processed {len(reviews_valid)} review embeddings."
                )

    finally:
        pass


async def main():
    async with async_db.factory()() as session:
        if PROFILING_ENABLED:
            import pyinstrument

            with pyinstrument.profile():
                await embed_and_store_reviews(session)
        else:
            await embed_and_store_reviews(session)


if __name__ == "__main__":
    preload_embed_model()
    asyncio.run(main())
