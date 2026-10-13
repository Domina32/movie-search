"""Local embeddings with sentence-transformers."""

import os
import time

from numpy import ndarray
from sentence_transformers import SentenceTransformer

from config import LOG

EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_BATCH = 100
# bge-small context is 512 tokens
MAX_CHARS = 2000
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class LocalEmbedder:
    def __init__(self) -> None:
        self._model: SentenceTransformer | None = None

    def model(self) -> SentenceTransformer:
        if self._model is None:
            LOG.info("Loading embedding model model=%s ...", EMBED_MODEL)
            self._model = SentenceTransformer(EMBED_MODEL)
            LOG.info("Embedding model loaded model=%s", EMBED_MODEL)
        return self._model

    def is_loaded(self) -> bool:
        return self._model is not None


embedder = LocalEmbedder()


def get_embedder() -> SentenceTransformer:
    return embedder.model()


def embed_texts(texts: list[str]) -> ndarray:
    """
    Embed one batch of review contents. Order preserved.
    """
    model = get_embedder()
    truncated = [text[:MAX_CHARS] for text in texts]
    vectors = model.encode(
        truncated,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return vectors


def is_model_loaded() -> bool:
    return embedder.is_loaded()


def embed_query(text: str) -> list[float]:
    """
    Embed a single search query with the BGE retrieval prefix.
    """
    return embed_texts([QUERY_PREFIX + text[:MAX_CHARS]])[0]


def preload_embed_model() -> None:
    """
    Load weights now + warm up with a dummy encode.
    """
    started = time.monotonic()
    model = get_embedder()
    model.encode(
        ["warmup"],
        batch_size=1,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    LOG.info(
        "Embedding model ready model=%s dim=%s took=%.1fs",
        EMBED_MODEL,
        model.get_embedding_dimension(),
        time.monotonic() - started,
    )
