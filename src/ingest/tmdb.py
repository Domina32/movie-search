"""TMDB API client."""

from datetime import UTC, datetime
from typing import Literal, TypedDict, cast

import httpx

from config import LOG, pretty_format

BASE_URL = "https://api.themoviedb.org/3"

DIRECTOR_JOBS = frozenset({"Director", "Co-Director", "Series Director"})


class GenreResponseData(TypedDict):
    id: int
    name: str


class CreatorResponseData(TypedDict):
    id: int
    name: str


class CastResponseData(TypedDict):
    id: int
    name: str
    order: int


class CrewResponseData(TypedDict):
    id: int
    name: str
    job: str


class CreditsResponseData(TypedDict):
    cast: list[CastResponseData]
    crew: list[CrewResponseData]


class ReviewResponseData(TypedDict):
    id: str
    content: str


class ReviewsResponseData(TypedDict):
    results: list[ReviewResponseData]


class LanguageResponseData(TypedDict):
    english_name: str


class TrendingMovieTitleResponseData(TypedDict):
    id: int
    title: str
    original_language: str


class TrendingTvTitleResponseData(TypedDict):
    id: int
    name: str
    original_language: str


class DetailsTvResponseData(TypedDict):
    id: int
    name: str
    original_language: str
    spoken_languages: list[LanguageResponseData]
    genres: list[GenreResponseData]
    first_air_date: str
    credits: CreditsResponseData
    created_by: list[CreatorResponseData]
    reviews: ReviewsResponseData


class DetailsMovieResponseData(TypedDict):
    id: int
    title: str
    original_language: str
    spoken_languages: list[LanguageResponseData]
    genres: list[GenreResponseData]
    release_date: str
    credits: CreditsResponseData
    reviews: ReviewsResponseData


class NormalizedReviewData(TypedDict):
    id: str
    content: str


class NormalizedGenreData(TypedDict):
    id: int
    name: str


class NormalizedCreditsMemberData(TypedDict):
    id: int
    role: Literal["actor", "director"]
    name: str
    order: int | None
    job: str | None


class NormalizedTitleData(TypedDict):
    tmdb_id: int
    title: str
    original_language: str
    language_name: str
    release_date: str
    fetched_at: str
    media_type: Literal["movie", "tv"]


class NormalizedTitleResultData(TypedDict):
    title: NormalizedTitleData
    reviews: list[NormalizedReviewData]
    genres: list[NormalizedGenreData]
    actors: list[NormalizedCreditsMemberData]
    directors: list[NormalizedCreditsMemberData]


async def get_trending(
    client: httpx.AsyncClient,
    token: str,
    media_type: Literal["movie", "tv"],
    page: int,
) -> list[dict[str, TrendingTvTitleResponseData | TrendingMovieTitleResponseData]]:
    """
    Get trending movies and tv shows for the day.
    """
    response = await client.get(
        f"{BASE_URL}/trending/{media_type}/day",
        headers={"Authorization": f"Bearer {token}"},
        params={"page": page},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json().get("results", [])


async def get_title_details(
    client: httpx.AsyncClient,
    token: str,
    media_type: Literal["movie", "tv"],
    title_id: int,
) -> DetailsMovieResponseData | DetailsTvResponseData:
    """
    Get metadata for movie or tv show by id.
    """
    LOG.debug(f"Fetching details for title id {title_id}.")

    response = await client.get(
        f"{BASE_URL}/{media_type}/{title_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={"append_to_response": "credits,reviews"},
        timeout=10.0,
    )
    response.raise_for_status()

    LOG.debug(f"Fetched details for title id {title_id}.")

    return response.json()


def normalize_title(
    raw: DetailsTvResponseData | DetailsMovieResponseData,
    media_type: Literal["movie", "tv"],
) -> NormalizedTitleResultData | None:
    """
    Parse response data for title into shape with details, credits and reviews.
    Returns None when the payload has no usable TMDB id (nothing to store).
    """
    raw_id = raw.get("id")
    if not isinstance(raw_id, int):
        return None

    actors: list[NormalizedCreditsMemberData] = []
    directors: list[NormalizedCreditsMemberData] = []
    credits = raw.get("credits") or {}
    crew = credits.get("crew") or []
    # get creators for tv shows, not directors of individual episodes
    if "created_by" in raw:
        creators = cast("DetailsTvResponseData", raw).get("created_by")
        directors = [
            {
                "id": member.get("id"),
                "role": "director",
                "name": (member.get("name") or "").strip(),
                "order": None,
                "job": None,
            }
            for member in creators
        ]
    else:
        directors = [
            {
                "id": member.get("id"),
                "role": "director",
                "name": (member.get("name") or "").strip(),
                "order": None,
                "job": member.get("job"),
            }
            for member in crew
            if member.get("job") in DIRECTOR_JOBS
        ]

    # get human readable language name
    spoken = raw.get("spoken_languages") or []
    language_name = spoken[0].get("english_name", "") if spoken else ""

    genres: list[NormalizedGenreData] = []
    seen_genre_ids: set[int] = set()
    for g in raw.get("genres") or []:
        gid = g.get("id")
        gname = (g.get("name") or "").strip()
        if not isinstance(gid, int) or not gname or gid in seen_genre_ids:
            continue
        seen_genre_ids.add(gid)
        genres.append({"id": gid, "name": gname})

    reviews_block = raw.get("reviews") or {}
    review_items = reviews_block.get("results") or []
    reviews: list[NormalizedReviewData] = [
        {
            "id": r.get("id", ""),
            "content": r.get("content", ""),
        }
        for r in review_items
        if r.get("content")
    ]

    if media_type == "movie":
        title = cast("DetailsMovieResponseData", raw).get("title") or ""
        release_date = cast("DetailsMovieResponseData", raw).get("release_date") or ""
    else:
        title = cast("DetailsTvResponseData", raw).get("name") or ""
        release_date = cast("DetailsTvResponseData", raw).get("first_air_date") or ""
        LOG.info(pretty_format(raw))

    return {
        "title": {
            "tmdb_id": raw_id,
            "title": title,
            "original_language": raw.get("original_language", ""),
            "language_name": language_name,
            "release_date": release_date,
            "fetched_at": datetime.now(UTC).isoformat(),
            "media_type": media_type,
        },
        "reviews": reviews,
        "genres": genres,
        "actors": actors,
        "directors": directors,
    }
