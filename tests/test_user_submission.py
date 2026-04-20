from pathlib import Path
from types import SimpleNamespace

from aiogram.types import InlineKeyboardMarkup

from multimedia_bot.application.ingestion import IngestionService
from multimedia_bot.application.user_submission import UserSubmissionService
from multimedia_bot.bot.keyboards import review_submission_keyboard
from multimedia_bot.domain.models import SubmissionStatus
from multimedia_bot.infrastructure.repositories import (
    SqlAlchemyMediaRepository,
    SqlAlchemyUserSubmissionRepository,
)


class FakeBot:
    def __init__(self, review_chat_id: int) -> None:
        self.review_chat_id = review_chat_id
        self.sent_media: list[tuple[str, int, str]] = []
        self.sent_messages: list[tuple[int, str]] = []
        self.edited_markups: list[tuple[int, int]] = []

    async def download(self, downloadable, destination: str) -> None:
        Path(destination).write_bytes(b"fake-media")

    async def send_audio(self, *, chat_id: int, audio, caption: str, **kwargs):
        self.sent_media.append(("audio", chat_id, caption))
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=501)

    async def send_photo(self, *, chat_id: int, photo, caption: str, **kwargs):
        self.sent_media.append(("photo", chat_id, caption))
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=502)

    async def send_video(self, *, chat_id: int, video, caption: str, **kwargs):
        self.sent_media.append(("video", chat_id, caption))
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=503)

    async def send_message(self, *, chat_id: int, text: str, **kwargs):
        self.sent_messages.append((chat_id, text))
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=601)

    async def edit_message_reply_markup(self, *, chat_id: int, message_id: int, reply_markup=None):
        self.edited_markups.append((chat_id, message_id))


class FailingReviewBot(FakeBot):
    async def send_audio(self, *, chat_id: int, audio, caption: str, **kwargs):
        raise RuntimeError("telegram unavailable")


class FakeUploader:
    def __init__(self) -> None:
        self.calls = 0

    async def upload_media(self, **_: object) -> str:
        self.calls += 1
        return f"telegram-file-{self.calls}"


class FailingSubmissionRepository(SqlAlchemyUserSubmissionRepository):
    async def create_submission(self, submission):
        raise RuntimeError("submission database unavailable")


def build_audio_message(*, user_id: int, username: str | None = None, caption: str = ""):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, username=username, full_name=f"user-{user_id}"),
        caption=caption,
        audio=SimpleNamespace(
            file_name="submission.mp3",
            performer="Tester",
            duration=7,
        ),
        photo=None,
        video=None,
    )


