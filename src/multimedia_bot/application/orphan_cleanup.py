from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from multimedia_bot.application.file_storage import delete_local_file
from multimedia_bot.domain.repositories import AdminDraftRepository, MediaRepository, UserSubmissionRepository


@dataclass(slots=True)
class OrphanScanResult:
    files: list[Path]

    @property
    def count(self) -> int:
        return len(self.files)


class OrphanCleanupService:
    def __init__(
        self,
        *,
        media_repository: MediaRepository,
        draft_repository: AdminDraftRepository,
        submission_repository: UserSubmissionRepository,
        media_root: Path,
        admin_user_id: int | None,
    ) -> None:
        self._media_repository = media_repository
        self._draft_repository = draft_repository
        self._submission_repository = submission_repository
        self._media_root = media_root
        self._admin_user_id = admin_user_id

    def is_admin(self, user_id: int) -> bool:
        return self._admin_user_id is not None and user_id == self._admin_user_id

    async def find_orphans(self) -> OrphanScanResult:
        referenced = await self._referenced_files()
        files = [
            path
            for path in sorted(self._media_root.rglob("*"))
            if path.is_file() and path.name != ".gitkeep" and path.resolve() not in referenced
        ]
        return OrphanScanResult(files=files)

    async def cleanup_orphans(self) -> OrphanScanResult:
        result = await self.find_orphans()
        for path in result.files:
            delete_local_file(str(path))
        return result

    async def _referenced_files(self) -> set[Path]:
        referenced: set[Path] = set()
        for item in await self._media_repository.get_all_media():
            if item.storage_path:
                referenced.add(self._resolve(item.storage_path))
        for path in await self._draft_repository.list_draft_paths():
            referenced.add(self._resolve(path))
        for path in await self._submission_repository.list_submission_paths():
            referenced.add(self._resolve(path))
        return referenced

    def _resolve(self, storage_path: str) -> Path:
        path = Path(storage_path)
        return path.resolve() if path.is_absolute() else (self._media_root / path).resolve()
