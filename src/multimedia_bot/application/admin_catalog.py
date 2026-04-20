from __future__ import annotations

import json
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile
from typing import Literal
from uuid import uuid4

from aiogram import Bot
from aiogram.types import Audio, Message, PhotoSize, Video, Voice

from multimedia_bot.application.file_storage import delete_local_file
from multimedia_bot.application.ingestion import build_search_text, IngestionService
from multimedia_bot.application.manifest import build_manifest_item_from_media, build_metadata_from_manifest_item, load_manifest
from multimedia_bot.application.telegram_limits import (
    ensure_telegram_caption_limit,
    ensure_telegram_message_text_limit,
)
from multimedia_bot.application.validation import is_valid_record_title, sanitize_title
from multimedia_bot.domain.models import IngestionMetadata, MediaItem, MediaType
from multimedia_bot.domain.repositories import MediaRepository
from multimedia_bot.infrastructure.file_metadata import infer_file_metadata


EditableField = Literal["title", "description", "caption", "content", "tags"]


class AdminCatalogService:
    def __init__(
        self,
        *,
        bot: Bot,
        media_repository: MediaRepository,
        ingestion_service: IngestionService,
        media_root: Path,
        admin_user_id: int | None,
    ) -> None:
        self._bot = bot
        self._media_repository = media_repository
        self._ingestion_service = ingestion_service
        self._media_root = media_root.resolve()
        self._admin_user_id = admin_user_id

    def is_admin(self, user_id: int) -> bool:
        return self._admin_user_id is not None and user_id == self._admin_user_id

    async def list_media_page(
        self,
        *,
        query: str | None,
        page: int,
        page_size: int = 6,
    ) -> tuple[list[MediaItem], int, int, int]:
        total = await self._media_repository.count_media(query=query)
        total_pages = max(1, (total + page_size - 1) // page_size)
        normalized_page = min(max(page, 0), total_pages - 1)
        items = await self._media_repository.list_media(
            limit=page_size,
            offset=normalized_page * page_size,
            query=query,
        )
        return items, total, normalized_page, total_pages

    async def get_media(self, media_id: int) -> MediaItem | None:
        return await self._media_repository.get_media_by_id(media_id)

    async def delete_media(self, media_id: int) -> MediaItem:
        item = await self._media_repository.delete_media(media_id)
        if item is None:
            raise LookupError("Медиафайл не найден.")
        if item.storage_path:
            delete_local_file(self._resolve_local_path(item).as_posix())
        return item

    async def update_media_field(self, *, media_id: int, field: EditableField, raw_value: str) -> MediaItem:
        item = await self._media_repository.get_media_by_id(media_id)
        if item is None:
            raise LookupError("Медиафайл не найден.")

        if field == "title":
            title = sanitize_title(raw_value)
            if not is_valid_record_title(title):
                raise ValueError("Алиас должен содержать хотя бы один видимый символ.")
            existing = await self._media_repository.get_media_by_title(title)
            if existing is not None and existing.id != item.id:
                raise ValueError(f"Алиас '{title}' уже существует. Выберите другой.")
            item.title = title
        elif field == "description":
            item.description = sanitize_optional_text(raw_value)
        elif field == "caption":
            item.caption = sanitize_optional_text(raw_value)
            ensure_telegram_caption_limit(item.caption)
        elif field == "content":
            item.content = sanitize_optional_text(raw_value)
            ensure_telegram_message_text_limit(item.content)
        elif field == "tags":
            item.tags = parse_tags(raw_value)
        else:
            raise ValueError(f"Неподдерживаемое поле: {field}")

        item.search_text = build_search_text(
            title=item.title,
            description=item.description,
            content=item.content,
            tags=item.tags,
        )
        return await self._media_repository.upsert_media(item)

    async def replace_media_file(self, *, media_id: int, message: Message) -> MediaItem:
        item = await self._media_repository.get_media_by_id(media_id)
        if item is None:
            raise LookupError("Медиафайл не найден.")
        if item.media_type is MediaType.TEXT:
            raise ValueError("Для текстовой записи замена файла недоступна.")

        media_type, downloadable, original_name = self._extract_media(message)
        if media_type is not item.media_type:
            raise ValueError(
                f"Ожидался файл типа {item.media_type.value}, получен {media_type.value}."
            )

        destination_dir = self._media_root / media_type.value
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_path = destination_dir / _build_import_file_name(original_name)
        await self._bot.download(downloadable, destination=str(destination_path))

        inferred = infer_file_metadata(destination_path)
        previous_path = self._resolve_local_path(item)
        try:
            updated = await self._ingestion_service.ingest(
                build_metadata_from_manifest_item(
                    media_root=self._media_root,
                    manifest_parent=self._media_root,
                    raw_item={
                        "path": str(destination_path),
                        "type": item.media_type.value,
                        "title": item.title,
                        "description": item.description,
                        "caption": item.caption,
                        "tags": item.tags,
                        "performer": getattr(message.audio, "performer", None) or item.performer,
                        "duration": getattr(message.audio or message.video or message.voice, "duration", None) or item.duration,
                        "width": inferred["width"],
                        "height": inferred["height"],
                        "mime_type": inferred["mime_type"],
                    },
                ),
                existing_item_id=item.id,
            )
        except Exception:
            delete_local_file(str(destination_path))
            raise

        if previous_path != destination_path:
            delete_local_file(str(previous_path))
        return updated

    async def export_manifest(self) -> tuple[Path, int]:
        items = await self._media_repository.get_all_media()
        export_items = []
        for item in items:
            if item.media_type is not MediaType.TEXT:
                try:
                    absolute_path = self._resolve_local_path(item)
                except FileNotFoundError:
                    continue
                if not absolute_path.exists():
                    continue
            export_items.append(build_manifest_item_from_media(item, self._media_root))

        payload = {"items": export_items}
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".json") as temporary_file:
            json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
            path = Path(temporary_file.name)
        return path, len(export_items)

    async def import_manifest(self, manifest_path: Path, *, allow_external_paths: bool = False) -> int:
        manifest = load_manifest(manifest_path)
        items = manifest.get("items")
        if not isinstance(items, list):
            raise ValueError("Манифест должен содержать список 'items'.")

        imported = 0
        for raw_item in items:
            copied_path: Path | None = None
            metadata = build_metadata_from_manifest_item(
                media_root=self._media_root,
                manifest_parent=manifest_path.parent,
                raw_item=raw_item,
            )
            self._ensure_import_path_allowed(
                metadata=metadata,
                manifest_parent=manifest_path.parent,
                allow_external_paths=allow_external_paths,
            )
            original_path = metadata.path
            try:
                metadata = self._ensure_media_root_file(metadata)
                if metadata.path and metadata.path != original_path:
                    copied_path = Path(metadata.path)
                if not is_valid_record_title(metadata.title):
                    continue
                existing = await self._media_repository.get_media_by_title(metadata.title)
                if existing is not None:
                    if metadata.media_type is MediaType.TEXT:
                        raise ValueError(f"Алиас '{metadata.title}' уже существует в этом боте.")
                    if existing.storage_path != self._relative_storage_path(metadata.path):
                        raise ValueError(f"Алиас '{metadata.title}' уже существует в этом боте.")
                await self._ingestion_service.ingest(metadata)
                imported += 1
                copied_path = None
            finally:
                if copied_path is not None:
                    delete_local_file(str(copied_path))
        return imported

    async def reimport_current_catalog(self) -> int:
        items = await self._media_repository.get_all_media()
        imported = 0
        for item in items:
            if item.media_type is MediaType.TEXT:
                if not is_valid_record_title(item.title):
                    continue
            else:
                absolute_path = self._resolve_local_path(item)
                if not absolute_path.exists() or not is_valid_record_title(item.title):
                    continue
            await self._ingestion_service.ingest(
                build_metadata_from_media(item=item, media_root=self._media_root)
            )
            imported += 1
        return imported

    async def download_document(self, *, file_id: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        await self._bot.download(file_id, destination=str(destination))
        return destination

    def format_media_card(self, item: MediaItem) -> str:
        tags = ", ".join(item.tags) if item.tags else "нет"
        return (
            f"#{item.id} {item.media_type.value}\n"
            f"Алиас: {item.title}\n"
            f"Описание: {item.description or '-'}\n"
            f"Подпись: {item.caption or '-'}\n"
            f"Текст: {item.content or '-'}\n"
            f"Теги: {tags}"
        )

    def format_media_page(
        self,
        *,
        items: list[MediaItem],
        query: str | None,
        page: int,
        total: int,
        total_pages: int,
    ) -> str:
        header = f"Каталог медиа, страница {page + 1}/{total_pages}\nВсего элементов: {total}"
        if query:
            header += f"\nФильтр: {query}"
        if not items:
            return f"{header}\n\nНичего не найдено."

        lines = [header, "", "Выберите медиафайл:"]
        lines.extend(
            f"{item.id}. {item.title} [{item.media_type.value}]"
            for item in items
        )
        return "\n".join(lines)

    def _resolve_local_path(self, item: MediaItem) -> Path:
        if not item.storage_path:
            raise FileNotFoundError("Медиафайл не привязан к локальному файлу.")
        path = Path(item.storage_path)
        return path if path.is_absolute() else (self._media_root / path)

    def _relative_storage_path(self, path: str) -> str:
        absolute_path = Path(path).resolve()
        return str(absolute_path.relative_to(self._media_root.resolve()))

    def _ensure_media_root_file(self, metadata: IngestionMetadata) -> IngestionMetadata:
        if metadata.media_type is MediaType.TEXT:
            return metadata
        absolute_path = Path(metadata.path).resolve()
        media_root = self._media_root.resolve()
        try:
            absolute_path.relative_to(media_root)
            return metadata
        except ValueError:
            destination_dir = media_root / metadata.media_type.value
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination_path = destination_dir / _build_import_file_name(absolute_path.name)
            shutil.copy2(absolute_path, destination_path)
            metadata.path = str(destination_path)
            return metadata

    def _ensure_import_path_allowed(
        self,
        *,
        metadata: IngestionMetadata,
        manifest_parent: Path,
        allow_external_paths: bool,
    ) -> None:
        if allow_external_paths or metadata.media_type is MediaType.TEXT or metadata.path is None:
            return
        absolute_path = Path(metadata.path).resolve()
        allowed_roots = (self._media_root.resolve(), manifest_parent.resolve())
        if any(_is_relative_to(absolute_path, root) for root in allowed_roots):
            return
        raise ValueError("Манифест содержит путь к файлу вне каталога импорта или MEDIA_ROOT.")

    def _extract_media(self, message: Message) -> tuple[MediaType, Audio | Video | Voice | PhotoSize, str]:
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
        raise ValueError("Неподдерживаемый тип медиа-сообщения.")


def build_metadata_from_media(*, item: MediaItem, media_root: Path) -> IngestionMetadata:
    absolute_path = (
        Path(item.storage_path)
        if item.storage_path and Path(item.storage_path).is_absolute()
        else (media_root / (item.storage_path or ""))
    )
    return build_metadata_from_manifest_item(
        media_root=media_root,
        manifest_parent=media_root,
        raw_item={
            "type": item.media_type.value,
            "title": item.title,
            "description": item.description,
            "caption": item.caption,
            "content": item.content,
            "tags": item.tags,
            "performer": item.performer,
            "duration": item.duration,
            "width": item.width,
            "height": item.height,
            "mime_type": item.mime_type,
            **({"path": str(absolute_path)} if item.media_type is not MediaType.TEXT else {}),
        },
    )


def parse_tags(raw_value: str) -> list[str]:
    normalized = sanitize_title(raw_value)
    if not normalized:
        return []
    parts = [part.strip().lstrip("#") for part in normalized.split(",")]
    return sorted({part for part in parts if part})


def sanitize_optional_text(raw_value: str) -> str | None:
    sanitized = sanitize_title(raw_value)
    return sanitized or None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _build_import_file_name(original_name: str) -> str:
    path = Path(original_name)
    extension = path.suffix or ".bin"
    stem = path.stem or "media"
    safe_stem = "".join(character for character in stem if character.isalnum() or character in {"-", "_"}).strip("_-")
    safe_stem = safe_stem or "media"
    return f"{safe_stem}-{uuid4().hex[:8]}{extension.lower()}"
