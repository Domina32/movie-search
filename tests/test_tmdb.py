from typing import Any, Literal

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

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
        return httpx.Response(200, json={"page": 3, "results": [item]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    results = await get_trending(
        client, token="test-token", media_type=media_type, page=3
    )

    assert len(results) == 1
    assert results[0].original_language == item["original_language"]
    assert seen["auth"] == "Bearer test-token"
    assert f"trending/{media_type}/day" in seen["url"]
    assert "page=3" in seen["url"]
    assert "language=" not in seen["url"]


@pytest.mark.asyncio
async def test_get_trending_raises_on_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status_message": "Invalid token"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await get_trending(client, token="bad-token", media_type="movie", page=1)
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

    assert data.id == 1
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
    raw = DetailsMovieResponseData.model_validate(
        {
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
    )
    out = normalize_title(raw, "movie")
    assert out is not None
    assert out["title"]["title"] == "Dune"
    assert out["title"]["language_name"] == "English"
    assert out["title"]["release_date"] == "2021-09-15"
    assert out["reviews"] == [{"id": "r1", "content": "Great film"}]
    assert out["genres"] == [{"id": 0, "name": "Sci-Fi"}]


def test_normalize_title_tv_falls_back_to_creators() -> None:
    raw = DetailsTvResponseData.model_validate(
        {
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
    )
    out = normalize_title(raw, "tv")
    assert out is not None
    assert out["title"]["title"] == "Shogun"
    assert out["title"]["language_name"] == ""
    assert out["reviews"] == []


def test_normalize_title_dedupes_duplicate_actors_keeping_lowest_order() -> None:
    raw = DetailsMovieResponseData.model_validate(
        {
            "id": 3,
            "title": "Dup",
            "credits": {
                "cast": [
                    {"id": 1, "name": "A", "order": 5},
                    {"id": 1, "name": "A", "order": 0},
                    {"id": 2, "name": "B", "order": 1},
                ],
                "crew": [],
            },
            "reviews": {"results": []},
        }
    )
    out = normalize_title(raw, "movie")
    assert out is not None
    ids = [a["id"] for a in out["actors"]]
    assert ids == [1, 2]
    assert out["actors"][0]["order"] == 0


def test_normalize_title_truncates_actors_to_five() -> None:
    raw = DetailsMovieResponseData.model_validate(
        {
            "id": 4,
            "title": "Many",
            "credits": {
                "cast": [{"id": i, "name": f"A{i}", "order": i} for i in range(10)],
                "crew": [],
            },
            "reviews": {"results": []},
        }
    )
    out = normalize_title(raw, "movie")
    assert out is not None
    assert len(out["actors"]) == 5
    assert [a["id"] for a in out["actors"]] == [0, 1, 2, 3, 4]


def test_normalize_title_returns_none_without_usable_id() -> None:
    out = normalize_title({"title": "No id"}, "movie")
    assert out is None


def test_normalize_title_filters_crew_by_director_job() -> None:
    raw = DetailsMovieResponseData.model_validate(
        {
            "id": 5,
            "title": "Crew",
            "credits": {
                "cast": [],
                "crew": [
                    {"id": 1, "name": "Dir", "job": "Director"},
                    {"id": 2, "name": "Prod", "job": "Producer"},
                    {"id": 1, "name": "Dir", "job": "Director"},
                ],
            },
            "reviews": {"results": []},
        }
    )
    out = normalize_title(raw, "movie")
    assert out is not None
    assert out["directors"] == [{"id": 1, "name": "Dir"}]


def test_response_models_ignore_extra_fields_and_default_missing() -> None:
    movie = DetailsMovieResponseData.model_validate(
        {"id": 9, "unknown_field": "ignored"}
    )
    assert movie.id == 9
    assert movie.title == ""
    assert movie.credits.cast == []


member = st.fixed_dictionaries(
    {"name": st.text(), "order": st.integers(min_value=0, max_value=50)}
)
partial_details = st.fixed_dictionaries(
    {},
    optional={
        "id": st.integers(),
        "title": st.text(),
        "name": st.text(),
        "original_language": st.text(),
        "spoken_languages": st.lists(
            st.fixed_dictionaries({"english_name": st.text()}), max_size=2
        ),
        "genres": st.lists(st.fixed_dictionaries({"name": st.text()}), max_size=10),
        "release_date": st.text(),
        "first_air_date": st.text(),
        "credits": st.fixed_dictionaries(
            {},
            optional={
                "cast": st.lists(member, max_size=20),
                "crew": st.lists(
                    st.fixed_dictionaries({"name": st.text(), "job": st.text()}),
                    max_size=20,
                ),
            },
        ),
        "created_by": st.lists(st.fixed_dictionaries({"name": st.text()}), max_size=2),
        "reviews": st.fixed_dictionaries(
            {
                "results": st.lists(
                    st.fixed_dictionaries({"id": st.text(), "content": st.text()}),
                    max_size=20,
                )
            }
        ),
    },
)


@pytest.mark.hypothesis
@given(raw=partial_details)
def test_normalize_title_never_crashes_on_partial_payload(
    raw: dict[str, Any],
) -> None:
    out = normalize_title(raw, "movie")  # type: ignore[arg-type]
    if out is None:
        return
    assert set(out) == {"title", "reviews", "genres", "actors", "directors"}
    assert isinstance(out["title"]["title"], str)
