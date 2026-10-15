import asyncio
import time
from asyncio import Task, TaskGroup
from collections.abc import Coroutine
from typing import Any, Literal

import httpx
from httpx import AsyncClient
from sqlalchemy.ext.asyncio.session import AsyncSession

from config import (
    LOG,
    PROFILING_ENABLED,
    configure_logging,
    get_max_pages,
    get_tmdb_token,
)
from db.models import IngestStatus
from db.session import async_db, set_ingest_run_status, start_ingest_run, store_titles
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
    try:
        raw = await get_title_details(client, token, media_type, title_id)
    except httpx.HTTPStatusError as e:
        body = (e.response.text or "")[:300] if e.response is not None else ""
        status = e.response.status_code if e.response is not None else "?"
        LOG.warning(
            "TMDB details failed type=%s id=%d status=%s body=%s",
            media_type,
            title_id,
            status,
            body,
        )
        return None
    except (httpx.TimeoutException, httpx.TransportError) as e:
        LOG.warning(
            "TMDB details transport error type=%s id=%d error=%s",
            media_type,
            title_id,
            e,
        )
        return None
    try:
        record = normalize_title(raw, media_type)
    except Exception:
        LOG.exception("TMDB normalize failed type=%s id=%d", media_type, title_id)
        return None

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


async def fetch_titles(
    client: AsyncClient, max_pages: int, session: AsyncSession
) -> None:
    """
    Fetch titles, normalize and store into db.
    """
    token = get_tmdb_token()
    media_types: tuple[Literal["movie", "tv"], ...] = ("movie", "tv")
    run_id = await start_ingest_run(max_pages, session)

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
        await set_ingest_run_status(run_id, IngestStatus.completed, session)
    except Exception:
        LOG.exception("Ingest run %s failed.", run_id)
        await set_ingest_run_status(run_id, IngestStatus.failed, session)
        raise


async def main():
    configure_logging()

    async with httpx.AsyncClient() as client, async_db:
        max_pages = get_max_pages()

        async with async_db.factory()() as session:
            if PROFILING_ENABLED:
                import pyinstrument

                with pyinstrument.profile():
                    await fetch_titles(client, max_pages, session)
            else:
                await fetch_titles(client, max_pages, session)


if __name__ == "__main__":
    asyncio.run(main())
