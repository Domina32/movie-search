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


class NormalizedDirectorData(TypedDict):
    id: int
    name: str


class NormalizedActorData(TypedDict):
    id: int
    name: str
    order: int


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
    actors: list[NormalizedActorData]
    directors: list[NormalizedDirectorData]


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

    actors: list[NormalizedActorData] = []
    directors: list[NormalizedDirectorData] = []
    credits = raw.get("credits") or {}
    crew_members = credits.get("crew") or []
    cast_members = credits.get("cast") or []
    sorted_actors: list[NormalizedActorData] = sorted(
        [
            {
                "id": member["id"],
                "name": (member.get("name") or "").strip(),
                "order": member.get("order"),
            }
            for member in cast_members
            if "id" in member
        ],
        key=lambda m: m["order"],
    )
    seen_actor_ids: set[int] = set()
    for a in sorted_actors:
        if a["id"] in seen_actor_ids:
            continue
        seen_actor_ids.add(a["id"])
        actors.append(a)

    # get creators for tv shows, not directors of individual episodes
    if "created_by" in raw:
        creators = cast(DetailsTvResponseData, raw).get("created_by")
        sorted_directors = [
            {
                "id": member["id"],
                "name": (member.get("name") or "").strip(),
            }
            for member in creators
            if "id" in member
        ]
    else:
        sorted_directors = [
            {
                "id": member["id"],
                "name": (member.get("name") or "").strip(),
            }
            for member in crew_members
            if "id" in member
            if member.get("job") in DIRECTOR_JOBS
        ]
    seen_director_ids: set[int] = set()
    for d in sorted_directors:
        if d["id"] in seen_director_ids:
            continue
        seen_director_ids.add(d["id"])
        directors.append(d)

    # get human readable language name
    spoken = raw.get("spoken_languages") or []
    language_name = spoken[0].get("english_name", "") if spoken else ""

    genres: list[NormalizedGenreData] = [
        {
            "id": genre["id"],
            "name": genre["name"].strip(),
        }
        for genre in raw.get("genres") or []
        if "id" in genre and genre.get("name")
    ]

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
        title = cast(DetailsMovieResponseData, raw).get("title") or ""
        release_date = cast(DetailsMovieResponseData, raw).get("release_date") or ""
    else:
        title = cast(DetailsTvResponseData, raw).get("name") or ""
        release_date = cast(DetailsTvResponseData, raw).get("first_air_date") or ""
        LOG.debug(pretty_format(raw))

    deduped_actors: list[NormalizedActorData] = list(
        {member["id"]: member for member in actors}.values()
    )[:5]
    deduped_directors: list[NormalizedDirectorData] = list(
        {member["id"]: member for member in directors}.values()
    )

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
        "actors": deduped_actors,
        "directors": deduped_directors,
    }
