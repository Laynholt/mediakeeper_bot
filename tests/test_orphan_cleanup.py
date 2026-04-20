from pathlib import Path

from multimedia_bot.application.ingestion import IngestionService
from multimedia_bot.application.orphan_cleanup import OrphanCleanupService
from multimedia_bot.domain.models import IngestionMetadata, MediaType
from multimedia_bot.infrastructure.repositories import (
    SqlAlchemyAdminDraftRepository,
    SqlAlchemyMediaRepository,
    SqlAlchemyUserSubmissionRepository,
)


class FakeUploader:
    async def upload_media(self, **_: object) -> str:
        return "telegram-file"


async def test_orphan_cleanup_keeps_referenced_files_and_removes_orphans(session_factory, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    kept = media_root / "audio" / "kept.mp3"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(b"kept")
    orphan = media_root / "audio" / "orphan.mp3"
    orphan.write_bytes(b"orphan")
    gitkeep = media_root / "audio" / ".gitkeep"
    gitkeep.write_text("", encoding="utf-8")

    media_repository = SqlAlchemyMediaRepository(session_factory)
    draft_repository = SqlAlchemyAdminDraftRepository(session_factory)
    submission_repository = SqlAlchemyUserSubmissionRepository(session_factory)
    ingestion_service = IngestionService(media_repository, FakeUploader(), media_root)
    await ingestion_service.ingest(
        IngestionMetadata(
            media_type=MediaType.AUDIO,
            path=str(kept),
            title="kept",
        )
    )

    service = OrphanCleanupService(
        media_repository=media_repository,
        draft_repository=draft_repository,
        submission_repository=submission_repository,
        media_root=media_root,
        admin_user_id=42,
    )

    scan = await service.find_orphans()
    assert orphan in scan.files
    assert kept not in scan.files
    assert gitkeep not in scan.files

    cleanup = await service.cleanup_orphans()
    assert orphan in cleanup.files
    assert not orphan.exists()
    assert kept.exists()
    assert gitkeep.exists()
