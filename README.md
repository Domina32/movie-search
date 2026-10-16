# Semantic movie search

## Useful commands

- Run all services

  `docker compose --profile ingest --profile embed up`

- Get api health

  `curl http://localhost:8001/health`

- Get 5 titles

  `curl "http://localhost:8001/titles?limit=5"`

- Get a title_id

  `curl -s 'http://localhost:8001/titles?limit=1' | jq -r '.data[0].id'`

- Get title with title_id

  `curl -s "http://localhost:8001/titles/title_id"`

- Search for titles with natural language query

  `curl "http://localhost:8001/search?q=lonely+astronaut+drifting+in+space&n=3"`

  `curl "http://localhost:8001/search?q=heist+gone+wrong&n=5&media_type=movie"`

## Usage

1. Create a .env file in the directory root with the following variables:

   `POSTGRES_USER=postgres`

   `POSTGRES_PASSWORD=postgres`

   `POSTGRES_DB=movie_search`

   `MAX_PAGES=500`

   `TMDB_API_READ_ACCESS_TOKEN={token}`

2. Run docker command for running all services:

`docker compose --profile ingest --profile embed up`

After build, it automatically starts fetching all trending titles for the previous day and generating embeddings for reviews. For limiting how many titles to fetch on future runs, use MAX_PAGES environment variable.

3. After ingestion and embedding is complete, use the following API endpoints for fetching titles:

   | Method | Path                 | Params                                                                                   | Response                                                                                              |
   | ------ | -------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
   | GET    | `/health`            | —                                                                                        | {"status": "ok"}                                                                                      |
   | GET    | `/ready`             | —                                                                                        | 200 ready, 503 until embed model loaded                                                               |
   | GET    | `/titles`            | `limit` 1–100 (default 20), `offset` ≥ 0 (default 0)                                     | data: {tmdb_id, media_type, title, original_language, language_name, release_date, fetched_at}, count |
   | GET    | `/titles/{title_id}` | `title_id: UUID`                                                                         | Title + genres, actors, directors, reviews, 404 if missing                                            |
   | GET    | `/search`            | `q` required (1–500 chars), `n` 1–50 (default 5), `media_type` `movie` / `tv` (optional) | query, [{ review_id, title_id, title, tmdb_id, media_type, snippet, score }] results:                 |

## Architecture & decisions

TMDB ingest → Postgres → local embeddings (SentenceTransformers) → ChromaDB → FastAPI

Ingest and embed are separate services so fetching and vectorizing can run concurrently.
The task only implied a single one-day fetch, but the app assumes fetching repeats —
hence idempotent upserts, ingest-run heartbeats, and stale-run cleanup.

### No scheduler

Coordination of ingestion and embedding is done via DB flag writes and polling but they are deliberately
kept as one-off jobs that can then later be scheduled via cron, scheduler or some other strategy.

### Throttling TMDB API requests

The Movie Database API rate limit is 40 requests per 1 second, and response page size is 20 titles.
This means it is safe to execute 20+1 requests in half the rate limit time (0.5 seconds) -- 1 request
for fetching the page, 20 requests for fetching details for each title on the page. Thus, with 0.1 second
overhead for safety, throttling has been set to 0.6 seconds (`src/ingest/runner.py:135`).

### No asyncpg

Alembic requires a sync session anyway, so `psycopg` (+ `psycopg[binary]`) covers both
runtime and migrations with one driver.

### One Title table for movies + TV

Search must return 3–5 most relevant _titles_ across both media types which makes one shared
ranking space. The task wording uses "naslov" (title) as the common term. Splitting tables
would mean fetching top-5 movies + top-5 shows then re-ranking and duplicating TMDB calls.

### SentenceTransformers local embedding model

Local embedding model is chosen instead of outsourcing it to cloud API solutions to keep everything
more self contained. Avoids dealing with usage caps and extra infrastructure/setup/dependencies until
data volume requires more compute power.

### Query prefix (`bge` instruction tokens)

The model was contrastively trained on short-query → long-passage pairs where queries carry
an instruction prefix. Prefixing at inference reproduces the training distribution and
shifts the query vector into the region where relevant passages cluster. Documents were
trained without it, so only queries get the prefix ([reference](https://huggingface.co/BAAI/bge-small-en-v1.5)).
