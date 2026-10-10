"""Postgres engine and title/review writes."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, SQLModel, create_engine, select

from db.models import Review, Title
from ingest.tmdb import (
    NormalizedTitleResultData,
)


def get_engine(dsn: str) -> Engine:
    """Create engine. One per process; callers manage lifetime."""
    return create_engine(dsn, pool_pre_ping=True)


def store_title(session: Session, record: NormalizedTitleResultData) -> UUID:
    """Upsert one title + its reviews. Caller commits. Returns title id."""
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
