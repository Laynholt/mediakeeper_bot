from __future__ import annotations

from aiogram import Bot
from aiogram.types import FSInputFile

from multimedia_bot.domain.models import MediaType, UploadedMedia


class TelegramStorageUploader:
    def __init__(self, bot: Bot, storage_chat_id: int) -> None:
        self._bot = bot
        self._storage_chat_id = storage_chat_id

    async def upload_media(
        self,
        *,
        path: str,
        media_type: MediaType,
        title: str,
        caption: str | None,
        performer: str | None,
        duration: int | None,
    ) -> UploadedMedia:
        input_file = FSInputFile(path)
        if media_type is MediaType.AUDIO:
            message = await self._bot.send_audio(
                chat_id=self._storage_chat_id,
                audio=input_file,
                title=title,
                caption=caption,
                performer=performer,
                duration=duration,
            )
            if message.audio is None:
                raise RuntimeError("Telegram не вернул метаданные аудио.")
            return _uploaded(message.audio.file_id, message)

        if media_type is MediaType.IMAGE:
            message = await self._bot.send_photo(
                chat_id=self._storage_chat_id,
                photo=input_file,
                caption=caption,
            )
            if not message.photo:
                raise RuntimeError("Telegram не вернул метаданные изображения.")
            return _uploaded(message.photo[-1].file_id, message)

        if media_type is MediaType.VIDEO:
            message = await self._bot.send_video(
                chat_id=self._storage_chat_id,
                video=input_file,
                caption=caption,
                duration=duration,
            )
            if message.video is None:
                raise RuntimeError("Telegram не вернул метаданные видео.")
            return _uploaded(message.video.file_id, message)

        raise ValueError(f"Неподдерживаемый тип медиа: {media_type}")

    async def delete_uploaded_media(self, uploaded: UploadedMedia) -> None:
        if uploaded.chat_id is None or uploaded.message_id is None:
            return
        await self._bot.delete_message(
            chat_id=uploaded.chat_id,
            message_id=uploaded.message_id,
        )


def _uploaded(file_id: str, message) -> UploadedMedia:
    return UploadedMedia(
        file_id=file_id,
        chat_id=message.chat.id,
        message_id=message.message_id,
    )
