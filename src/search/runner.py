import asyncio

from ..config import PROFILING_ENABLED


async def embed_reviews():
    pass


if __name__ == "__main__":
    if PROFILING_ENABLED:
        import pyinstrument

        with pyinstrument.profile():
            asyncio.run(embed_reviews())
    else:
        asyncio.run(embed_reviews())
