from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.types import Message

from multimedia_bot.application.file_storage import delete_local_file
from multimedia_bot.domain.models import AdminMediaDraft, IngestionMetadata, MediaItem, MediaType
from multimedia_bot.application.ingestion import IngestionService
from multimedia_bot.application.telegram_media import build_media_file_name, extract_media_from_message
from multimedia_bot.application.validation import is_valid_record_title, sanitize_title
from multimedia_bot.domain.repositories import AdminDraftRepository, MediaRepository
from multimedia_bot.infrastructure.file_metadata import infer_file_metadata, parse_caption_metadata, parse_text_metadata


class AdminIngestionService:
    def __init__(
        self,
        *,
        bot: Bot,
        ingestion_service: IngestionService,
        draft_repository: AdminDraftRepository,
        media_repository: MediaRepository,
        media_root: Path,
        admin_user_id: int | None,
    ) -> None:
        self._bot = bot
        self._ingestion_service = ingestion_service
        self._draft_repository = draft_repository
        self._media_repository = media_repository
        self._media_root = media_root
        self._admin_user_id = admin_user_id

    def is_admin(self, user_id: int) -> bool:
        return self._admin_user_id is not None and user_id == self._admin_user_id

    async def create_draft_from_message(self, message: Message) -> AdminMediaDraft:
        previous_draft = await self._draft_repository.get_draft_for_admin(message.from_user.id)
        media_type, downloadable, original_name = extract_media_from_message(message)
        destination_dir = self._media_root / media_type.value
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_path = destination_dir / build_media_file_name(original_name)
        try:
            await self._bot.download(downloadable, destination=str(destination_path))

            caption_data = parse_caption_metadata(message.caption or "")
            inferred = infer_file_metadata(destination_path)
            draft = AdminMediaDraft(
                id=0,
                admin_user_id=message.from_user.id,
                media_type=media_type,
                path=str(destination_path),
                suggested_title=caption_data["title"] or inferred["title"],
                description=caption_data["description"],
                caption=message.caption,
                tags=caption_data["tags"],
                performer=getattr(message.audio, "performer", None),
                duration=getattr(message.audio or message.video or message.voice or message.animation, "duration", None),
                width=inferred["width"],
                height=inferred["height"],
                mime_type=inferred["mime_type"],
            )
            saved_draft = await self._draft_repository.create_or_replace_draft(
                admin_user_id=message.from_user.id,
                draft=draft,
            )
        except Exception:
            delete_local_file(str(destination_path))
            raise
        if previous_draft is not None and previous_draft.path != saved_draft.path:
            delete_local_file(previous_draft.path)
        return saved_draft

    async def create_text_draft(self, *, admin_user_id: int, text: str) -> AdminMediaDraft:
        previous_draft = await self._draft_repository.get_draft_for_admin(admin_user_id)
        parsed = parse_text_metadata(text)
        content = parsed["content"] if isinstance(parsed["content"], str) else None
        if not content:
            raise ValueError("Текстовая запись должна содержать хотя бы одну непустую строку без тегов.")
        draft = AdminMediaDraft(
            id=0,
            admin_user_id=admin_user_id,
            media_type=MediaType.TEXT,
            path=None,
            suggested_title=str(parsed["title"] or "text"),
            description=parsed["description"] if isinstance(parsed["description"], str) else None,
            content=content,
            tags=list(parsed["tags"]),
        )
        saved_draft = await self._draft_repository.create_or_replace_draft(
            admin_user_id=admin_user_id,
            draft=draft,
        )
        if previous_draft is not None and previous_draft.path and previous_draft.path != saved_draft.path:
            delete_local_file(previous_draft.path)
        return saved_draft

    async def finalize_draft_with_alias(self, *, admin_user_id: int, alias: str) -> MediaItem:
        normalized_alias = sanitize_title(alias)
        if not is_valid_record_title(normalized_alias):
            raise ValueError("Алиас должен содержать хотя бы один видимый символ: букву или цифру.")
        existing_item = await self._media_repository.get_media_by_title(normalized_alias)
        if existing_item is not None:
            raise ValueError(f"Алиас '{normalized_alias}' уже существует. Выберите другой.")

        draft = await self._draft_repository.get_draft_for_admin(admin_user_id)
        if draft is None:
            raise LookupError("Для этого администратора нет активного черновика.")

        item = await self._ingestion_service.ingest(
            IngestionMetadata(
                media_type=draft.media_type,
                path=draft.path,
                title=normalized_alias,
                description=draft.description,
                caption=draft.caption,
                content=draft.content,
                tags=draft.tags,
                performer=draft.performer,
                duration=draft.duration,
                width=draft.width,
                height=draft.height,
                mime_type=draft.mime_type,
            )
        )
        await self._draft_repository.delete_draft_for_admin(admin_user_id)
        return item

    async def finalize_draft_with_suggested_title(self, *, admin_user_id: int) -> MediaItem:
        draft = await self._draft_repository.get_draft_for_admin(admin_user_id)
        if draft is None:
            raise LookupError("Для этого администратора нет активного черновика.")
        if not is_valid_record_title(draft.suggested_title):
            raise ValueError("Не удалось определить корректный предложенный алиас.")
        return await self.finalize_draft_with_alias(
            admin_user_id=admin_user_id,
            alias=draft.suggested_title,
        )

    async def get_pending_draft(self, admin_user_id: int) -> AdminMediaDraft | None:
        return await self._draft_repository.get_draft_for_admin(admin_user_id)

    async def request_alias_input(self, admin_user_id: int) -> AdminMediaDraft:
        draft = await self._draft_repository.set_awaiting_alias_input(
            admin_user_id=admin_user_id,
            value=True,
        )
        if draft is None:
            raise LookupError("Для этого администратора нет активного черновика.")
        return draft

    async def cancel_pending_draft(self, admin_user_id: int) -> bool:
        draft = await self._draft_repository.get_draft_for_admin(admin_user_id)
        if draft is None:
            return False
        await self._draft_repository.delete_draft_for_admin(admin_user_id)
        delete_local_file(draft.path)
        return True
