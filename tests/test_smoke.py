from config import hello


def test_hello() -> None:
    assert hello("movies") == "Hello, movies!"
