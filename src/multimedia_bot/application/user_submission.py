from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message, User

from multimedia_bot.application.file_storage import delete_local_file
from multimedia_bot.application.ingestion import IngestionService
from multimedia_bot.application.telegram_limits import trim_telegram_caption, trim_telegram_message_text
from multimedia_bot.application.telegram_media import build_media_file_name, extract_media_from_message
from multimedia_bot.application.validation import is_valid_record_title, sanitize_title
from multimedia_bot.domain.models import IngestionMetadata, MediaItem, MediaType, SubmissionStatus, UserMediaSubmission
from multimedia_bot.domain.repositories import MediaRepository, UserSubmissionRepository
from multimedia_bot.infrastructure.file_metadata import infer_file_metadata, parse_caption_metadata, parse_text_metadata


class UserSubmissionService:
    def __init__(
        self,
        *,
        bot: Bot,
        ingestion_service: IngestionService,
        submission_repository: UserSubmissionRepository,
        media_repository: MediaRepository,
        media_root: Path,
        admin_user_id: int | None,
    ) -> None:
        self._bot = bot
        self._ingestion_service = ingestion_service
        self._submission_repository = submission_repository
        self._media_repository = media_repository
        self._media_root = media_root
        self._admin_user_id = admin_user_id

    def review_enabled(self) -> bool:
        return self._admin_user_id is not None

    def is_admin(self, user_id: int) -> bool:
        return self._admin_user_id is not None and user_id == self._admin_user_id

    async def create_submission_from_message(self, message: Message) -> UserMediaSubmission:
        if self._admin_user_id is None:
            raise RuntimeError("ADMIN_USER_ID не настроен.")
        previous_submission = await self._submission_repository.get_latest_actionable_for_user(message.from_user.id)

        media_type, downloadable, original_name = extract_media_from_message(message)
        destination_dir = self._media_root / media_type.value
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_path = destination_dir / build_media_file_name(original_name)
        try:
            await self._bot.download(downloadable, destination=str(destination_path))

            caption_data = parse_caption_metadata(message.caption or "")
            inferred = infer_file_metadata(destination_path)
            submission = UserMediaSubmission(
                id=0,
                submitter_user_id=message.from_user.id,
                media_type=media_type,
                path=str(destination_path),
                suggested_title=caption_data["title"] or inferred["title"],
                status=SubmissionStatus.AWAITING_USER_CHOICE,
                description=caption_data["description"],
                caption=message.caption,
                content=None,
                tags=caption_data["tags"],
                performer=getattr(message.audio, "performer", None),
                duration=getattr(message.audio or message.video or message.voice or message.animation, "duration", None),
                width=inferred["width"],
                height=inferred["height"],
                mime_type=inferred["mime_type"],
            )
            saved_submission = await self._submission_repository.create_submission(submission)
        except Exception:
            delete_local_file(str(destination_path))
            raise
        if previous_submission is not None:
            await self._submission_repository.delete_submission(previous_submission.id)
            delete_local_file(previous_submission.path)
        return saved_submission

    async def create_text_submission(self, *, user_id: int, text: str) -> UserMediaSubmission:
        if self._admin_user_id is None:
            raise RuntimeError("ADMIN_USER_ID не настроен.")
        previous_submission = await self._submission_repository.get_latest_actionable_for_user(user_id)
        parsed = parse_text_metadata(text)
        content = parsed["content"] if isinstance(parsed["content"], str) else None
        if not content:
            raise ValueError("Текстовая заявка должна содержать хотя бы одну непустую строку без тегов.")
        submission = UserMediaSubmission(
            id=0,
            submitter_user_id=user_id,
            media_type=MediaType.TEXT,
            path=None,
            suggested_title=str(parsed["title"] or "text"),
            status=SubmissionStatus.AWAITING_USER_CHOICE,
            description=parsed["description"] if isinstance(parsed["description"], str) else None,
            content=content,
            tags=list(parsed["tags"]),
        )
        saved_submission = await self._submission_repository.create_submission(submission)
        if previous_submission is not None:
            await self._submission_repository.delete_submission(previous_submission.id)
            delete_local_file(previous_submission.path)
        return saved_submission

    async def get_submission_for_user(self, *, submission_id: int, user_id: int) -> UserMediaSubmission | None:
        submission = await self._submission_repository.get_submission_by_id(submission_id)
        if submission is None or submission.submitter_user_id != user_id:
            return None
        return submission

    async def get_latest_actionable_submission(self, user_id: int) -> UserMediaSubmission | None:
        return await self._submission_repository.get_latest_actionable_for_user(user_id)

    async def submit_with_suggested_title(
        self,
        *,
        submission_id: int,
        user_id: int,
        submitter: User,
        reply_markup: InlineKeyboardMarkup,
    ) -> UserMediaSubmission:
        submission = await self._require_user_submission(submission_id=submission_id, user_id=user_id)
        if not is_valid_record_title(submission.suggested_title):
            raise ValueError("Не удалось определить корректное предложенное название.")
        await self._ensure_alias_available(submission.suggested_title)
        submission.title = submission.suggested_title
        return await self._submit_for_review(submission=submission, submitter=submitter, reply_markup=reply_markup)

    async def request_user_title_input(self, *, submission_id: int, user_id: int) -> UserMediaSubmission:
        submission = await self._require_user_submission(submission_id=submission_id, user_id=user_id)
        submission.status = SubmissionStatus.AWAITING_USER_TITLE
        return await self._submission_repository.update_submission(submission)

    async def submit_with_custom_title(
        self,
        *,
        user_id: int,
        title: str,
        submitter: User,
        reply_markup: InlineKeyboardMarkup,
    ) -> UserMediaSubmission:
        submission = await self._submission_repository.get_latest_actionable_for_user(user_id)
        if submission is None or submission.status is not SubmissionStatus.AWAITING_USER_TITLE:
            raise LookupError("Нет заявки, ожидающей пользовательское название.")
        normalized_title = sanitize_title(title)
        if not is_valid_record_title(normalized_title):
            raise ValueError("Название должно содержать хотя бы один видимый символ: букву или цифру.")
        await self._ensure_alias_available(normalized_title)
        submission.title = normalized_title
        return await self._submit_for_review(submission=submission, submitter=submitter, reply_markup=reply_markup)

    async def cancel_submission(self, *, submission_id: int, user_id: int) -> UserMediaSubmission:
        submission = await self._require_user_submission(submission_id=submission_id, user_id=user_id)
        await self._submission_repository.delete_submission(submission.id)
        delete_local_file(submission.path)
        submission.status = SubmissionStatus.CANCELLED
        submission.editing_admin_user_id = None
        return submission

    async def start_admin_edit(self, *, submission_id: int, admin_user_id: int) -> UserMediaSubmission:
        self._ensure_admin(admin_user_id)
        submission = await self._require_submission(submission_id)
        if submission.status is not SubmissionStatus.PENDING_REVIEW:
            raise ValueError("Заявка сейчас не ожидает модерации.")
        submission.status = SubmissionStatus.AWAITING_ADMIN_TITLE
        submission.editing_admin_user_id = admin_user_id
        return await self._submission_repository.update_submission(submission)

    async def accept_submission(self, *, submission_id: int, admin_user_id: int) -> tuple[UserMediaSubmission, MediaItem]:
        self._ensure_admin(admin_user_id)
        submission = await self._require_submission(submission_id)
        if submission.status is not SubmissionStatus.PENDING_REVIEW:
            raise ValueError("Заявка сейчас не ожидает модерации.")
        title = submission.title or submission.suggested_title
        if not is_valid_record_title(title):
            raise ValueError("У заявки нет корректного названия для одобрения.")
        await self._ensure_alias_available(title)
        return await self._publish_submission(submission=submission, title=title)

    async def complete_admin_edit(
        self,
        *,
        admin_user_id: int,
        title: str,
    ) -> tuple[UserMediaSubmission, MediaItem]:
        self._ensure_admin(admin_user_id)
        submission = await self._submission_repository.get_latest_admin_edit_submission(admin_user_id)
        if submission is None:
            raise LookupError("Нет заявки, ожидающей вашего исправленного названия.")
        normalized_title = sanitize_title(title)
        if not is_valid_record_title(normalized_title):
            raise ValueError("Название должно содержать хотя бы один видимый символ: букву или цифру.")
        await self._ensure_alias_available(normalized_title)
        submission.title = normalized_title
        return await self._publish_submission(submission=submission, title=normalized_title)

    async def reject_submission(self, *, submission_id: int, admin_user_id: int) -> UserMediaSubmission:
        self._ensure_admin(admin_user_id)
        submission = await self._require_submission(submission_id)
        if submission.status not in {
            SubmissionStatus.PENDING_REVIEW,
            SubmissionStatus.AWAITING_ADMIN_TITLE,
        }:
            raise ValueError("Заявка сейчас не ожидает модерации.")
        await self._submission_repository.delete_submission(submission.id)
        delete_local_file(submission.path)
        submission.status = SubmissionStatus.REJECTED
        submission.editing_admin_user_id = None
        return submission

    async def clear_review_markup(self, submission: UserMediaSubmission) -> None:
        if submission.review_chat_id is None or submission.review_message_id is None:
            return
        await self._bot.edit_message_reply_markup(
            chat_id=submission.review_chat_id,
            message_id=submission.review_message_id,
            reply_markup=None,
        )

    async def notify_user_about_review(self, submission: UserMediaSubmission) -> None:
        await self._bot.send_message(
            chat_id=submission.submitter_user_id,
            text=(
                "Материал отправлен на модерацию.\n"
                f"Название: {submission.title or submission.suggested_title}\n"
                "Администратор проверит его и сообщит результат."
            ),
        )

    async def notify_user_about_rejection(self, submission: UserMediaSubmission) -> None:
        await self._bot.send_message(
            chat_id=submission.submitter_user_id,
            text=(
                "Материал отклонён администратором.\n"
                f"Название: {submission.title or submission.suggested_title}"
            ),
        )

    async def notify_user_about_acceptance(self, submission: UserMediaSubmission, item: MediaItem) -> None:
        await self._bot.send_message(
            chat_id=submission.submitter_user_id,
            text=(
                "Материал одобрен и добавлен в inline-каталог.\n"
                f"Алиас: {item.title}\n"
                "Теперь его можно отправлять через inline-режим."
            ),
        )

    async def _submit_for_review(
        self,
        *,
        submission: UserMediaSubmission,
        submitter: User,
        reply_markup: InlineKeyboardMarkup,
    ) -> UserMediaSubmission:
        if self._admin_user_id is None:
            raise RuntimeError("ADMIN_USER_ID не настроен.")

        review_message = await self._send_review_message(
            submission=submission,
            submitter=submitter,
            reply_markup=reply_markup,
        )
        submission.status = SubmissionStatus.PENDING_REVIEW
        submission.editing_admin_user_id = None
        submission.review_chat_id = review_message.chat.id
        submission.review_message_id = review_message.message_id
        try:
            return await self._submission_repository.update_submission(submission)
        except Exception:
            delete_message = getattr(self._bot, "delete_message", None)
            if callable(delete_message):
                try:
                    await delete_message(
                        chat_id=review_message.chat.id,
                        message_id=review_message.message_id,
                    )
                except Exception:
                    pass
            raise

    async def _publish_submission(
        self,
        *,
        submission: UserMediaSubmission,
        title: str,
    ) -> tuple[UserMediaSubmission, MediaItem]:
        item = await self._ingestion_service.ingest(
            IngestionMetadata(
                media_type=submission.media_type,
                path=submission.path,
                title=title,
                description=submission.description,
                caption=submission.caption,
                content=submission.content,
                tags=submission.tags,
                performer=submission.performer,
                duration=submission.duration,
                width=submission.width,
                height=submission.height,
                mime_type=submission.mime_type,
            )
        )
        submission.status = SubmissionStatus.ACCEPTED
        submission.title = title
        submission.editing_admin_user_id = None
        try:
            submission = await self._submission_repository.update_submission(submission)
        except Exception:
            with suppress(Exception):
                await self._media_repository.delete_media(item.id)
            raise
        return submission, item

    async def _ensure_alias_available(self, title: str) -> None:
        existing_item = await self._media_repository.get_media_by_title(title)
        if existing_item is not None:
            raise ValueError(f"Алиас '{title}' уже существует. Выберите другой.")

    async def _send_review_message(
        self,
        *,
        submission: UserMediaSubmission,
        submitter: User,
        reply_markup: InlineKeyboardMarkup,
    ) -> Message:
        caption = self._build_review_caption(submission=submission, submitter=submitter)
        if submission.media_type is MediaType.TEXT:
            text = caption
            if submission.content:
                text = f"{caption}\n\nТекст:\n{submission.content}"
            text = trim_telegram_message_text(text)
            return await self._bot.send_message(
                chat_id=self._admin_user_id,
                text=text,
                reply_markup=reply_markup,
            )

        caption = trim_telegram_caption(caption)
        media = FSInputFile(submission.path)
        if submission.media_type is MediaType.AUDIO:
            return await self._bot.send_audio(
                chat_id=self._admin_user_id,
                audio=media,
                caption=caption,
                title=submission.title or submission.suggested_title,
                performer=submission.performer,
                duration=submission.duration,
                reply_markup=reply_markup,
            )
        if submission.media_type is MediaType.IMAGE:
            return await self._bot.send_photo(
                chat_id=self._admin_user_id,
                photo=media,
                caption=caption,
                reply_markup=reply_markup,
            )
        if submission.media_type is MediaType.VOICE:
            return await self._bot.send_voice(
                chat_id=self._admin_user_id,
                voice=media,
                caption=caption,
                duration=submission.duration,
                reply_markup=reply_markup,
            )
        if submission.media_type is MediaType.GIF:
            return await self._bot.send_animation(
                chat_id=self._admin_user_id,
                animation=media,
                caption=caption,
                duration=submission.duration,
                reply_markup=reply_markup,
            )
        return await self._bot.send_video(
            chat_id=self._admin_user_id,
            video=media,
            caption=caption,
            width=submission.width,
            height=submission.height,
            duration=submission.duration,
            reply_markup=reply_markup,
        )

    def _build_review_caption(self, *, submission: UserMediaSubmission, submitter: User) -> str:
        parts = [
            f"Заявка #{submission.id}",
            f"От: {_format_user_label(submitter)}",
            f"Название: {submission.title or submission.suggested_title}",
            f"Тип: {submission.media_type.value}",
        ]
        if submission.description:
            parts.append(f"Описание: {submission.description}")
        if submission.tags:
            parts.append(f"Теги: {', '.join(submission.tags)}")
        return "\n".join(parts)

    async def _require_user_submission(self, *, submission_id: int, user_id: int) -> UserMediaSubmission:
        submission = await self.get_submission_for_user(submission_id=submission_id, user_id=user_id)
        if submission is None:
            raise LookupError("Заявка не найдена.")
        if submission.status not in {
            SubmissionStatus.AWAITING_USER_CHOICE,
            SubmissionStatus.AWAITING_USER_TITLE,
        }:
            raise ValueError("Заявку больше нельзя изменить.")
        return submission

    async def _require_submission(self, submission_id: int) -> UserMediaSubmission:
        submission = await self._submission_repository.get_submission_by_id(submission_id)
        if submission is None:
            raise LookupError("Заявка не найдена.")
        return submission

    def _ensure_admin(self, user_id: int) -> None:
        if not self.is_admin(user_id):
            raise PermissionError("Это действие доступно только администраторам.")

def _format_user_label(user: User) -> str:
    if user.username:
        return f"@{user.username} ({user.id})"
    return f"{user.full_name} ({user.id})"
