from typing import Literal

import httpx
import pytest

from ingest.tmdb import (
    DetailsMovieResponseData,
    DetailsTvResponseData,
    get_title_details,
    get_trending,
    normalize_title,
)


@pytest.mark.parametrize(
    ("media_type", "item"),
    [
        ("movie", {"id": 1, "title": "Dune", "original_language": "en"}),
        ("tv", {"id": 2, "name": "Shogun", "original_language": "ja"}),
    ],
)
@pytest.mark.asyncio
async def test_get_trending_sends_auth_and_keeps_language(
    media_type: Literal["movie", "tv"], item: dict[str, object]
) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"page": 1, "results": [item]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    results = await get_trending(client, token="test-token", media_type=media_type)

    assert len(results) == 1
    assert results[0]["original_language"] == item["original_language"]
    assert seen["auth"] == "Bearer test-token"
    assert f"trending/{media_type}/day" in seen["url"]
    assert "page=1" in seen["url"]
    assert "language=" not in seen["url"]


@pytest.mark.asyncio
async def test_get_trending_raises_on_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status_message": "Invalid token"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await get_trending(client, token="bad-token", media_type="movie")
    except httpx.HTTPStatusError:
        return
    raise AssertionError("expected HTTPStatusError for 401")


@pytest.mark.asyncio
async def test_get_title_details_appends_credits_and_reviews() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"id": 1, "title": "Dune"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    data = await get_title_details(
        client, token="test-token", media_type="movie", title_id=1
    )

    assert data["id"] == 1
    assert "/movie/1" in seen["url"]
    assert "append_to_response" in seen["url"]
    assert "credits" in seen["url"]
    assert "reviews" in seen["url"]


@pytest.mark.asyncio
async def test_get_title_details_raises_on_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"status_message": "Not found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await get_title_details(
            client, token="t", media_type="movie", title_id=99999999
        )
    except httpx.HTTPStatusError:
        return
    raise AssertionError("expected HTTPStatusError for 404")


def test_normalize_title_movie() -> None:
    raw: DetailsMovieResponseData = {
        "id": 1,
        "title": "Dune",
        "original_language": "en",
        "spoken_languages": [{"english_name": "English"}],
        "genres": [{"id": 0, "name": "Sci-Fi"}, {"id": 1, "name": ""}],
        "release_date": "2021-09-15",
        "credits": {
            "cast": [
                {"id": 0, "name": "B", "order": 1},
                {"id": 1, "name": "A", "order": 0},
                {"id": 2, "name": "", "order": 2},
            ],
            "crew": [
                {"id": 0, "name": "Denis Villeneuve", "job": "Director"},
                {"id": 1, "name": "Someone", "job": "Producer"},
            ],
        },
        "reviews": {
            "results": [
                {"id": "r1", "content": "Great film"},
                {"id": "r2", "content": ""},
            ]
        },
    }
    out = normalize_title(raw, "movie")
    assert out["title"] == "Dune"
    assert out["actors"] == ["A", "B"]
    assert out["directors"] == ["Denis Villeneuve"]
    assert out["genres"] == ["Sci-Fi"]
    assert out["language_name"] == "English"
    assert out["release_date"] == "2021-09-15"
    assert out["reviews"] == [{"id": "r1", "content": "Great film"}]


def test_normalize_title_tv_falls_back_to_creators() -> None:
    raw: DetailsTvResponseData = {
        "id": 2,
        "name": "Shogun",
        "original_language": "ja",
        "spoken_languages": [],
        "genres": [{"id": 0, "name": "Drama"}],
        "first_air_date": "2024-02-27",
        "credits": {"cast": [], "crew": []},
        "created_by": [{"id": 0, "name": "Jonathan van Tulleken"}],
        "reviews": {"results": []},
    }
    out = normalize_title(raw, "tv")
    assert out["title"] == "Shogun"
    assert out["directors"] == ["Jonathan van Tulleken"]
    assert out["language_name"] == ""
    assert out["reviews"] == []
