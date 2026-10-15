import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select

from db.models import Title, TitleDetailPublic, TitlePublic, TitlesPublic
from db.session import async_db, get_async_session
from search.chroma import (
    chroma,
    query_reviews,
)
from search.embed import embed_query, is_model_loaded, preload_embed_model

SessionDep = Annotated[AsyncSession, Depends(get_async_session)]


class SearchResult(SQLModel):
    review_id: str
    title_id: str
    title: str
    tmdb_id: int
    media_type: str
    snippet: str
    score: float


class SearchResponse(SQLModel):
    query: str
    results: list[SearchResult]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    await asyncio.to_thread(preload_embed_model)
    await chroma.connect()
    yield
    await async_db.dispose()


app = FastAPI(title="movie-search", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    if not is_model_loaded():
        raise HTTPException(status_code=503, detail="embedding model not loaded")
    return {"status": "ready"}


@app.get("/titles", response_model=TitlesPublic)
async def list_titles(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TitlesPublic:
    result = await session.execute(select(Title).offset(offset).limit(limit))
    rows = result.scalars().all()
    return TitlesPublic(
        data=[TitlePublic.model_validate(r) for r in rows],
        count=len(rows),
    )


@app.get("/titles/{title_id}", response_model=TitleDetailPublic)
async def get_title(
    title_id: UUID,
    session: SessionDep,
) -> TitleDetailPublic:
    result = await session.execute(
        select(Title)
        .where(Title.id == title_id)
        .options(
            selectinload(Title.genres),
            selectinload(Title.actors),
            selectinload(Title.directors),
            selectinload(Title.reviews),
        )
    )
    row = result.scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Title not found")
    return TitleDetailPublic.model_validate(row)


@app.get("/search", response_model=SearchResponse)
async def search(
    q: Annotated[str, Query(min_length=1, max_length=500)],
    n: Annotated[int, Query(ge=1, le=50)] = 5,
    media_type: Annotated[Literal["movie", "tv"] | None, Query()] = None,
) -> SearchResponse:
    if not is_model_loaded():
        raise HTTPException(status_code=503, detail="embedding model not loaded")
    query_vector = await asyncio.to_thread(embed_query, q)
    collection = chroma.get_collection()
    hits = await query_reviews(collection, query_vector, n, media_type)

    return SearchResponse(query=q, results=[SearchResult(**hit) for hit in hits])
