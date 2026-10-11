import asyncio
import time
from asyncio import Task
from typing import Any, Literal

import httpx

from config import LOG, get_database_url, get_max_pages, get_tmdb_read_token
from db.session import get_engine, store_titles
from ingest.tmdb import (
    NormalizedTitleResultData,
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


async def fetch_titles(max_pages: int | None = None) -> None:
    if max_pages is None:
        max_pages = get_max_pages()

    token = get_tmdb_read_token()
    media_types: tuple[Literal["movie", "tv"], ...] = ("movie", "tv")
    engine = get_engine(get_database_url())

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

                LOG.debug(f"Fetching page {current_page} for media type {media_type}.")
                items = await get_trending(client, token, media_type, current_page)
                title_tasks = [
                    build_title(item, client, token, media_type) for item in items
                ]
                titles: list[Task[NormalizedTitleResultData | None]] = []
                async with asyncio.TaskGroup() as tg:
                    for task in title_tasks:
                        _task = tg.create_task(task)
                        titles.append(_task)

                batch: list[NormalizedTitleResultData] = []
                for title_task in titles:
                    record = title_task.result()
                    if record is None:
                        continue
                    batch.append(record)
                    LOG.debug(
                        "%s | %s (%s) | %s | %d reviews",
                        record["title"]["title"],
                        record["title"]["language_name"] or "-",
                        record["title"]["original_language"],
                        record["title"]["release_date"],
                        len(record["reviews"]),
                    )

                if batch:
                    stored = store_titles(engine, batch)
                    LOG.debug(
                        "Stored type=%s page=%d rows=%d",
                        media_type,
                        current_page,
                        stored,
                    )


if __name__ == "__main__":
    asyncio.run(fetch_titles())
