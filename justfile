set dotenv-load

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

lint-fix:
    uv run ruff check --fix

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

# Ingest trending into Postgres.
fetch-titles: db migrate
    PYTHONPATH=src uv run python -m ingest.runner

# Serve async API.
api: db migrate
    PYTHONPATH=src uv run uvicorn api.routes:app --reload --port 8001

# ── DB reset (dev) ───────────────────────────────────────────────────

# Wipe DB clean (keeps container). Dev only!
db-nuke:
    docker exec movie-pg psql -U postgres -d movie_search -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO postgres; GRANT ALL ON SCHEMA public TO public;"

# New migration from src/db/models.py. Usage: just db-revision "add foo"
db-revision msg="initial schema":
    PYTHONPATH=src uv run alembic revision --autogenerate -m "{{msg}}"

# Full fresh start (for right now): nuke + new revision + apply
db-fresh msg="initial schema":
    just db-nuke
    PYTHONPATH=src uv run alembic revision --autogenerate -m "{{msg}}"
    PYTHONPATH=src uv run alembic upgrade head
    docker exec movie-pg psql -U postgres -d movie_search -c '\dt'
