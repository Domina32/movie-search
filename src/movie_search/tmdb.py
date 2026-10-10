"""TMDB API client."""

from typing import Any, Literal

import httpx

BASE_URL = "https://api.themoviedb.org/3"


def get_trending(
    client: httpx.Client, token: str, media_type: Literal["movie", "tv"], page: int = 1
) -> list[dict[str, Any]]:
    """
    Get trending movies and tv shows for the day.
    """
    response = client.get(
        f"{BASE_URL}/trending/{media_type}/day",
        headers={"Authorization": f"Bearer {token}"},
        params={"page": page},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json().get("results", [])


def get_title_details(
    client: httpx.Client, token: str, media_type: Literal["movie", "tv"], title_id: int
) -> dict[str, Any]:
    """
    Get metadata for movie or tv show by id.
    """
    response = client.get(
        f"{BASE_URL}/{media_type}/{title_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={"append_to_response": "credits,reviews"},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def normalize_title(
    raw: dict[str, Any], media_type: Literal["movie", "tv"]
) -> dict[str, Any]:
    """
    Parse response data for title into shape with details, credits and reviews.
    """
    credits: dict[str, Any] = raw.get("credits") or {}
    cast: list[dict[str, Any]] = credits.get("cast") or []
    crew: list[dict[str, Any]] = credits.get("crew") or []

    actors = [
        member.get("name", "")
        for member in sorted(cast, key=lambda x: x.get("order", 999))
        if member.get("name")
    ][:5]

    directors = [
        member.get("name", "")
        for member in crew
        if member.get("job") == "Director" and member.get("name")
    ]
    # plan b for tv shows with no directors:
    # credit creators instead which is tv show equivalent
    if not directors and media_type == "tv":
        created = raw.get("created_by") or []
        directors = [member.get("name", "") for member in created if member.get("name")]

    # get human readable language name
    spoken: list[dict[str, Any]] = raw.get("spoken_languages") or []
    language_name = str(spoken[0].get("english_name", "")) if spoken else ""

    genres = [g.get("name", "") for g in (raw.get("genres") or []) if g.get("name")]

    reviews_block: dict[str, Any] = raw.get("reviews") or {}
    review_items: list[dict[str, Any]] = reviews_block.get("results") or []
    reviews = [
        {
            "id": r.get("id", ""),
            "content": r.get("content", ""),
        }
        for r in review_items
        if r.get("content")
    ]

    return {
        "tmdb_id": raw.get("id"),
        "media_type": media_type,
        "title": raw.get("title") or raw.get("name") or "",
        "original_language": raw.get("original_language", ""),
        "language_name": language_name,
        "genres": genres,
        "release_date": raw.get("release_date") or raw.get("first_air_date") or "",
        "actors": actors,
        "directors": directors,
        "reviews": reviews,
    }
