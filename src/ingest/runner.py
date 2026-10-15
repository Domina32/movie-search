import asyncio
import time
from asyncio import Task, TaskGroup
from collections.abc import Coroutine
from typing import Any, Literal

import httpx
from httpx import AsyncClient

from config import LOG, PROFILING_ENABLED, get_max_pages, get_tmdb_read_token
from db.session import async_db, store_titles
from ingest.tmdb import (
    NormalizedTitleResultData,
    TrendingMovieTitleResponseData,
    TrendingTvTitleResponseData,
    get_title_details,
    get_trending,
    normalize_title,
)

# rate limit: 40 requests per 1 second
# API response page size is 20 titles
# so we can safely execute 20+1 requests
# in half the rate limit time (0.5 sec)
# and add 0.1sec overhead for safety
THROTTLE_TIME = 0.6


async def build_title(
    item: TrendingMovieTitleResponseData | TrendingTvTitleResponseData,
    client: httpx.AsyncClient,
    token: str,
    media_type: Literal["movie", "tv"],
) -> NormalizedTitleResultData | None:
    title_id = item.id
    if title_id < 0:
        return None
    raw = await get_title_details(client, token, media_type, title_id)
    record = normalize_title(raw, media_type)

    return record


async def run_tasks[T](coroutines: list[Coroutine[Any, Any, T | None]]) -> list[T]:
    tasks: list[Task[T | None]] = []
    async with TaskGroup() as tg:
        for coroutine in coroutines:
            tasks.append(tg.create_task(coroutine))
    batch: list[T] = []
    for task in tasks:
        record = task.result()
        if record is None:
            continue
        batch.append(record)
    return batch


async def fetch_titles(client: AsyncClient, max_pages: int | None = None) -> None:
    """
    Fetch titles, normalize and store into db.
    """
    if max_pages is None:
        max_pages = get_max_pages()

    token = get_tmdb_read_token()
    media_types: tuple[Literal["movie", "tv"], ...] = ("movie", "tv")

    try:
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

                LOG.debug(
                    f"Fetching page {current_page}/{max_pages} for media type {media_type}."
                )
                title_items = await get_trending(
                    client, token, media_type, current_page
                )
                LOG.info(f"Fetched page {current_page} for media type {media_type}.")
                title_coroutines = [
                    build_title(item, client, token, media_type) for item in title_items
                ]
                title_batch = await run_tasks(title_coroutines)
                stored = await store_titles(title_batch)
                LOG.debug(
                    "Stored type=%s page=%d/%d fetched=%d stored=%d",
                    media_type,
                    current_page,
                    max_pages,
                    len(title_batch),
                    len(stored),
                )
    finally:
        await async_db.dispose()


async def main():
    async with httpx.AsyncClient() as client:
        if PROFILING_ENABLED:
            import pyinstrument

            with pyinstrument.profile():
                await fetch_titles(client)
        else:
            await fetch_titles(client)


if __name__ == "__main__":
    asyncio.run(main())
