set dotenv-load

_default:
    @just --list --unsorted

# ── Tests ──────────────────────────────────────────────────────────────

test:
    uv run pytest

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

db:
    docker start movie-pg 2>/dev/null || docker run -d --name movie-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=movie_search -p 5432:5432 -v movie-pg-data:/var/lib/postgresql/data postgres:16

db-down:
    docker stop movie-pg

migrate: db
    PYTHONPATH=src uv run alembic upgrade head

chroma:
    docker start chroma 2>/dev/null || docker run -d --name chroma -p 8002:8000 -v chroma-data:/data ghcr.io/chroma-core/chroma:1.5.9

chroma-down:
    docker stop chroma

# -- App scripts --------------------------------------------------------

# Ingest trending titles into Postgres
fetch: db migrate
    PYTHONPATH=src uv run python -m ingest.runner

store:
    PYTHONPATH=src uv run python -m db.runner

embed:
    PYTHONPATH=src uv run python -m search.runner

# Serve async API
api: db migrate
    PYTHONPATH=src uv run uvicorn api.routes:app --reload --port 8001

# ── DB reset (dev) ───────────────────────────────────────────────────

db-nuke:
    docker exec movie-pg psql -U postgres -d movie_search -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO postgres; GRANT ALL ON SCHEMA public TO public;"

# New migration from src/db/models.py. Usage: just db-revision "add foo"
db-revision msg="initial schema":
    PYTHONPATH=src uv run alembic revision --autogenerate -m "{{ msg }}"

# Full fresh start (keeps migration files intact)
db-fresh:
    just db-nuke
    PYTHONPATH=src uv run alembic upgrade head
    docker exec movie-pg psql -U postgres -d movie_search -c '\dt'
