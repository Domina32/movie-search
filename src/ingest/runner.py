import asyncio
from asyncio import Task
from typing import Any, Literal

import httpx

from config import LOG, get_max_pages, get_tmdb_read_token
from ingest.tmdb import get_title_details, get_trending, normalize_title

# rate limit: 40 requests per 1 second


async def build_title(
    item: dict[str, Any],
    client: httpx.AsyncClient,
    token: str,
    media_type: Literal["movie", "tv"],
) -> dict[str, Any] | None:
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

    async with httpx.AsyncClient() as client:
        for media_type in media_types:
            for current_page in range(1, max_pages + 1):
                LOG.debug(f"Fetching page {current_page} for media type {media_type}.")
                items = await get_trending(client, token, media_type)
                title_tasks = [
                    build_title(item, client, token, media_type) for item in items
                ]
                titles: list[Task[dict[str, Any] | None]] = []
                async with asyncio.TaskGroup() as tg:
                    for task in title_tasks:
                        _task = tg.create_task(task)
                        titles.append(_task)

                for title_task in titles:
                    record = title_task.result()
                    if record is None:
                        continue
                    LOG.debug(
                        "%s | %s (%s) | %s | %s | %s | %s | %d reviews",
                        record["title"],
                        record["language_name"] or "-",
                        record["original_language"],
                        record["release_date"],
                        ", ".join(record["genres"]),
                        ", ".join(record["actors"]),
                        ", ".join(record["directors"]),
                        len(record["reviews"]),
                    )


if __name__ == "__main__":
    asyncio.run(fetch_titles())
