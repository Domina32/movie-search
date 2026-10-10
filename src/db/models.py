import enum
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel
from sqlmodel.main import Relationship


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


class MediaType(enum.StrEnum):
    movie = "movie"
    tv = "tv"


# class CreditRole(enum.StrEnum):
#     actor = "actor"
#     director = "director"


# class GenreBase(SQLModel):
#     name: str = Field(max_length=64)
#
#
# class Genre(GenreBase, table=True):
#     id: int = Field(primary_key=True)
#
#
# class GenrePublic(GenreBase):
#     id: int
#
#
# class PersonBase(SQLModel):
#     name: str = Field(max_length=255)
#
#
# class Person(PersonBase, table=True):
#     id: int = Field(primary_key=True)
#
#
# class PersonPublic(PersonBase):
#     id: int
#
#


class TitleBase(SQLModel):
    tmdb_id: int
    media_type: MediaType = Field(max_length=16)
    title: str = Field(default="", max_length=500)
    original_language: str = Field(default="", max_length=16)
    language_name: str = Field(default="", max_length=64)
    release_date: date | None = Field(default=None)
    fetched_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


class Title(TitleBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    # ids can repeat on /movies and /tv so we need to include
    # media_type marker on each title entity
    __table_args__ = (
        UniqueConstraint("tmdb_id", "media_type", name="uq_title_tmdb_media"),
    )
    reviews: list["Review"] = Relationship(back_populates="title")  # noqa: UP037 - forward ref, Review defined below


class TitlePublic(TitleBase):
    id: uuid.UUID


class TitlesPublic(SQLModel):
    data: list[TitlePublic]
    count: int


class ReviewBase(SQLModel):
    content: str
    fetched_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


class Review(ReviewBase, table=True):
    id: str = Field(primary_key=True, max_length=64)
    title_id: uuid.UUID = Field(foreign_key="title.id", index=True, ondelete="CASCADE")
    title: Title | None = Relationship(back_populates="reviews")


class ReviewPublic(ReviewBase):
    id: str
    title_id: uuid.UUID
