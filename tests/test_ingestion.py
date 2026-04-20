from pathlib import Path

from multimedia_bot.application.ingestion import IngestionService
from multimedia_bot.domain.models import IngestionMetadata, MediaType, UploadedMedia
from multimedia_bot.infrastructure.repositories import SqlAlchemyMediaRepository


class FakeUploader:
    def __init__(self) -> None:
        self.calls = 0

    async def upload_media(self, **_: object) -> str:
        self.calls += 1
        return f"file-{self.calls}"


class DeletableUploader:
    def __init__(self) -> None:
        self.deleted: list[UploadedMedia] = []

    async def upload_media(self, **_: object) -> UploadedMedia:
        return UploadedMedia(file_id="telegram-file", chat_id=-1001, message_id=77)

    async def delete_uploaded_media(self, uploaded: UploadedMedia) -> None:
        self.deleted.append(uploaded)


class FailingMediaRepository:
    async def upsert_media(self, item) -> None:
        raise RuntimeError("database unavailable")


async def test_ingestion_upserts_duplicate_storage_path(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    audio_dir = media_root / "audio"
    audio_dir.mkdir(parents=True)
    file_path = audio_dir / "rain.mp3"
    file_path.write_bytes(b"fake-audio")

    repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    service = IngestionService(repository, uploader, media_root)

    first = await service.ingest(
        IngestionMetadata(
            media_type=MediaType.AUDIO,
            path=str(file_path),
            title="Rain One",
            tags=["rain"],
        )
    )
    second = await service.ingest(
        IngestionMetadata(
            media_type=MediaType.AUDIO,
            path=str(file_path),
            title="Rain Two",
            tags=["rain", "loop"],
        )
    )

    assert first.id == second.id
    assert second.title == "Rain Two"
    assert uploader.calls == 2


async def test_text_ingestion_does_not_upload_file(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)

    repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    service = IngestionService(repository, uploader, media_root)

    item = await service.ingest(
        IngestionMetadata(
            media_type=MediaType.TEXT,
            path=None,
            title="greeting",
            description="Короткий текст",
            content="Привет!",
            tags=["hello"],
        )
    )

    assert item.media_type is MediaType.TEXT
    assert item.storage_path is None
    assert item.telegram_file_id is None
    assert item.content == "Привет!"
    assert uploader.calls == 0


async def test_ingestion_deletes_uploaded_storage_message_when_database_write_fails(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    audio_dir = media_root / "audio"
    audio_dir.mkdir(parents=True)
    file_path = audio_dir / "rain.mp3"
    file_path.write_bytes(b"fake-audio")

    uploader = DeletableUploader()
    service = IngestionService(FailingMediaRepository(), uploader, media_root)

    try:
        await service.ingest(
            IngestionMetadata(
                media_type=MediaType.AUDIO,
                path=str(file_path),
                title="Rain",
            )
        )
    except RuntimeError as error:
        assert "database unavailable" in str(error)
    else:
        raise AssertionError("Expected database write failure")

    assert uploader.deleted == [UploadedMedia(file_id="telegram-file", chat_id=-1001, message_id=77)]


async def test_ingestion_rejects_oversized_caption_before_upload(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    audio_dir = media_root / "audio"
    audio_dir.mkdir(parents=True)
    file_path = audio_dir / "rain.mp3"
    file_path.write_bytes(b"fake-audio")

    repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    service = IngestionService(repository, uploader, media_root)

    try:
        await service.ingest(
            IngestionMetadata(
                media_type=MediaType.AUDIO,
                path=str(file_path),
                title="Rain",
                caption="x" * 1025,
            )
        )
    except ValueError as error:
        assert "лимите 1024" in str(error)
    else:
        raise AssertionError("Expected caption limit validation")

    assert uploader.calls == 0
