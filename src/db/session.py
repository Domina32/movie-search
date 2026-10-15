"""Postgres engine and title/review writes."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel, create_engine, select
from typing_extensions import TypedDict

from config import LOG, get_database_url
from db.models import (
    Actor,
    Director,
    EmbeddingStatus,
    Genre,
    MediaType,
    Review,
    Title,
    TitleActorLink,
    TitleDirectorLink,
    TitleGenreLink,
)
from ingest.tmdb import (
    NormalizedReviewData,
    NormalizedTitleResultData,
)


class NormalizedTitleDataShort(TypedDict):
    title: str
    tmdb_id: int
    media_type: MediaType


class TitlesAndReviewsNormalizedData(TypedDict):
    title: NormalizedTitleDataShort
    reviews: list[NormalizedReviewData]


class AsyncDatabase:
    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._factory: async_sessionmaker[AsyncSession] | None = None

    def factory(self) -> async_sessionmaker[AsyncSession]:
        if self._factory is None:
            self._engine = create_async_engine(get_database_url(), pool_pre_ping=True)
            self._factory = async_sessionmaker(
                self._engine, class_=AsyncSession, expire_on_commit=False
            )
        return self._factory

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._factory = None


async_db = AsyncDatabase()


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_db.factory()


async def get_async_session() -> AsyncIterator[AsyncSession]:
    async with async_db.factory()() as session:
        yield session


def get_engine(dsn: str) -> Engine:
    """
    Create engine. One per process; callers manage lifetime.
    """
    return create_engine(dsn, pool_pre_ping=True)


async def try_store_title(
    session: AsyncSession, record: NormalizedTitleResultData
) -> UUID | None:
    """
    Upsert one title with its genres and reviews.
    """
    title = record["title"]
    payload = Title(**title)
    try:
        async with session.begin_nested():
            row = Title.model_validate(payload).model_dump()
            upsert = (
                insert(Title)
                .values(row)
                .on_conflict_do_update(
                    constraint="uq_title_tmdb_media",
                    set_={
                        "title": row["title"],
                        "original_language": row["original_language"],
                        "language_name": row["language_name"],
                        "release_date": row["release_date"],
                        "fetched_at": datetime.now(UTC),
                    },
                )
                .returning(Title.metadata.tables["title"].c.id)
            )
            title_id: UUID = (await session.execute(upsert)).scalar_one()

            review_rows = [
                {"id": r["id"], "title_id": title_id, "content": r["content"]}
                for r in record.get("reviews", [])
            ]
            if review_rows:
                await session.execute(
                    insert(Review)
                    .values(review_rows)
                    .on_conflict_do_nothing(index_elements=["id"])
                )

            genre_rows = [
                {"id": g["id"], "name": g["name"]} for g in record.get("genres", [])
            ]
            if genre_rows:
                upsert_genres = insert(Genre).values(genre_rows)
                await session.execute(
                    upsert_genres.on_conflict_do_update(
                        index_elements=["id"],
                        set_={"name": upsert_genres.excluded.name},
                    )
                )
                await session.execute(
                    insert(TitleGenreLink)
                    .values(
                        [
                            {"title_id": title_id, "genre_id": g["id"]}
                            for g in genre_rows
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=["title_id", "genre_id"])
                )

            actor_rows = [
                {"id": a["id"], "name": a["name"], "order": a["order"]}
                for a in record.get("actors", [])
            ]
            if actor_rows:
                upsert_actors = insert(Actor).values(actor_rows)
                await session.execute(
                    upsert_actors.on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            "name": upsert_actors.excluded.name,
                            "order": upsert_actors.excluded.order,
                        },
                    )
                )
                await session.execute(
                    insert(TitleActorLink)
                    .values(
                        [
                            {"title_id": title_id, "actor_id": a["id"]}
                            for a in actor_rows
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=["title_id", "actor_id"])
                )

            director_rows = [
                {"id": d["id"], "name": d["name"]} for d in record.get("directors", [])
            ]
            if director_rows:
                upsert_directors = insert(Director).values(director_rows)
                await session.execute(
                    upsert_directors.on_conflict_do_update(
                        index_elements=["id"],
                        set_={"name": upsert_directors.excluded.name},
                    )
                )
                await session.execute(
                    insert(TitleDirectorLink)
                    .values(
                        [
                            {"title_id": title_id, "director_id": d["id"]}
                            for d in director_rows
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=["title_id", "director_id"])
                )
            return title_id
    except Exception as e:
        LOG.error("Skipped storing because of:")
        LOG.error(e)
        return None


async def store_titles(
    records: list[NormalizedTitleResultData],
) -> list[tuple[UUID, NormalizedTitleResultData]]:
    ids: list[UUID] = []
    failed_records: list[int] = []
    async with async_db.factory()() as session:
        for index, record in enumerate(records):
            store_attempt = await try_store_title(session, record)

            if store_attempt is None:
                failed_records.append(index)
                continue

            ids.append(store_attempt)
            LOG.debug(
                "%s | %s (%s) | %s | tmdb=%s (%s) | %d reviews",
                record["title"]["title"],
                record["title"]["language_name"] or "-",
                record["title"]["original_language"],
                record["title"]["release_date"],
                record["title"]["tmdb_id"],
                record["title"]["media_type"],
                len(record["reviews"]),
            )
        await session.commit()

    successful_records = [
        record for index, record in enumerate(records) if index not in failed_records
    ]
    LOG.info("Postgres upserted %d/%d", len(successful_records), len(records))

    return list(zip(ids, successful_records, strict=True))


async def fetch_unprocessed_reviews_from_db(
    session: AsyncSession,
    batch_size: int,
) -> list[tuple[UUID, TitlesAndReviewsNormalizedData]] | None:
    """
    Queries reviews that match EmbeddingStatus.pending.
    """
    statement = (
        select(Review.id)
        .where(Review.embedding_status == EmbeddingStatus.pending)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(statement)
    review_ids = result.scalars().all()
    if not review_ids:
        return None

    await session.execute(
        update(Review)
        .where(Review.metadata.tables["review"].c.id.in_(review_ids))
        .values(embedding_status=EmbeddingStatus.processing)
    )
    await session.commit()

    statement = (
        select(Review, Title)
        .join(Title)
        .where(Review.metadata.tables["review"].c.id.in_(review_ids))
    )
    rows = (await session.execute(statement)).all()

    grouped_data: dict[UUID, TitlesAndReviewsNormalizedData] = {}
    for review, title_obj in rows:
        title_id = review.title_id
        if title_id not in grouped_data:
            grouped_data[title_id] = {
                "title": {
                    "title": title_obj.title,
                    "tmdb_id": title_obj.tmdb_id,
                    "media_type": title_obj.media_type,
                },
                "reviews": [],
            }

        grouped_data[title_id]["reviews"].append(
            {
                "id": review.id,
                "content": review.content,
            }
        )
    return list(grouped_data.items())


def ensure_schema(engine: Engine) -> None:
    """Create tables without migrations (dev/test only)."""
    SQLModel.metadata.create_all(engine)