async def test_user_submission_can_be_reviewed_and_approved(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    submission_repository = SqlAlchemyUserSubmissionRepository(session_factory)
    uploader = FakeUploader()
    bot = FakeBot(review_chat_id=-100555)
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = UserSubmissionService(
        bot=bot,
        ingestion_service=ingestion_service,
        submission_repository=submission_repository,
        media_repository=media_repository,
        media_root=media_root,
        admin_user_id=42,
    )

    message = build_audio_message(user_id=1001, username="submitter", caption="Rain Loop\nSoft ambience\n#rain")
    submission = await service.create_submission_from_message(message)
    assert submission.status is SubmissionStatus.AWAITING_USER_CHOICE

    submission = await service.submit_with_suggested_title(
        submission_id=submission.id,
        user_id=1001,
        submitter=message.from_user,
        reply_markup=review_submission_keyboard(submission.id),
    )
    assert submission.status is SubmissionStatus.PENDING_REVIEW
    assert submission.review_chat_id == 42
    assert submission.review_message_id == 501
    assert bot.sent_media[0][0] == "audio"

    approved_submission, item = await service.accept_submission(
        submission_id=submission.id,
        admin_user_id=42,
    )
    assert approved_submission.status is SubmissionStatus.ACCEPTED
    assert item.title == "Rain Loop"
    assert uploader.calls == 1

    await service.clear_review_markup(approved_submission)
    await service.notify_user_about_acceptance(approved_submission, item)
    assert bot.edited_markups == [(42, 501)]
    assert bot.sent_messages[-1][0] == 1001


async def test_admin_can_edit_user_submission_title_before_approval(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    submission_repository = SqlAlchemyUserSubmissionRepository(session_factory)
    uploader = FakeUploader()
    bot = FakeBot(review_chat_id=-100777)
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = UserSubmissionService(
        bot=bot,
        ingestion_service=ingestion_service,
        submission_repository=submission_repository,
        media_repository=media_repository,
        media_root=media_root,
        admin_user_id=42,
    )

    message = build_audio_message(user_id=2002, caption="draft title")
    submission = await service.create_submission_from_message(message)
    submission = await service.request_user_title_input(submission_id=submission.id, user_id=2002)
    assert submission.status is SubmissionStatus.AWAITING_USER_TITLE

    submission = await service.submit_with_custom_title(
        user_id=2002,
        title="user title",
        submitter=message.from_user,
        reply_markup=review_submission_keyboard(submission.id),
    )
    assert submission.title == "user title"
    assert submission.status is SubmissionStatus.PENDING_REVIEW

    submission = await service.start_admin_edit(submission_id=submission.id, admin_user_id=42)
    assert submission.status is SubmissionStatus.AWAITING_ADMIN_TITLE

    approved_submission, item = await service.complete_admin_edit(
        admin_user_id=42,
        title="approved title",
    )
    assert approved_submission.status is SubmissionStatus.ACCEPTED
    assert approved_submission.title == "approved title"
    assert item.title == "approved title"
    assert uploader.calls == 1


async def test_user_cancel_and_reject_remove_orphan_files(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    submission_repository = SqlAlchemyUserSubmissionRepository(session_factory)
    uploader = FakeUploader()
    bot = FakeBot(review_chat_id=-100888)
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = UserSubmissionService(
        bot=bot,
        ingestion_service=ingestion_service,
        submission_repository=submission_repository,
        media_repository=media_repository,
        media_root=media_root,
        admin_user_id=42,
    )

    first_message = build_audio_message(user_id=3003, caption="temp one")
    first_submission = await service.create_submission_from_message(first_message)
    assert Path(first_submission.path).exists()
    cancelled = await service.cancel_submission(submission_id=first_submission.id, user_id=3003)
    assert cancelled.status is SubmissionStatus.CANCELLED
    assert not Path(first_submission.path).exists()
    assert await submission_repository.get_submission_by_id(first_submission.id) is None

    second_message = build_audio_message(user_id=3003, caption="temp two")
    second_submission = await service.create_submission_from_message(second_message)
    second_submission = await service.submit_with_suggested_title(
        submission_id=second_submission.id,
        user_id=3003,
        submitter=second_message.from_user,
        reply_markup=review_submission_keyboard(second_submission.id),
    )
    assert Path(second_submission.path).exists()
    rejected = await service.reject_submission(submission_id=second_submission.id, admin_user_id=42)
    assert rejected.status is SubmissionStatus.REJECTED
    assert not Path(second_submission.path).exists()
    assert await submission_repository.get_submission_by_id(second_submission.id) is None


async def test_duplicate_alias_is_rejected_for_user_submission(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    submission_repository = SqlAlchemyUserSubmissionRepository(session_factory)
    uploader = FakeUploader()
    bot = FakeBot(review_chat_id=-100999)
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = UserSubmissionService(
        bot=bot,
        ingestion_service=ingestion_service,
        submission_repository=submission_repository,
        media_repository=media_repository,
        media_root=media_root,
        admin_user_id=42,
    )

    original_message = build_audio_message(user_id=4004, caption="base title")
    original_submission = await service.create_submission_from_message(original_message)
    original_submission = await service.submit_with_suggested_title(
        submission_id=original_submission.id,
        user_id=4004,
        submitter=original_message.from_user,
        reply_markup=review_submission_keyboard(original_submission.id),
    )
    await service.accept_submission(submission_id=original_submission.id, admin_user_id=42)

    duplicate_message = build_audio_message(user_id=5005, caption="base title")
    duplicate_submission = await service.create_submission_from_message(duplicate_message)
    try:
        await service.submit_with_suggested_title(
            submission_id=duplicate_submission.id,
            user_id=5005,
            submitter=duplicate_message.from_user,
            reply_markup=review_submission_keyboard(duplicate_submission.id),
        )
    except ValueError as error:
        assert "уже существует" in str(error)
    else:
        raise AssertionError("Duplicate alias should be rejected")

    duplicate_submission = await service.request_user_title_input(
        submission_id=duplicate_submission.id,
        user_id=5005,
    )
    assert duplicate_submission.status is SubmissionStatus.AWAITING_USER_TITLE


async def test_failed_review_delivery_keeps_submission_actionable(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    submission_repository = SqlAlchemyUserSubmissionRepository(session_factory)
    uploader = FakeUploader()
    bot = FailingReviewBot(review_chat_id=-101000)
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = UserSubmissionService(
        bot=bot,
        ingestion_service=ingestion_service,
        submission_repository=submission_repository,
        media_repository=media_repository,
        media_root=media_root,
        admin_user_id=42,
    )

    message = build_audio_message(user_id=6006, caption="сбой модерации")
    submission = await service.create_submission_from_message(message)

    try:
        await service.submit_with_suggested_title(
            submission_id=submission.id,
            user_id=6006,
            submitter=message.from_user,
            reply_markup=review_submission_keyboard(submission.id),
        )
    except RuntimeError as error:
        assert "telegram unavailable" in str(error)
    else:
        raise AssertionError("Review delivery should fail in this test")

    actionable = await service.get_latest_actionable_submission(6006)
    assert actionable is not None
    assert actionable.id == submission.id
    assert actionable.status is SubmissionStatus.AWAITING_USER_CHOICE


async def test_text_submission_is_reviewed_in_admin_private_chat(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    submission_repository = SqlAlchemyUserSubmissionRepository(session_factory)
    uploader = FakeUploader()
    bot = FakeBot(review_chat_id=42)
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = UserSubmissionService(
        bot=bot,
        ingestion_service=ingestion_service,
        submission_repository=submission_repository,
        media_repository=media_repository,
        media_root=media_root,
        admin_user_id=42,
    )

    submission = await service.create_text_submission(
        user_id=7007,
        text="Приветствие\nДля inline-ответа\n#hello",
    )
    assert submission.media_type is not None
    assert submission.path is None

    submission = await service.submit_with_suggested_title(
        submission_id=submission.id,
        user_id=7007,
        submitter=SimpleNamespace(id=7007, username="tester", full_name="tester"),
        reply_markup=review_submission_keyboard(submission.id),
    )

    assert submission.status is SubmissionStatus.PENDING_REVIEW
    assert submission.review_chat_id == 42
    assert bot.sent_messages[0][0] == 42
    assert "Текст:" in bot.sent_messages[0][1]

    approved_submission, item = await service.accept_submission(
        submission_id=submission.id,
        admin_user_id=42,
    )
    assert approved_submission.status is SubmissionStatus.ACCEPTED
    assert item.content == "Приветствие\nДля inline-ответа"
    assert item.storage_path is None
    assert item.telegram_file_id is None
    assert uploader.calls == 0


async def test_user_media_download_is_removed_when_submission_save_fails(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    bot = FakeBot(review_chat_id=42)
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = UserSubmissionService(
        bot=bot,
        ingestion_service=ingestion_service,
        submission_repository=FailingSubmissionRepository(session_factory),
        media_repository=media_repository,
        media_root=media_root,
        admin_user_id=42,
    )

    try:
        await service.create_submission_from_message(
            build_audio_message(user_id=8008, caption="broken submission")
        )
    except RuntimeError as error:
        assert "submission database unavailable" in str(error)
    else:
        raise AssertionError("Expected submission save failure")

    assert list(media_root.rglob("*.mp3")) == []
