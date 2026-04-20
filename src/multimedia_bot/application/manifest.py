from __future__ import annotations

import json
from pathlib import Path

from multimedia_bot.domain.models import IngestionMetadata, MediaItem, MediaType
from multimedia_bot.infrastructure.file_metadata import infer_file_metadata


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_metadata_from_manifest_item(
    *,
    media_root: Path,
    manifest_parent: Path,
    raw_item: dict,
) -> IngestionMetadata:
    if not isinstance(raw_item, dict):
        raise ValueError("Каждый элемент манифеста должен быть объектом.")

    try:
        media_type = MediaType(raw_item["type"])
    except Exception as exc:
        raise ValueError(f"Некорректный тип медиа в элементе манифеста: {raw_item!r}") from exc

    resolved_path: Path | None = None
    inferred: dict[str, object | None] = {
        "title": None,
        "mime_type": None,
        "width": None,
        "height": None,
    }
    content = raw_item.get("content")
    if media_type is MediaType.TEXT:
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"Для текстового элемента манифеста требуется непустое поле content: {raw_item!r}")
        inferred["title"] = content.strip().splitlines()[0][:255]
    else:
        resolved_path = _resolve_manifest_path(
            media_root=media_root,
            manifest_parent=manifest_parent,
            raw_path=raw_item["path"],
        )
        if not resolved_path.exists():
            raise FileNotFoundError(f"Медиафайл не найден: {resolved_path}")
        inferred = infer_file_metadata(resolved_path)

    title = raw_item.get("title") or inferred["title"]
    tags = raw_item.get("tags") or []
    if not isinstance(tags, list):
        raise ValueError(f"Поле tags должно быть списком: {raw_item!r}")

    return IngestionMetadata(
        media_type=media_type,
        path=str(resolved_path.resolve()) if resolved_path is not None else None,
        title=title,
        description=raw_item.get("description"),
        caption=raw_item.get("caption"),
        content=content,
        tags=[str(tag) for tag in tags],
        performer=raw_item.get("performer"),
        duration=raw_item.get("duration"),
        width=raw_item.get("width") or inferred["width"],
        height=raw_item.get("height") or inferred["height"],
        mime_type=raw_item.get("mime_type") or inferred["mime_type"],
    )


def build_manifest_item_from_media(item: MediaItem, media_root: Path) -> dict:
    payload = {
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
    }
    if item.media_type is not MediaType.TEXT:
        absolute_path = _resolve_media_path(media_root, item.storage_path)
        try:
            payload["path"] = absolute_path.resolve().relative_to(media_root.resolve()).as_posix()
        except ValueError:
            payload["path"] = str(absolute_path)
    return payload


def _resolve_manifest_path(*, media_root: Path, manifest_parent: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    candidates = [manifest_parent / path, media_root / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _resolve_media_path(media_root: Path, storage_path: str | None) -> Path:
    if not storage_path:
        raise FileNotFoundError("У медиафайла нет связанного пути к локальному файлу.")
    path = Path(storage_path)
    return path if path.is_absolute() else (media_root / path)
