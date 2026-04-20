from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from multimedia_bot.application.telegram_limits import (
    ensure_record_title_limit,
    ensure_telegram_caption_limit,
    ensure_telegram_message_text_limit,
)
from multimedia_bot.application.text import normalize_text
from multimedia_bot.domain.models import IngestionMetadata, MediaItem, MediaType, UploadedMedia
from multimedia_bot.domain.repositories import MediaRepository, Uploader


class IngestionService:
    def __init__(
        self,
        media_repository: MediaRepository,
        uploader: Uploader,
        media_root: Path,
    ) -> None:
        self._media_repository = media_repository
        self._uploader = uploader
        self._media_root = media_root.resolve()

    async def ingest(self, metadata: IngestionMetadata, *, existing_item_id: int | None = None) -> MediaItem:
        _validate_metadata_limits(metadata)
        relative_path: str | None = None
        file_id: str | None = None
        uploaded: UploadedMedia | None = None
        if metadata.media_type is not MediaType.TEXT:
            if not metadata.path:
                raise ValueError("Для медиафайла требуется путь к локальному файлу.")
            absolute_path = Path(metadata.path).resolve()
            relative_path = str(absolute_path.relative_to(self._media_root))
            upload_result = await self._uploader.upload_media(
                path=str(absolute_path),
                media_type=metadata.media_type,
                title=metadata.title,
                caption=metadata.caption,
                performer=metadata.performer,
                duration=metadata.duration,
            )
            if isinstance(upload_result, str):
                file_id = upload_result
            else:
                uploaded = upload_result
                file_id = upload_result.file_id
        item = MediaItem(
            id=existing_item_id or 0,
            media_type=metadata.media_type,
            title=metadata.title,
            storage_path=relative_path,
            description=metadata.description,
            caption=metadata.caption,
            content=metadata.content,
            search_text=build_search_text(
                title=metadata.title,
                description=metadata.description,
                content=metadata.content,
                tags=metadata.tags,
            ),
            telegram_file_id=file_id,
            mime_type=metadata.mime_type,
            performer=metadata.performer,
            duration=metadata.duration,
            width=metadata.width,
            height=metadata.height,
            tags=metadata.tags,
        )
        try:
            return await self._media_repository.upsert_media(item)
        except Exception:
            if uploaded is not None:
                with suppress(Exception):
                    await self._uploader.delete_uploaded_media(uploaded)
            raise


def build_search_text(*, title: str, description: str | None, content: str | None, tags: list[str]) -> str:
    parts = [title]
    if description:
        parts.append(description)
    if content:
        parts.append(content)
    parts.extend(tags)
    return normalize_text(" ".join(parts))


def _validate_metadata_limits(metadata: IngestionMetadata) -> None:
    ensure_record_title_limit(metadata.title)
    ensure_telegram_caption_limit(metadata.caption)
    if metadata.media_type is MediaType.TEXT:
        ensure_telegram_message_text_limit(metadata.content)
