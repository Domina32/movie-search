set dotenv-load := true

_default:
    @just --list --unsorted

# ── Tests ──────────────────────────────────────────────────────────────

test:
    uv run pytest

# Fast suite: skip Hypothesis property tests.
test-fast:
    uv run pytest -m "not hypothesis"

# ── Lint / checks ──────────────────────────────────────────────────────

lint:
    uv run ruff check src tests
    uv run ruff format --check src tests

typecheck:
    uv run pyrefly check src tests

check: lint typecheck test

# -- Services -----------------------------------------------------------

# Start local Postgres (idempotent: reuses container if present).
db:
    docker start movie-pg 2>/dev/null || docker run -d --name movie-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=movie_search -p 5432:5432 -v movie-pg-data:/var/lib/postgresql/data postgres:16

# Stop local Postgres, keep data.
db-down:
    docker stop movie-pg

# Apply migrations. Needs DB up.
migrate: db
    PYTHONPATH=src uv run alembic upgrade head

# -- App scripts --------------------------------------------------------

# Ingest trending into Postgres. Needs `just db` first.
fetch-titles: db migrate
    PYTHONPATH=src uv run python -m ingest.runner
