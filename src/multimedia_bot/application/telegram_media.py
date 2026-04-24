from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from aiogram.types import Animation, Audio, Message, PhotoSize, Video, Voice

from multimedia_bot.domain.models import MediaType


TelegramDownloadable = Animation | Audio | Video | Voice | PhotoSize


def extract_media_from_message(message: Message) -> tuple[MediaType, TelegramDownloadable, str]:
    if message.audio:
        file_name = message.audio.file_name or f"{message.audio.file_unique_id}.bin"
        return MediaType.AUDIO, message.audio, file_name
    if message.photo:
        file_name = f"{message.photo[-1].file_unique_id}.jpg"
        return MediaType.IMAGE, message.photo[-1], file_name
    if message.video:
        file_name = message.video.file_name or f"{message.video.file_unique_id}.mp4"
        return MediaType.VIDEO, message.video, file_name
    if message.voice:
        file_name = f"{message.voice.file_unique_id}.ogg"
        return MediaType.VOICE, message.voice, file_name
    if message.animation:
        file_name = message.animation.file_name or f"{message.animation.file_unique_id}.gif"
        return MediaType.GIF, message.animation, file_name
    raise ValueError("Неподдерживаемый тип медиа-сообщения.")


def build_media_file_name(original_name: str) -> str:
    path = Path(original_name.replace("\\", "/"))
    extension = path.suffix or ".bin"
    stem = path.stem or "media"
    safe_stem = "".join(character for character in stem if character.isalnum() or character in {"-", "_"}).strip("_-")
    safe_stem = safe_stem or "media"
    return f"{safe_stem}-{uuid4().hex[:8]}{extension.lower()}"
