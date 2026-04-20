from __future__ import annotations

from aiogram.types import (
    InlineQueryResultArticle,
    InlineQueryResultCachedAudio,
    InlineQueryResultCachedGif,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultCachedVoice,
    InputTextMessageContent,
)

from multimedia_bot.application.telegram_limits import TELEGRAM_CAPTION_LIMIT, TELEGRAM_MESSAGE_TEXT_LIMIT
from multimedia_bot.application.validation import is_valid_record_title
from multimedia_bot.domain.models import MediaItem, MediaType


def map_media_item_to_inline_result(item: MediaItem):
    if not is_valid_record_title(item.title):
        return None

    result_id = f"media:{item.id}"
    if item.media_type is MediaType.TEXT:
        if not item.content or len(item.content) > TELEGRAM_MESSAGE_TEXT_LIMIT:
            return None
        return InlineQueryResultArticle(
            id=result_id,
            title=item.title,
            description=item.description or item.content[:120],
            input_message_content=InputTextMessageContent(message_text=item.content),
        )

    if not item.telegram_file_id:
        return None
    if item.caption is not None and len(item.caption) > TELEGRAM_CAPTION_LIMIT:
        return None

    if item.media_type is MediaType.AUDIO:
        return InlineQueryResultCachedAudio(
            id=result_id,
            audio_file_id=item.telegram_file_id,
            caption=item.caption,
        )
    if item.media_type is MediaType.IMAGE:
        return InlineQueryResultCachedPhoto(
            id=result_id,
            photo_file_id=item.telegram_file_id,
            title=item.title,
            description=item.description,
            caption=item.caption,
        )
    if item.media_type is MediaType.VIDEO:
        return InlineQueryResultCachedVideo(
            id=result_id,
            video_file_id=item.telegram_file_id,
            title=item.title,
            description=item.description,
            caption=item.caption,
        )
    if item.media_type is MediaType.VOICE:
        return InlineQueryResultCachedVoice(
            id=result_id,
            voice_file_id=item.telegram_file_id,
            title=item.title,
            caption=item.caption,
        )
    if item.media_type is MediaType.GIF:
        return InlineQueryResultCachedGif(
            id=result_id,
            gif_file_id=item.telegram_file_id,
            title=item.title,
            caption=item.caption,
        )
    return None
