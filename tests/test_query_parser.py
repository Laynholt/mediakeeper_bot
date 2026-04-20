from multimedia_bot.application.query_parser import parse_inline_query
from multimedia_bot.domain.models import QueryCategory


def test_parse_empty_query() -> None:
    parsed = parse_inline_query("")
    assert parsed.category is QueryCategory.NONE
    assert parsed.search_text == ""


def test_parse_audio_query() -> None:
    parsed = parse_inline_query("audio lo-fi")
    assert parsed.category is QueryCategory.AUDIO
    assert parsed.search_text == "lo-fi"


def test_parse_image_query() -> None:
    parsed = parse_inline_query("image cat meme")
    assert parsed.category is QueryCategory.IMAGE
    assert parsed.search_text == "cat meme"


def test_parse_video_query() -> None:
    parsed = parse_inline_query("video funny intro")
    assert parsed.category is QueryCategory.VIDEO
    assert parsed.search_text == "funny intro"


def test_parse_text_query() -> None:
    parsed = parse_inline_query("text greeting")
    assert parsed.category is QueryCategory.TEXT
    assert parsed.search_text == "greeting"


def test_parse_free_text_query() -> None:
    parsed = parse_inline_query("rain ambience")
    assert parsed.category is QueryCategory.ALL
    assert parsed.search_text == "rain ambience"
