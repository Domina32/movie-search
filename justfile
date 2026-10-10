set dotenv-load := true

_default:
    @just --list --unsorted

# ── Tests ──────────────────────────────────────────────────────────────

test:
    uv run pytest

# ── Lint / checks ──────────────────────────────────────────────────────

lint:
    uv run ruff check src tests
    uv run ruff format --check src tests

typecheck:
    uv run pyrefly check src tests

check: lint typecheck test

# -- App scripts --------------------------------------------------------

fetch-titles:
    PYTHONPATH=src uv run python -m ingest.runner
