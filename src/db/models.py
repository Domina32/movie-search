import enum
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import DateTime, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped
from sqlmodel import Field, SQLModel
from sqlmodel.main import Relationship


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


class MediaType(enum.StrEnum):
    movie = "movie"
    tv = "tv"


class EmbeddingStatus(enum.StrEnum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


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


class TitleGenreLink(SQLModel, table=True):
    title_id: uuid.UUID = Field(
        foreign_key="title.id", primary_key=True, ondelete="CASCADE"
    )
    genre_id: int = Field(foreign_key="genre.id", primary_key=True, ondelete="CASCADE")


class TitleActorLink(SQLModel, table=True):
    title_id: uuid.UUID = Field(
        foreign_key="title.id", primary_key=True, ondelete="CASCADE"
    )
    actor_id: int = Field(foreign_key="actor.id", primary_key=True, ondelete="CASCADE")


class TitleDirectorLink(SQLModel, table=True):
    title_id: uuid.UUID = Field(
        foreign_key="title.id", primary_key=True, ondelete="CASCADE"
    )
    director_id: int = Field(
        foreign_key="director.id", primary_key=True, ondelete="CASCADE"
    )


class Title(TitleBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # ids can repeat on /movies and /tv so we need to include
    # media_type marker on each title entity
    __table_args__ = (
        UniqueConstraint("tmdb_id", "media_type", name="uq_title_tmdb_media"),
    )
    genres: Mapped[list[Genre]] = Relationship(
        back_populates="titles",
        link_model=TitleGenreLink,
    )
    reviews: Mapped[list[Review]] = Relationship(
        back_populates="title", cascade_delete=True
    )
    actors: Mapped[list[Actor]] = Relationship(
        back_populates="titles", link_model=TitleActorLink
    )
    directors: Mapped[list[Director]] = Relationship(
        back_populates="titles", link_model=TitleDirectorLink
    )


class TitlePublic(TitleBase):
    id: uuid.UUID


class TitlesPublic(SQLModel):
    data: list[TitlePublic]
    count: int


class GenreBase(SQLModel):
    name: str = Field(max_length=64)


class Genre(GenreBase, table=True):
    id: int = Field(primary_key=True, sa_column_kwargs={"autoincrement": False})
    titles: list[Title] = Relationship(
        back_populates="genres", link_model=TitleGenreLink
    )


class GenrePublic(GenreBase):
    id: int


class ReviewBase(SQLModel):
    content: str
    fetched_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


class Review(ReviewBase, table=True):
    id: str = Field(primary_key=True, max_length=64)
    title_id: uuid.UUID = Field(foreign_key="title.id", index=True, ondelete="CASCADE")
    title: Title = Relationship(back_populates="reviews")
    embedding_status: EmbeddingStatus = Field(
        default=EmbeddingStatus.pending,
        max_length=16,
    )
    __table_args__ = (
        Index(
            "ix_review_needs_embedding",
            "embedding_status",
            postgresql_where=text("embedding_status = 'pending'"),
        ),
    )


class ReviewPublic(ReviewBase):
    id: str
    title_id: uuid.UUID


class DirectorBase(SQLModel):
    name: str = Field(max_length=128)


class Director(DirectorBase, table=True):
    id: int = Field(primary_key=True, sa_column_kwargs={"autoincrement": False})
    titles: list[Title] = Relationship(
        back_populates="directors", link_model=TitleDirectorLink
    )


class DirectorPublic(DirectorBase):
    pass


class ActorBase(SQLModel):
    name: str = Field(max_length=128)
    order: int | None = Field(default=None)


class Actor(ActorBase, table=True):
    id: int = Field(primary_key=True, sa_column_kwargs={"autoincrement": False})
    titles: list[Title] = Relationship(
        back_populates="actors", link_model=TitleActorLink
    )


class ActorPublic(ActorBase):
    pass


class TitleDetailPublic(TitlePublic):
    genres: list[GenrePublic] = []
    actors: list[ActorPublic] = []
    directors: list[DirectorPublic] = []
    reviews: list[ReviewPublic] = []
