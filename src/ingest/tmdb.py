"""TMDB API client."""

from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

import httpx
from pydantic import BaseModel, ConfigDict, Field

from config import LOG, pretty_format

BASE_URL = "https://api.themoviedb.org/3"

DIRECTOR_JOBS = frozenset({"Director", "Co-Director", "Series Director"})


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class GenreResponseData(StrictModel):
    id: int = -1
    name: str = ""


class CreatorResponseData(StrictModel):
    id: int = -1
    name: str = ""


class CastResponseData(StrictModel):
    id: int = -1
    name: str = ""
    order: int = 9999


class CrewResponseData(StrictModel):
    id: int = -1
    name: str = ""
    job: str = ""


class CreditsResponseData(StrictModel):
    cast: list[CastResponseData] = Field(default_factory=list)
    crew: list[CrewResponseData] = Field(default_factory=list)


class ReviewResponseData(StrictModel):
    id: str = ""
    content: str = ""


class ReviewsResponseData(StrictModel):
    results: list[ReviewResponseData] = Field(default_factory=list)


class LanguageResponseData(StrictModel):
    english_name: str = ""


class TrendingMovieTitleResponseData(StrictModel):
    id: int = -1
    title: str = ""
    original_language: str = ""


class TrendingTvTitleResponseData(StrictModel):
    id: int = -1
    name: str = ""
    original_language: str = ""


class DetailsTvResponseData(StrictModel):
    id: int | None = None
    name: str = ""
    original_language: str = ""
    spoken_languages: list[LanguageResponseData] = Field(default_factory=list)
    genres: list[GenreResponseData] = Field(default_factory=list)
    first_air_date: str = ""
    credits: CreditsResponseData = Field(default_factory=CreditsResponseData)
    created_by: list[CreatorResponseData] = Field(default_factory=list)
    reviews: ReviewsResponseData = Field(default_factory=ReviewsResponseData)


class DetailsMovieResponseData(StrictModel):
    id: int | None = None
    title: str = ""
    original_language: str = ""
    spoken_languages: list[LanguageResponseData] = Field(default_factory=list)
    genres: list[GenreResponseData] = Field(default_factory=list)
    release_date: str = ""
    credits: CreditsResponseData = Field(default_factory=CreditsResponseData)
    reviews: ReviewsResponseData = Field(default_factory=ReviewsResponseData)


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
) -> list[TrendingTvTitleResponseData | TrendingMovieTitleResponseData]:
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
    model = (
        TrendingMovieTitleResponseData
        if media_type == "movie"
        else TrendingTvTitleResponseData
    )
    return [
        model.model_validate(item)
        for item in response.json().get("results", [])
        if isinstance(item, dict)
    ]


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

    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected TMDB payload for {media_type}/{title_id}")
    if media_type == "movie":
        return DetailsMovieResponseData.model_validate(payload)
    return DetailsTvResponseData.model_validate(payload)


def normalize_title(
    raw: DetailsTvResponseData | DetailsMovieResponseData | dict[str, Any],
    media_type: Literal["movie", "tv"],
) -> NormalizedTitleResultData | None:
    """
    Parse response data for title into shape with details, credits and reviews.
    Returns None when the payload has no usable TMDB id (nothing to store).
    """
    if isinstance(raw, dict):
        model = (
            DetailsMovieResponseData if media_type == "movie" else DetailsTvResponseData
        )
        parsed = model.model_validate(raw)
    else:
        parsed = raw
    if not isinstance(parsed.id, int):
        return None
    raw_id = parsed.id

    credits = parsed.credits
    crew_members = credits.crew
    cast_members = credits.cast
    sorted_actors: list[NormalizedActorData] = sorted(
        [
            {
                "id": member.id,
                "name": (member.name or "").strip(),
                "order": member.order,
            }
            for member in cast_members
            if member.id >= 0
        ],
        key=lambda m: m["order"],
    )
    seen_actor_ids: set[int] = set()
    actors: list[NormalizedActorData] = []
    for a in sorted_actors:
        if a["id"] in seen_actor_ids:
            continue
        seen_actor_ids.add(a["id"])
        actors.append(a)

    # get creators for tv shows, not directors of individual episodes
    if isinstance(parsed, DetailsTvResponseData) and parsed.created_by:
        sorted_directors = [
            {
                "id": member.id,
                "name": (member.name or "").strip(),
            }
            for member in parsed.created_by
            if member.id >= 0
        ]
    else:
        sorted_directors = [
            {
                "id": member.id,
                "name": (member.name or "").strip(),
            }
            for member in crew_members
            if member.id >= 0
            if member.job in DIRECTOR_JOBS
        ]
    seen_director_ids: set[int] = set()
    directors: list[NormalizedDirectorData] = []
    for d in sorted_directors:
        if d["id"] in seen_director_ids:
            continue
        seen_director_ids.add(d["id"])
        directors.append(d)

    # get human readable language name
    spoken = parsed.spoken_languages
    language_name = spoken[0].english_name if spoken else ""

    genres: list[NormalizedGenreData] = [
        {
            "id": genre.id,
            "name": genre.name.strip(),
        }
        for genre in parsed.genres
        if genre.id >= 0 and genre.name.strip()
    ]

    reviews: list[NormalizedReviewData] = [
        {
            "id": r.id,
            "content": r.content,
        }
        for r in parsed.reviews.results
        if r.content
    ]

    if isinstance(parsed, DetailsMovieResponseData):
        title = parsed.title
        release_date = parsed.release_date
    else:
        title = parsed.name
        release_date = parsed.first_air_date
        LOG.debug(pretty_format(parsed.model_dump()))

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
            "original_language": parsed.original_language,
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
