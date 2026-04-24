from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile
from tempfile import TemporaryDirectory
from typing import Literal
from zipfile import ZIP_STORED, ZipFile

from aiogram import Bot
from aiogram.types import Message

from multimedia_bot.application.file_storage import delete_local_file
from multimedia_bot.application.ingestion import build_search_text, IngestionService
from multimedia_bot.application.manifest import build_manifest_item_from_media, build_metadata_from_manifest_item, load_manifest
from multimedia_bot.application.telegram_limits import (
    ensure_telegram_caption_limit,
    ensure_telegram_message_text_limit,
)
from multimedia_bot.application.telegram_media import build_media_file_name, extract_media_from_message
from multimedia_bot.application.validation import is_valid_record_title, sanitize_title
from multimedia_bot.domain.models import IngestionMetadata, MediaItem, MediaType
from multimedia_bot.domain.repositories import MediaRepository
from multimedia_bot.infrastructure.file_metadata import infer_file_metadata


EditableField = Literal["title", "description", "caption", "content", "tags"]
DEFAULT_EXPORT_ARCHIVE_SIZE_BYTES = 1900 * 1024 * 1024


@dataclass(slots=True)
class BackupArchiveEntry:
    manifest_item: dict
    source_path: Path
    archive_path: str
    size: int


@dataclass(slots=True)
class CatalogBackupPackage:
    manifest_path: Path
    archive_paths: list[Path]
    item_count: int
    skipped_files: list[Path]


class AdminCatalogService:
    def __init__(
        self,
        *,
        bot: Bot,
        media_repository: MediaRepository,
        ingestion_service: IngestionService,
        media_root: Path,
        admin_user_id: int | None,
        export_part_size_bytes: int = DEFAULT_EXPORT_ARCHIVE_SIZE_BYTES,
    ) -> None:
        self._bot = bot
        self._media_repository = media_repository
        self._ingestion_service = ingestion_service
        self._media_root = media_root.resolve()
        self._admin_user_id = admin_user_id
        self._export_part_size_bytes = export_part_size_bytes

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

        media_type, downloadable, original_name = extract_media_from_message(message)
        if media_type is not item.media_type:
            raise ValueError(
                f"Ожидался файл типа {item.media_type.value}, получен {media_type.value}."
            )

        destination_dir = self._media_root / media_type.value
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_path = destination_dir / build_media_file_name(original_name)
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
                        "duration": getattr(message.audio or message.video or message.voice or message.animation, "duration", None) or item.duration,
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

    async def export_backup(self, *, max_archive_size_bytes: int | None = None) -> CatalogBackupPackage:
        archive_size_limit = max_archive_size_bytes or self._export_part_size_bytes
        if archive_size_limit <= 0:
            raise ValueError("Лимит размера архива должен быть больше нуля.")

        items = await self._media_repository.get_all_media()
        manifest_items: list[dict] = []
        archive_text_items: list[dict] = []
        archive_entries: list[BackupArchiveEntry] = []
        skipped_files: list[Path] = []

        for item in items:
            if item.media_type is MediaType.TEXT:
                manifest_item = build_manifest_item_from_media(item, self._media_root)
                manifest_items.append(manifest_item)
                archive_text_items.append(dict(manifest_item))
                continue

            try:
                absolute_path = self._resolve_local_path(item)
            except FileNotFoundError:
                continue
            if not absolute_path.exists():
                continue

            manifest_item = build_manifest_item_from_media(item, self._media_root)
            manifest_items.append(manifest_item)
            file_size = absolute_path.stat().st_size
            if file_size > archive_size_limit:
                skipped_files.append(absolute_path)
                continue

            archive_item = dict(manifest_item)
            archive_path = _archive_media_path(manifest_item["path"])
            archive_item["path"] = archive_path
            archive_entries.append(
                BackupArchiveEntry(
                    manifest_item=archive_item,
                    source_path=absolute_path,
                    archive_path=archive_path,
                    size=file_size,
                )
            )

        manifest_path = _write_json_temp({"items": manifest_items}, suffix=".json")
        archive_groups = _split_archive_entries(archive_entries, max_size_bytes=archive_size_limit)
        if not archive_groups and archive_text_items:
            archive_groups = [[]]

        archive_paths = [
            _write_backup_archive(
                part_index=index,
                entries=group,
                text_items=archive_text_items if index == 1 else [],
            )
            for index, group in enumerate(archive_groups, start=1)
        ]
        return CatalogBackupPackage(
            manifest_path=manifest_path,
            archive_paths=archive_paths,
            item_count=len(manifest_items),
            skipped_files=skipped_files,
        )

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

    async def import_backup_archive(self, archive_path: Path) -> int:
        with TemporaryDirectory() as temporary_directory:
            extract_root = Path(temporary_directory)
            _safe_extract_zip(archive_path=archive_path, destination=extract_root)
            manifest_path = extract_root / "manifest.json"
            if not manifest_path.exists():
                raise ValueError("ZIP-архив должен содержать manifest.json в корне.")
            return await self.import_manifest(manifest_path)

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
            destination_path = destination_dir / build_media_file_name(absolute_path.name)
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


def _archive_media_path(manifest_path: str) -> str:
    normalized = manifest_path.replace("\\", "/").lstrip("/")
    return f"media/{normalized}"


def _split_archive_entries(
    entries: list[BackupArchiveEntry],
    *,
    max_size_bytes: int,
) -> list[list[BackupArchiveEntry]]:
    groups: list[list[BackupArchiveEntry]] = []
    current_group: list[BackupArchiveEntry] = []
    current_size = 0
    for entry in entries:
        if current_group and current_size + entry.size > max_size_bytes:
            groups.append(current_group)
            current_group = []
            current_size = 0
        current_group.append(entry)
        current_size += entry.size
    if current_group:
        groups.append(current_group)
    return groups


def _write_json_temp(payload: dict, *, suffix: str) -> Path:
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=suffix) as temporary_file:
        json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
        return Path(temporary_file.name)


def _write_backup_archive(
    *,
    part_index: int,
    entries: list[BackupArchiveEntry],
    text_items: list[dict],
) -> Path:
    path = _empty_temp_path(suffix=f"-part-{part_index:03}.zip")
    manifest_items = [*text_items, *(entry.manifest_item for entry in entries)]
    with ZipFile(path, "w", compression=ZIP_STORED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"items": manifest_items}, ensure_ascii=False, indent=2),
        )
        for entry in entries:
            archive.write(entry.source_path, arcname=entry.archive_path)
    return path


def _empty_temp_path(*, suffix: str) -> Path:
    with NamedTemporaryFile(delete=False, suffix=suffix) as temporary_file:
        return Path(temporary_file.name)


def _safe_extract_zip(*, archive_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    with ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target_path = (destination / member.filename).resolve()
            if not _is_relative_to(target_path, destination):
                raise ValueError(f"ZIP-архив содержит небезопасный путь: {member.filename}")

        for member in archive.infolist():
            target_path = (destination / member.filename).resolve()
            if member.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target_path.open("wb") as target:
                shutil.copyfileobj(source, target)
