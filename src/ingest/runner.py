import asyncio
import time
from asyncio import Task
from collections.abc import Coroutine
from typing import Any, Literal
from uuid import UUID

import httpx

from config import LOG, get_max_pages, get_tmdb_read_token
from db.session import async_db, store_titles
from ingest.chroma import (
    ReviewData,
    get_chroma_collection,
    initialize_chroma_client,
    store_reviews,
)
from ingest.tmdb import (
    NormalizedReviewData,
    NormalizedTitleData,
    NormalizedTitleResultData,
    get_title_details,
    get_trending,
    normalize_title,
)
from search.embed import preload_embed_model

# rate limit: 40 requests per 1 second
# API response page size is 20 titles
# so we can safely execute 20+1 requests
# in half the rate limit time (0.5 sec)
# and add 0.1sec overhead for safety
THROTTLE_TIME = 0.6


async def build_title(
    item: dict[str, Any],
    client: httpx.AsyncClient,
    token: str,
    media_type: Literal["movie", "tv"],
) -> NormalizedTitleResultData | None:
    title_id = item.get("id")
    if not isinstance(title_id, int):
        return
    raw = await get_title_details(client, token, media_type, title_id)
    record = normalize_title(raw, media_type)

    return record


async def build_review(
    review: NormalizedReviewData,
    title: NormalizedTitleData,
    title_id: UUID,
) -> ReviewData | None:
    """Join review with its title data."""
    content = review.get("content")
    if not content:
        return None
    return {
        "id": review["id"],
        "content": content,
        "title_id": str(title_id),
        "title": title["title"],
        "tmdb_id": title["tmdb_id"],
        "media_type": title["media_type"],
    }


async def run_tasks[T](coroutines: list[Coroutine[Any, Any, T | None]]) -> list[T]:
    tasks: list[Task[T | None]] = []
    async with asyncio.TaskGroup() as tg:
        for coroutine in coroutines:
            tasks.append(tg.create_task(coroutine))
    batch: list[T] = []
    for task in tasks:
        record = task.result()
        if record is None:
            continue
        batch.append(record)
    return batch


async def fetch_titles(max_pages: int | None = None) -> None:
    if max_pages is None:
        max_pages = get_max_pages()

    token = get_tmdb_read_token()
    media_types: tuple[Literal["movie", "tv"], ...] = ("movie", "tv")
    chroma_client = initialize_chroma_client()
    chroma_collection = get_chroma_collection(chroma_client)

    try:
        async with httpx.AsyncClient() as client:
            for media_type in media_types:
                last_fetch_start_timestamp: float | None = None

                for current_page in range(1, max_pages + 1):
                    current_timestamp = time.monotonic()
                    time_since_last_fetch_started = current_timestamp - (
                        last_fetch_start_timestamp or 0
                    )

                    # We have to throttle if a second has not yet passed to avoid rate limits
                    if time_since_last_fetch_started < THROTTLE_TIME:
                        remaining_time = THROTTLE_TIME - time_since_last_fetch_started

                        await asyncio.sleep(remaining_time)

                    last_fetch_start_timestamp = current_timestamp

                    LOG.info(
                        f"Fetching page {current_page} for media type {media_type}."
                    )
                    title_items = await get_trending(
                        client, token, media_type, current_page
                    )
                    title_coroutines = [
                        build_title(item, client, token, media_type)
                        for item in title_items
                    ]
                    title_batch = await run_tasks(title_coroutines)
                    for record in title_batch:
                        LOG.debug(
                            "%s | %s (%s) | %s | %d reviews",
                            record["title"]["title"],
                            record["title"]["language_name"] or "-",
                            record["title"]["original_language"],
                            record["title"]["release_date"],
                            len(record["reviews"]),
                        )
                    title_ids: list[UUID] = []
                    if title_batch:
                        title_ids = await store_titles(title_batch)
                        LOG.debug(
                            "Stored type=%s page=%d rows=%d",
                            media_type,
                            current_page,
                            len(title_ids),
                        )

                    review_coroutines = [
                        build_review(review, record["title"], title_id)
                        for record, title_id in zip(title_batch, title_ids, strict=True)
                        for review in record.get("reviews", [])
                    ]
                    review_batch = await run_tasks(review_coroutines)
                    for record in review_batch:
                        LOG.debug(
                            "%s | %s",
                            record["id"],
                            record["title"],
                        )
                    if review_batch:
                        stored = store_reviews(chroma_collection, review_batch)
                        LOG.debug(f"Stored {stored}")
    finally:
        await async_db.dispose()


if __name__ == "__main__":
    preload_embed_model()
    asyncio.run(fetch_titles())
