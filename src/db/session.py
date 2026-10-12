"""Postgres engine and title/review writes."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import Session, SQLModel, create_engine, select

from config import get_database_url
from db.models import (
    Director,
    Genre,
    Review,
    Title,
    TitleDirectorLink,
    TitleGenreLink,
)
from ingest.tmdb import (
    NormalizedTitleResultData,
)


class AsyncDatabase:
    """
    Async engine and session factory singleton.
    """

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


def store_title(session: Session, record: NormalizedTitleResultData) -> UUID:
    """
    Upsert one title with its genres and reviews. Caller commits.
    """
    title = record["title"]

    payload = Title(**title)
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
    )
    session.exec(upsert)
    title_id = session.exec(
        select(Title.id).where(
            Title.tmdb_id == payload.tmdb_id,
            Title.media_type == payload.media_type,
        )
    ).one()

    review_rows = [
        {"id": r["id"], "title_id": title_id, "content": r["content"]}
        for r in record.get("reviews", [])
    ]
    if review_rows:
        session.exec(
            insert(Review)
            .values(review_rows)
            .on_conflict_do_nothing(index_elements=["id"])
        )

    genre_rows = [{"id": g["id"], "name": g["name"]} for g in record.get("genres", [])]
    if genre_rows:
        upsert_genres = insert(Genre).values(genre_rows)
        session.exec(
            upsert_genres.on_conflict_do_update(
                index_elements=["id"],
                set_={"name": upsert_genres.excluded.name},
            )
        )
        session.exec(
            insert(TitleGenreLink)
            .values([{"title_id": title_id, "genre_id": g["id"]} for g in genre_rows])
            .on_conflict_do_nothing(index_elements=["title_id", "genre_id"])
        )

    director_rows = [
        {"id": d["id"], "name": d["name"]} for d in record.get("directors", [])
    ]
    if director_rows:
        upsert_directors = insert(Director).values(director_rows)
        session.exec(
            upsert_directors.on_conflict_do_update(
                index_elements=["id"], set_={"name": upsert_directors.excluded.name}
            )
        )
        session.exec(
            insert(TitleDirectorLink)
            .values(
                [{"title_id": title_id, "director_id": d["id"]} for d in director_rows]
            )
            .on_conflict_do_nothing(index_elements=["title_id", "director_id"])
        )

    return title_id


def store_titles(engine: Engine, records: list[NormalizedTitleResultData]) -> int:
    """Store a batch in one transaction. Returns titles written."""
    with Session(engine) as session:
        for record in records:
            store_title(session, record)
        session.commit()
    return len(records)


def ensure_schema(engine: Engine) -> None:
    """Create tables without migrations (dev/test only)."""
    SQLModel.metadata.create_all(engine)
