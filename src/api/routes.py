from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from db.models import Title, TitleDetailPublic, TitlePublic, TitlesPublic
from db.session import async_db, get_async_session

SessionDep = Annotated[AsyncSession, Depends(get_async_session)]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    yield
    await async_db.dispose()


app = FastAPI(title="movie-search", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
            # selectinload(Title.actors),
            selectinload(Title.directors),
            selectinload(Title.reviews),
        )
    )
    row = result.scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Title not found")
    return TitleDetailPublic.model_validate(row)
