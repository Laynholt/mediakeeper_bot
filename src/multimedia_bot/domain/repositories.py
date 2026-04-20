from __future__ import annotations

from typing import Protocol

from multimedia_bot.domain.models import (
    AdminMediaDraft,
    MediaItem,
    MediaType,
    QueryCategory,
    UploadedMedia,
    UserMediaSubmission,
)


class MediaRepository(Protocol):
    async def upsert_media(self, item: MediaItem) -> MediaItem: ...

    async def search_media(
        self,
        *,
        normalized_query: str,
        category: QueryCategory,
        limit: int,
    ) -> list[MediaItem]: ...

    async def get_popular_media(self, *, limit: int) -> list[MediaItem]: ...

    async def get_media_by_id(self, media_id: int) -> MediaItem | None: ...

    async def get_media_by_title(self, title: str) -> MediaItem | None: ...

    async def list_media(self, *, limit: int, offset: int = 0, query: str | None = None) -> list[MediaItem]: ...

    async def count_media(self, *, query: str | None = None) -> int: ...

    async def get_all_media(self) -> list[MediaItem]: ...

    async def delete_media(self, media_id: int) -> MediaItem | None: ...

    async def increment_usage_count(self, media_id: int) -> None: ...


class AnalyticsRepository(Protocol):
    async def log_search(
        self,
        *,
        user_id: int,
        query_raw: str,
        query_type: str,
        result_count: int,
    ) -> None: ...

    async def log_chosen_result(
        self,
        *,
        user_id: int,
        result_id: str,
        query_raw: str,
    ) -> None: ...


class Uploader(Protocol):
    async def upload_media(
        self,
        *,
        path: str,
        media_type: MediaType,
        title: str,
        caption: str | None,
        performer: str | None,
        duration: int | None,
    ) -> UploadedMedia: ...

    async def delete_uploaded_media(self, uploaded: UploadedMedia) -> None: ...


class AdminDraftRepository(Protocol):
    async def create_or_replace_draft(
        self,
        *,
        admin_user_id: int,
        draft: AdminMediaDraft,
    ) -> AdminMediaDraft: ...

    async def get_draft_for_admin(self, admin_user_id: int) -> AdminMediaDraft | None: ...

    async def delete_draft_for_admin(self, admin_user_id: int) -> None: ...

    async def set_awaiting_alias_input(self, *, admin_user_id: int, value: bool) -> AdminMediaDraft | None: ...

    async def list_draft_paths(self) -> list[str]: ...


class UserSubmissionRepository(Protocol):
    async def create_submission(self, submission: UserMediaSubmission) -> UserMediaSubmission: ...

    async def update_submission(self, submission: UserMediaSubmission) -> UserMediaSubmission: ...

    async def delete_submission(self, submission_id: int) -> None: ...

    async def get_submission_by_id(self, submission_id: int) -> UserMediaSubmission | None: ...

    async def get_latest_actionable_for_user(self, user_id: int) -> UserMediaSubmission | None: ...

    async def get_latest_admin_edit_submission(self, admin_user_id: int) -> UserMediaSubmission | None: ...

    async def list_submission_paths(self) -> list[str]: ...
