from collections.abc import AsyncIterator
from datetime import date
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from api.routes import app
from db.models import MediaType, Title
from db.session import get_async_session

Factory = async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture
async def db() -> AsyncIterator[Factory]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db: Factory) -> AsyncIterator[AsyncClient]:
    async def override() -> AsyncIterator[AsyncSession]:
        async with db() as session:
            yield session

    app.dependency_overrides[get_async_session] = override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


def make_title(tmdb_id: int, title: str = "Dune") -> Title:
    return Title(
        id=uuid4(),
        tmdb_id=tmdb_id,
        media_type=MediaType.movie,
        title=title,
        original_language="en",
        language_name="English",
        release_date=date(2021, 9, 15),
    )


async def seed(db: Factory, titles: list[Title]) -> None:
    async with db() as session:
        session.add_all(titles)
        await session.commit()


@pytest.mark.asyncio
async def test_health_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_list_empty(client: AsyncClient) -> None:
    response = await client.get("/titles")
    assert response.status_code == 200
    assert response.json() == {"data": [], "count": 0}


@pytest.mark.asyncio
async def test_list_returns_seeded(client: AsyncClient, db: Factory) -> None:
    await seed(db, [make_title(1, "Dune"), make_title(2, "Shogun")])
    response = await client.get("/titles")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert {row["tmdb_id"] for row in body["data"]} == {1, 2}


@pytest.mark.asyncio
async def test_list_pagination(client: AsyncClient, db: Factory) -> None:
    await seed(db, [make_title(i, f"T{i}") for i in range(3)])
    first = (await client.get("/titles?limit=2")).json()
    second = (await client.get("/titles?limit=2&offset=2")).json()
    assert first["count"] == 2
    assert second["count"] == 1
    assert first["data"][0]["tmdb_id"] != second["data"][0]["tmdb_id"]


@pytest.mark.asyncio
async def test_list_validation(client: AsyncClient) -> None:
    assert (await client.get("/titles?limit=0")).status_code == 422
    assert (await client.get("/titles?limit=101")).status_code == 422
    assert (await client.get("/titles?offset=-1")).status_code == 422


@pytest.mark.asyncio
async def test_get_by_id(client: AsyncClient, db: Factory) -> None:
    title = make_title(7, "Dune")
    await seed(db, [title])
    response = await client.get(f"/titles/{title.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(title.id)
    assert body["tmdb_id"] == 7
    assert body["title"] == "Dune"


@pytest.mark.asyncio
async def test_get_missing_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/titles/{uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Title not found"}


@pytest.mark.asyncio
async def test_get_invalid_uuid_returns_422(client: AsyncClient) -> None:
    response = await client.get("/titles/not-a-uuid")
    assert response.status_code == 422
