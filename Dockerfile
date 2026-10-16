FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    UV_LINK_MODE=copy \
    HF_HOME=/root/.cache/huggingface \
    HF_HUB_OFFLINE=0

WORKDIR /app

# libgomp for sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock README.md alembic.ini ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

ARG EMBED_MODEL=BAAI/bge-small-en-v1.5
ENV EMBED_MODEL=${EMBED_MODEL}
RUN --mount=type=cache,target=/root/.cache/huggingface \
    uv run --no-sync python -c "from sentence_transformers import SentenceTransformer; import os; SentenceTransformer(os.environ['EMBED_MODEL'])"

COPY alembic ./alembic
COPY src ./src

EXPOSE 8001

CMD ["sh", "-c", "exec uv run --no-sync uvicorn api.routes:app --host 0.0.0.0 --port 8001"]
