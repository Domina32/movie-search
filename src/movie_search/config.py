import os

from dotenv import load_dotenv

load_dotenv()


def get_tmdb_read_token(token: str | None = None) -> str:
    """
    Read The Movie Database API read access token from .env.
    """
    cleaned = os.getenv("TMDB_API_READ_ACCESS_TOKEN", "").strip()
    if not cleaned:
        raise RuntimeError(
            "Missing TMDB_API_READ_ACCESS_TOKEN. Set it in .env or environment."
        )
    if token is not None:
        return token.strip()
    return cleaned
