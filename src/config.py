import logging
import os
import pprint
from typing import Any

from dotenv import load_dotenv

pp = pprint.PrettyPrinter(indent=2, sort_dicts=False)


def pretty_format(obj: Any):
    pretty_out = f"{pp.pformat(obj)}"
    return f"{pretty_out}\n"


load_dotenv()

LOG = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
os.makedirs("./logs", exist_ok=True)
logging.basicConfig(
    filename="./logs/info.txt",
    filemode="w",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger().addHandler(logging.StreamHandler())

PROFILING_ENABLED = os.getenv("PROFILING_ENABLED", "false").strip().lower() in (
    "1",
    "true",
    "yes",
)


def get_tmdb_read_token(token: str | None = None) -> str:
    """
    Read The Movie Database API read access token from .env.
    """
    if token is not None:
        cleaned = token.strip()
        if cleaned:
            return cleaned
        raise RuntimeError("Empty explicit token passed.")
    cleaned = os.getenv("TMDB_API_READ_ACCESS_TOKEN", "").strip()
    if not cleaned:
        raise RuntimeError(
            "Missing TMDB_API_READ_ACCESS_TOKEN. Set it in .env or environment."
        )
    return cleaned


def get_max_pages(default: int = 50) -> int:
    """
    Read maximum pages constant from .env.
    Controlls how many results from each The Movie Database API
    call are processed.
    """
    raw = os.getenv("MAX_PAGES", "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 1 else default


def get_database_url() -> str:
    """
    Read Postgres Data Source Name from .env.
    """
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("Missing DATABASE_URL. Set it in .env or environment.")
    return dsn


def get_chroma_host_and_port() -> tuple[str, int]:
    """
    Read ChromaDB host name and port number from .env.
    """
    host = os.getenv("CHROMA_HOST", "localhost").strip()
    port = int(os.getenv("CHROMA_PORT", 8002))
    return (host, port)


def get_embed_model() -> str:
    return os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5").strip()
