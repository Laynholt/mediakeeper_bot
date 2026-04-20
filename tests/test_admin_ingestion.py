from pathlib import Path
from types import SimpleNamespace

from multimedia_bot.application.admin_ingestion import AdminIngestionService
from multimedia_bot.application.ingestion import IngestionService
from multimedia_bot.domain.models import MediaType
from multimedia_bot.infrastructure.repositories import (
    SqlAlchemyAdminDraftRepository,
    SqlAlchemyMediaRepository,
)


class FakeUploadBot:
    async def download(self, downloadable, destination: str) -> None:
        Path(destination).write_bytes(b"fake-media")


class FakeUploader:
    def __init__(self) -> None:
        self.calls = 0

    async def upload_media(self, **_: object) -> str:
        self.calls += 1
        return f"telegram-file-{self.calls}"


class FailingDraftRepository(SqlAlchemyAdminDraftRepository):
    async def create_or_replace_draft(self, **_: object):
        raise RuntimeError("draft database unavailable")


async def test_admin_media_requires_alias_before_publication(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    draft_repository = SqlAlchemyAdminDraftRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    admin_service = AdminIngestionService(
        bot=FakeUploadBot(),
        ingestion_service=ingestion_service,
        draft_repository=draft_repository,
        media_repository=media_repository,
        media_root=media_root,
        admin_user_id=42,
    )

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        caption="Черновой заголовок\nОписание\n#дождь #Loop",
        audio=SimpleNamespace(
            file_name="draft.mp3",
            performer="Tester",
            duration=5,
        ),
        photo=None,
        video=None,
    )

    draft = await admin_service.create_draft_from_message(message)
    assert draft.media_type is MediaType.AUDIO
    assert draft.suggested_title == "Черновой заголовок"
    assert draft.tags == ["loop", "дождь"]
    assert uploader.calls == 0
    assert await media_repository.get_popular_media(limit=10) == []

    item = await admin_service.finalize_draft_with_alias(admin_user_id=42, alias="test-rain")
    assert item.title == "test-rain"
    assert item.tags == ["loop", "дождь"]
    assert uploader.calls == 1
    assert await admin_service.get_pending_draft(42) is None
    assert [saved.title for saved in await media_repository.get_popular_media(limit=10)] == ["test-rain"]


async def test_admin_cancel_removes_orphan_file_and_duplicate_alias_is_rejected(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    draft_repository = SqlAlchemyAdminDraftRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    admin_service = AdminIngestionService(
        bot=FakeUploadBot(),
        ingestion_service=ingestion_service,
        draft_repository=draft_repository,
        media_repository=media_repository,
        media_root=media_root,
        admin_user_id=42,
    )

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        caption="first alias",
        audio=SimpleNamespace(
            file_name="draft.mp3",
            performer="Tester",
            duration=5,
        ),
        photo=None,
        video=None,
    )

    published = await admin_service.create_draft_from_message(message)
    await admin_service.finalize_draft_with_alias(admin_user_id=42, alias="taken-alias")
    assert Path(published.path).exists()

    second_draft = await admin_service.create_draft_from_message(message)
    try:
        await admin_service.finalize_draft_with_alias(admin_user_id=42, alias="taken-alias")
    except ValueError as error:
        assert "уже существует" in str(error)
    else:
        raise AssertionError("Duplicate alias should be rejected")
    assert Path(second_draft.path).exists()

    cancelled = await admin_service.cancel_pending_draft(42)
    assert cancelled is True
    assert not Path(second_draft.path).exists()


async def test_admin_can_publish_text_draft(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    draft_repository = SqlAlchemyAdminDraftRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    admin_service = AdminIngestionService(
        bot=FakeUploadBot(),
        ingestion_service=ingestion_service,
        draft_repository=draft_repository,
        media_repository=media_repository,
        media_root=media_root,
        admin_user_id=42,
    )

    draft = await admin_service.create_text_draft(
        admin_user_id=42,
        text="Приветствие\nКороткая фраза\n#hello #welcome",
    )

    assert draft.media_type is MediaType.TEXT
    assert draft.content == "Приветствие\nКороткая фраза"
    assert draft.tags == ["hello", "welcome"]

    item = await admin_service.finalize_draft_with_alias(admin_user_id=42, alias="greeting")
    assert item.media_type is MediaType.TEXT
    assert item.title == "greeting"
    assert item.content == "Приветствие\nКороткая фраза"
    assert item.storage_path is None
    assert item.telegram_file_id is None
    assert uploader.calls == 0


async def test_admin_media_download_is_removed_when_draft_save_fails(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    admin_service = AdminIngestionService(
        bot=FakeUploadBot(),
        ingestion_service=ingestion_service,
        draft_repository=FailingDraftRepository(session_factory),
        media_repository=media_repository,
        media_root=media_root,
        admin_user_id=42,
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        caption="broken draft",
        audio=SimpleNamespace(file_name="draft.mp3", performer="Tester", duration=5),
        photo=None,
        video=None,
    )

    try:
        await admin_service.create_draft_from_message(message)
    except RuntimeError as error:
        assert "draft database unavailable" in str(error)
    else:
        raise AssertionError("Expected draft save failure")

    assert list(media_root.rglob("*.mp3")) == []
