from uuid import uuid4

from db.models import MediaType
from search.runner import build_review


def test_build_review_returns_none_on_empty_content() -> None:
    title = {"title": "Dune", "tmdb_id": 1, "media_type": MediaType.movie}
    assert build_review({"id": "r1", "content": ""}, title, uuid4()) is None


def test_build_review_joins_title_and_converts_media_type() -> None:
    title_id = uuid4()
    title = {"title": "Dune", "tmdb_id": 7, "media_type": MediaType.tv}
    out = build_review({"id": "r1", "content": "Great"}, title, title_id)
    assert out is not None
    assert out["title_id"] == str(title_id)
    assert out["title"] == "Dune"
    assert out["tmdb_id"] == 7
    assert out["media_type"] == "tv"
