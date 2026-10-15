from typing import Any

import pytest

import search.chroma as chroma_mod
from search.chroma import query_reviews, store_embeddings


class FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.upsert_calls: list[dict[str, Any]] = []
        self.last_where: Any = None

    async def upsert(
        self,
        ids: list[str],
        embeddings: Any,
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        self.upsert_calls.append({"ids": list(ids)})
        for i, doc, meta in zip(ids, documents, metadatas, strict=True):
            self.docs[i] = {"document": doc, "metadata": meta}

    async def count(self) -> int:
        return len(self.docs)

    async def query(
        self,
        query_embeddings: Any = None,
        n_results: int = 5,
        where: Any = None,
    ) -> dict[str, Any]:
        self.last_where = where
        ordered = sorted(self.docs.items())
        ids = [k for k, _ in ordered[:n_results]]
        return {
            "ids": [ids],
            "documents": [[self.docs[i]["document"] for i in ids]],
            "metadatas": [[self.docs[i]["metadata"] for i in ids]],
            "distances": [[0.1 * (j + 1) for j in range(len(ids))]],
        }


def _review(i: int, title_id: str = "t1") -> dict[str, Any]:
    return {
        "id": f"r{i}",
        "content": f"content {i}",
        "title_id": title_id,
        "title": "Dune",
        "tmdb_id": 1,
        "media_type": "movie",
    }


@pytest.mark.asyncio
async def test_store_upserts_with_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def _embed(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3 for _ in texts]

    monkeypatch.setattr(chroma_mod, "embed_texts", _embed)
    col = FakeCollection()
    total = await store_embeddings(col, [_review(1), _review(2)])  # type: ignore[list-item]
    assert total == 2
    assert col.docs["r1"]["metadata"] == {
        "title_id": "t1",
        "title": "Dune",
        "tmdb_id": 1,
        "media_type": "movie",
    }


@pytest.mark.asyncio
async def test_store_batches_and_reupsert_overwrites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _embed(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3 for _ in texts]

    monkeypatch.setattr(chroma_mod, "embed_texts", _embed)
    monkeypatch.setattr(chroma_mod, "EMBED_BATCH_SIZE", 2)
    col = FakeCollection()
    records = [_review(i) for i in range(5)]
    assert await store_embeddings(col, records) == 5  # type: ignore[arg-type]
    assert len(col.upsert_calls) == 3
    again = _review(0)
    again["content"] = "updated"
    assert await store_embeddings(col, [again]) == 1  # type: ignore[list-item]
    assert col.docs["r0"]["document"] == "updated"


@pytest.mark.asyncio
async def test_query_empty_returns_none() -> None:
    assert await query_reviews(FakeCollection(), [0.0], n=5) is not None  # type: ignore[arg-type]
    assert await query_reviews(FakeCollection(), [0.0], n=5) == []  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_query_dedupes_per_title_and_scores() -> None:
    col = FakeCollection()
    col.docs = {
        "r1": {
            "document": "x" * 600,
            "metadata": {
                "title_id": "t1",
                "title": "Dune",
                "tmdb_id": 1,
                "media_type": "movie",
            },
        },
        "r2": {
            "document": "y",
            "metadata": {
                "title_id": "t1",
                "title": "Dune",
                "tmdb_id": 1,
                "media_type": "movie",
            },
        },
        "r3": {
            "document": "z",
            "metadata": {
                "title_id": "t2",
                "title": "Shogun",
                "tmdb_id": 2.0,
                "media_type": "tv",
            },
        },
        "r4": {
            "document": "w",
            "metadata": {
                "title_id": "t3",
                "title": "Other",
                "tmdb_id": 3,
                "media_type": "movie",
            },
        },
    }
    hits = await query_reviews(col, [0.0], n=2)  # type: ignore[arg-type]
    assert [h["title_id"] for h in hits] == ["t1", "t2"]
    assert hits[0]["score"] == pytest.approx(0.9)
    assert len(hits[0]["snippet"]) <= 500
    assert hits[2 - 1]["tmdb_id"] == 2


@pytest.mark.asyncio
async def test_query_passes_media_type_filter() -> None:
    col = FakeCollection()
    col.docs = {
        "r1": {"document": "x", "metadata": {"title_id": "t1", "media_type": "movie"}}
    }
    await query_reviews(col, [0.0], n=1, media_type="movie")  # type: ignore[arg-type]
    assert col.last_where == {"media_type": "movie"}


@pytest.mark.asyncio
async def test_query_finds_second_title_when_first_fetch_is_single_title() -> None:
    col = FakeCollection()
    col.docs = {
        "r1": {
            "document": "x",
            "metadata": {"title_id": "t1", "title": "A", "tmdb_id": 1},
        },
        "r2": {
            "document": "y",
            "metadata": {"title_id": "t1", "title": "A", "tmdb_id": 1},
        },
        "r3": {
            "document": "z",
            "metadata": {"title_id": "t2", "title": "B", "tmdb_id": 2},
        },
    }
    hits = await query_reviews(col, [0.0], n=2)  # type: ignore[arg-type]
    assert [h["title_id"] for h in hits] == ["t1", "t2"]
