from aiogram.types import (
    InlineQueryResultArticle,
    InlineQueryResultCachedAudio,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultCachedVoice,
)

from multimedia_bot.application.result_mapper import map_media_item_to_inline_result
from multimedia_bot.domain.models import MediaItem, MediaType


def test_map_audio_result() -> None:
    item = MediaItem(id=1, media_type=MediaType.AUDIO, title="Rain", telegram_file_id="audio-file")
    result = map_media_item_to_inline_result(item)
    assert isinstance(result, InlineQueryResultCachedAudio)


def test_map_image_result() -> None:
    item = MediaItem(id=2, media_type=MediaType.IMAGE, title="Cat", telegram_file_id="photo-file")
    result = map_media_item_to_inline_result(item)
    assert isinstance(result, InlineQueryResultCachedPhoto)


def test_map_video_result() -> None:
    item = MediaItem(id=3, media_type=MediaType.VIDEO, title="Intro", telegram_file_id="video-file")
    result = map_media_item_to_inline_result(item)
    assert isinstance(result, InlineQueryResultCachedVideo)


def test_map_voice_result() -> None:
    item = MediaItem(id=11, media_type=MediaType.VOICE, title="Quote", telegram_file_id="voice-file")
    result = map_media_item_to_inline_result(item)
    assert isinstance(result, InlineQueryResultCachedVoice)


def test_map_unicode_symbolic_title_result() -> None:
    item = MediaItem(id=6, media_type=MediaType.IMAGE, title="🔥 猫", telegram_file_id="photo-file")
    result = map_media_item_to_inline_result(item)
    assert isinstance(result, InlineQueryResultCachedPhoto)


def test_skip_missing_file_id() -> None:
    item = MediaItem(id=4, media_type=MediaType.IMAGE, title="Missing")
    assert map_media_item_to_inline_result(item) is None


def test_skip_invalid_title() -> None:
    item = MediaItem(id=5, media_type=MediaType.IMAGE, title="   ", telegram_file_id="photo-file")
    assert map_media_item_to_inline_result(item) is None


def test_skip_punctuation_only_title() -> None:
    item = MediaItem(id=7, media_type=MediaType.IMAGE, title="!!! ... ---", telegram_file_id="photo-file")
    assert map_media_item_to_inline_result(item) is None


def test_map_text_result() -> None:
    item = MediaItem(
        id=8,
        media_type=MediaType.TEXT,
        title="greeting",
        description="Приветствие",
        content="Привет, мир!",
    )
    result = map_media_item_to_inline_result(item)
    assert isinstance(result, InlineQueryResultArticle)
    assert result.input_message_content.message_text == "Привет, мир!"


def test_skip_oversized_text_result() -> None:
    item = MediaItem(
        id=9,
        media_type=MediaType.TEXT,
        title="too-long",
        content="x" * 4097,
    )
    assert map_media_item_to_inline_result(item) is None


def test_skip_oversized_caption_result() -> None:
    item = MediaItem(
        id=10,
        media_type=MediaType.IMAGE,
        title="Cat",
        telegram_file_id="photo-file",
        caption="x" * 1025,
    )
    assert map_media_item_to_inline_result(item) is None
