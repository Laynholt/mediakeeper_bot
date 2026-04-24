import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from multimedia_bot.application.admin_catalog import AdminCatalogService
from multimedia_bot.application.ingestion import IngestionService
from multimedia_bot.domain.models import IngestionMetadata, MediaType
from multimedia_bot.infrastructure.repositories import SqlAlchemyMediaRepository


class FakeBot:
    async def download(self, downloadable, destination: str) -> None:
        payload = getattr(downloadable, "payload", b"{}")
        Path(destination).write_bytes(payload)


class FakeUploader:
    def __init__(self) -> None:
        self.calls = 0

    async def upload_media(self, **_: object) -> str:
        self.calls += 1
        return f"telegram-file-{self.calls}"


async def test_admin_catalog_delete_and_duplicate_title_guard(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    first_path = media_root / "first.mp3"
    second_path = media_root / "second.mp3"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")

    media_repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = AdminCatalogService(
        bot=FakeBot(),
        media_repository=media_repository,
        ingestion_service=ingestion_service,
        media_root=media_root,
        admin_user_id=42,
    )

    first = await ingestion_service.ingest(IngestionMetadata(media_type=MediaType.AUDIO, path=str(first_path), title="one"))
    second = await ingestion_service.ingest(IngestionMetadata(media_type=MediaType.AUDIO, path=str(second_path), title="two"))

    try:
        await service.update_media_field(media_id=second.id, field="title", raw_value="one")
    except ValueError as error:
        assert "уже существует" in str(error)
    else:
        raise AssertionError("Expected duplicate alias rejection")

    deleted = await service.delete_media(first.id)
    assert deleted.title == "one"
    assert not first_path.exists()
    assert await media_repository.get_media_by_id(first.id) is None


async def test_admin_catalog_export_and_import_manifest(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    audio_path = media_root / "audio.mp3"
    audio_path.write_bytes(b"audio")

    media_repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = AdminCatalogService(
        bot=FakeBot(),
        media_repository=media_repository,
        ingestion_service=ingestion_service,
        media_root=media_root,
        admin_user_id=42,
    )

    await ingestion_service.ingest(
        IngestionMetadata(media_type=MediaType.AUDIO, path=str(audio_path), title="valid")
    )
    export_path, count = await service.export_manifest()
    assert count == 1
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported["items"][0]["title"] == "valid"
    assert exported["items"][0]["path"] == "audio.mp3"

    imported_media_root = tmp_path / "imported_media"
    imported_media_root.mkdir(parents=True)
    imported_file = imported_media_root / "copied.mp3"
    imported_file.write_bytes(b"copied")
    manifest_path = tmp_path / "import.json"
    manifest_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "path": str(imported_file),
                        "type": "audio",
                        "title": "imported",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    imported_count = await service.import_manifest(manifest_path, allow_external_paths=True)
    assert imported_count == 1
    imported_item = await media_repository.get_media_by_title("imported")
    assert imported_item is not None


async def test_admin_catalog_export_backup_includes_manifest_and_media_archive(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    audio_dir = media_root / "audio"
    audio_dir.mkdir()
    audio_path = audio_dir / "rain.mp3"
    audio_path.write_bytes(b"rain")

    media_repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = AdminCatalogService(
        bot=FakeBot(),
        media_repository=media_repository,
        ingestion_service=ingestion_service,
        media_root=media_root,
        admin_user_id=42,
    )

    await ingestion_service.ingest(
        IngestionMetadata(
            media_type=MediaType.AUDIO,
            path=str(audio_path),
            title="rain",
            tags=["weather"],
        )
    )

    package = await service.export_backup(max_archive_size_bytes=1024)

    manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
    assert package.item_count == 1
    assert package.skipped_files == []
    assert manifest["items"][0]["path"] == "audio/rain.mp3"
    assert len(package.archive_paths) == 1

    with ZipFile(package.archive_paths[0]) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "media/audio/rain.mp3" in names
        archive_manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert archive_manifest["items"][0]["path"] == "media/audio/rain.mp3"


async def test_admin_catalog_export_backup_splits_archives_by_size(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = AdminCatalogService(
        bot=FakeBot(),
        media_repository=media_repository,
        ingestion_service=ingestion_service,
        media_root=media_root,
        admin_user_id=42,
    )

    for title in ("first", "second"):
        path = media_root / f"{title}.mp3"
        path.write_bytes(b"x" * 10)
        await ingestion_service.ingest(
            IngestionMetadata(media_type=MediaType.AUDIO, path=str(path), title=title)
        )

    package = await service.export_backup(max_archive_size_bytes=15)

    assert package.item_count == 2
    assert len(package.archive_paths) == 2


async def test_admin_catalog_export_backup_skips_single_file_larger_than_archive_limit(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = AdminCatalogService(
        bot=FakeBot(),
        media_repository=media_repository,
        ingestion_service=ingestion_service,
        media_root=media_root,
        admin_user_id=42,
    )
    path = media_root / "large.mp3"
    path.write_bytes(b"x" * 20)
    await ingestion_service.ingest(
        IngestionMetadata(media_type=MediaType.AUDIO, path=str(path), title="large")
    )

    package = await service.export_backup(max_archive_size_bytes=10)

    assert package.item_count == 1
    assert package.archive_paths == []
    assert package.skipped_files == [path]


async def test_admin_catalog_import_backup_archive_restores_media(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    archive_path = tmp_path / "backup.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "items": [
                        {
                            "path": "media/audio/restored.mp3",
                            "type": "audio",
                            "title": "restored",
                            "tags": ["backup"],
                        }
                    ]
                }
            ),
        )
        archive.writestr("media/audio/restored.mp3", b"restored")

    media_repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = AdminCatalogService(
        bot=FakeBot(),
        media_repository=media_repository,
        ingestion_service=ingestion_service,
        media_root=media_root,
        admin_user_id=42,
    )

    imported = await service.import_backup_archive(archive_path)

    assert imported == 1
    restored = await media_repository.get_media_by_title("restored")
    assert restored is not None
    assert restored.tags == ["backup"]
    assert restored.storage_path is not None
    assert (media_root / restored.storage_path).exists()


async def test_admin_catalog_import_backup_archive_rejects_zip_path_traversal(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    archive_path = tmp_path / "malicious.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("../evil.txt", "evil")
        archive.writestr("manifest.json", json.dumps({"items": []}))

    media_repository = SqlAlchemyMediaRepository(session_factory)
    ingestion_service = IngestionService(media_repository, FakeUploader(), media_root)
    service = AdminCatalogService(
        bot=FakeBot(),
        media_repository=media_repository,
        ingestion_service=ingestion_service,
        media_root=media_root,
        admin_user_id=42,
    )

    try:
        await service.import_backup_archive(archive_path)
    except ValueError as error:
        assert "небезопасный путь" in str(error)
    else:
        raise AssertionError("Expected unsafe zip path rejection")

    assert not (tmp_path / "evil.txt").exists()


async def test_admin_catalog_pagination(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)

    media_repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = AdminCatalogService(
        bot=FakeBot(),
        media_repository=media_repository,
        ingestion_service=ingestion_service,
        media_root=media_root,
        admin_user_id=42,
    )

    for index in range(12):
        path = media_root / f"sample-{index}.mp3"
        path.write_bytes(f"sample-{index}".encode())
        await ingestion_service.ingest(
            IngestionMetadata(
                media_type=MediaType.AUDIO,
                path=str(path),
                title=f"item-{index}",
            )
        )

    first_page, total, page, total_pages = await service.list_media_page(query=None, page=0, page_size=5)
    second_page, _, second_page_index, _ = await service.list_media_page(query=None, page=1, page_size=5)
    last_page, _, clamped_page, _ = await service.list_media_page(query=None, page=99, page_size=5)

    assert total == 12
    assert total_pages == 3
    assert page == 0
    assert len(first_page) == 5
    assert second_page_index == 1
    assert len(second_page) == 5
    assert clamped_page == 2
    assert len(last_page) == 2


async def test_admin_catalog_replace_media_file(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    original_path = media_root / "old.mp3"
    original_path.write_bytes(b"old")

    media_repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = AdminCatalogService(
        bot=FakeBot(),
        media_repository=media_repository,
        ingestion_service=ingestion_service,
        media_root=media_root,
        admin_user_id=42,
    )

    item = await ingestion_service.ingest(
        IngestionMetadata(media_type=MediaType.AUDIO, path=str(original_path), title="stable-alias")
    )
    previous_storage_path = item.storage_path
    previous_file_id = item.telegram_file_id

    replacement_audio = SimpleNamespace(
        file_name="replacement.mp3",
        file_unique_id="replacement123",
        performer="Replacement",
        duration=7,
        payload=b"new-audio",
    )
    replacement_message = SimpleNamespace(
        audio=replacement_audio,
        photo=None,
        video=None,
        caption=None,
    )

    updated = await service.replace_media_file(media_id=item.id, message=replacement_message)

    assert updated.id == item.id
    assert updated.title == "stable-alias"
    assert updated.telegram_file_id != previous_file_id
    assert updated.storage_path != previous_storage_path
    assert updated.performer == "Replacement"
    assert updated.duration == 7
    assert not original_path.exists()
    assert (media_root / updated.storage_path).exists()


async def test_admin_catalog_repository_guard_rejects_duplicate_alias_case_insensitively(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    first_path = media_root / "first.mp3"
    second_path = media_root / "second.mp3"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")

    media_repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)

    await ingestion_service.ingest(
        IngestionMetadata(media_type=MediaType.AUDIO, path=str(first_path), title="Rain Loop")
    )

    try:
        await ingestion_service.ingest(
            IngestionMetadata(media_type=MediaType.AUDIO, path=str(second_path), title="  rain   loop  ")
        )
    except ValueError as error:
        assert "уже существует" in str(error)
    else:
        raise AssertionError("Expected duplicate alias rejection from repository constraint")


async def test_admin_catalog_exports_and_imports_text_items(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)

    media_repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = AdminCatalogService(
        bot=FakeBot(),
        media_repository=media_repository,
        ingestion_service=ingestion_service,
        media_root=media_root,
        admin_user_id=42,
    )

    await ingestion_service.ingest(
        IngestionMetadata(
            media_type=MediaType.TEXT,
            path=None,
            title="greeting",
            description="Короткий текст",
            content="Привет, мир!",
            tags=["hello"],
        )
    )

    export_path, count = await service.export_manifest()
    assert count == 1
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported["items"][0]["type"] == "text"
    assert exported["items"][0]["title"] == "greeting"
    assert exported["items"][0]["content"] == "Привет, мир!"
    assert "path" not in exported["items"][0]

    manifest_path = tmp_path / "text-import.json"
    manifest_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "type": "text",
                        "title": "farewell",
                        "description": "Фраза прощания",
                        "content": "Пока!",
                        "tags": ["bye"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    imported_count = await service.import_manifest(manifest_path)
    assert imported_count == 1
    imported_item = await media_repository.get_media_by_title("farewell")
    assert imported_item is not None
    assert imported_item.media_type is MediaType.TEXT
    assert imported_item.content == "Пока!"


async def test_admin_catalog_rejects_external_manifest_paths_by_default(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    import_dir = tmp_path / "imports"
    import_dir.mkdir()
    external_file = tmp_path / "external" / "external.mp3"
    external_file.parent.mkdir()
    external_file.write_bytes(b"external")

    media_repository = SqlAlchemyMediaRepository(session_factory)
    uploader = FakeUploader()
    ingestion_service = IngestionService(media_repository, uploader, media_root)
    service = AdminCatalogService(
        bot=FakeBot(),
        media_repository=media_repository,
        ingestion_service=ingestion_service,
        media_root=media_root,
        admin_user_id=42,
    )
    manifest_path = import_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "path": str(external_file),
                        "type": "audio",
                        "title": "external",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    try:
        await service.import_manifest(manifest_path)
    except ValueError as error:
        assert "вне каталога импорта" in str(error)
    else:
        raise AssertionError("Expected external path rejection")

    assert uploader.calls == 0
