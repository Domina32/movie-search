# Semantic movie search

## Useful commands

- Run all services
  `docker compose --profile ingest --profile embed up`

- Get api health
  ``

- Get 5 titles
  `curl "http://localhost:8001/titles?limit=5"`

- Get a title_id
  `curl -s 'http://localhost:8001/titles?limit=1' | jq -r '.data[0].id'`

- Get title with title_id
  `curl -s "http://localhost:8001/titles/$title_id"`

- Search for titles with natural language query
  `curl "http://localhost:8001/search?q=lonely+astronaut+drifting+in+space&n=3"`
  `curl "http://localhost:8001/search?q=heist+gone+wrong&n=5&media_type=movie"`

## Usage

1. Run docker command for running all services. After build, it automatically starts fetching all trending titles for the previous day and generating embeddings for reviews. For limiting how many titles to fetch on future runs, use MAX_PAGES environment variable.
2. After ingestion and embedding is complete, use the following API endpoints for fetching titles:
   | Method | Path                 | Params                                                                                   | Response                                                                                              |
   | ------ | -------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
   | GET    | `/health`            | —                                                                                        | {"status": "ok"}                                                                                      |
   | GET    | `/ready`             | —                                                                                        | 200 ready, 503 until embed model loaded                                                               |
   | GET    | `/titles`            | `limit` 1–100 (default 20), `offset` ≥ 0 (default 0)                                     | data: {tmdb_id, media_type, title, original_language, language_name, release_date, fetched_at}, count |
   | GET    | `/titles/{title_id}` | `title_id: UUID`                                                                         | Title + genres, actors, directors, reviews, 404 if missing                                            |
   | GET    | `/search`            | `q` required (1–500 chars), `n` 1–50 (default 5), `media_type` `movie` / `tv` (optional) | query, results: [{ review_id, title_id, title, tmdb_id, media_type, snippet, score }]                 |

## Architecture

TMDB ingest → Postgres → local embeddings → ChromaDB → FastAPI
