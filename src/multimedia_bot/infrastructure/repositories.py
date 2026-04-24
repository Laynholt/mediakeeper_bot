from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC
import json

from sqlalchemy import case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from multimedia_bot.application.text import normalize_text
from multimedia_bot.application.validation import normalize_record_title
from multimedia_bot.domain.models import (
    AdminMediaDraft,
    MediaItem,
    MediaType,
    QueryCategory,
    SubmissionStatus,
    UserMediaSubmission,
)
from multimedia_bot.infrastructure.db import session_scope
from multimedia_bot.infrastructure.models import (
    AdminMediaDraftModel,
    ChosenResultLogModel,
    MediaItemModel,
    SearchLogModel,
    TagModel,
    UserMediaSubmissionModel,
)


class SqlAlchemyMediaRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_media(self, item: MediaItem) -> MediaItem:
        async with session_scope(self._session_factory) as session:
            existing = await self._find_existing(session=session, item=item)
            resolved_tags = await self._resolve_tags(session, item.tags)
            if existing is None:
                model = MediaItemModel(
                    type=item.media_type.value,
                    title=item.title,
                    tags=list(resolved_tags),
                )
                session.add(model)
            else:
                model = existing
                model.tags = list(resolved_tags)

            model.type = item.media_type.value
            model.title = item.title
            model.normalized_title = normalize_record_title(item.title)
            model.storage_path = item.storage_path
            model.description = item.description
            model.caption = item.caption
            model.content_text = item.content
            model.search_text = item.search_text
            model.telegram_file_id = item.telegram_file_id
            model.mime_type = item.mime_type
            model.performer = item.performer
            model.duration = item.duration
            model.width = item.width
            model.height = item.height
            model.is_active = item.is_active
            if existing is None:
                model.usage_count = item.usage_count

            try:
                await session.flush()
            except IntegrityError as error:
                if _is_duplicate_title_error(error):
                    raise ValueError(f"Алиас '{item.title}' уже существует. Выберите другой.") from error
                if _is_duplicate_media_identity_error(error):
                    raise ValueError("Файл или Telegram file_id уже привязан к другой записи каталога.") from error
                raise
            await session.refresh(model)
            return _to_domain(model)

    async def search_media(
        self,
        *,
        normalized_query: str,
        category: QueryCategory,
        limit: int,
        offset: int = 0,
    ) -> list[MediaItem]:
        async with session_scope(self._session_factory) as session:
            query = (
                select(MediaItemModel)
                .options(selectinload(MediaItemModel.tags))
                .distinct()
                .where(MediaItemModel.is_active.is_(True))
            )
            if category in {
                QueryCategory.AUDIO,
                QueryCategory.IMAGE,
                QueryCategory.VIDEO,
                QueryCategory.VOICE,
                QueryCategory.GIF,
                QueryCategory.TEXT,
            }:
                query = query.where(MediaItemModel.type == category.value)

            if normalized_query:
                pattern = _like_contains_pattern(normalized_query)
                query = query.outerjoin(MediaItemModel.tags).where(
                    or_(
                        func.lower(MediaItemModel.title) == normalized_query,
                        func.lower(MediaItemModel.title).like(pattern, escape="\\"),
                        func.lower(MediaItemModel.description).like(pattern, escape="\\"),
                        func.lower(MediaItemModel.content_text).like(pattern, escape="\\"),
                        func.lower(TagModel.slug).like(pattern, escape="\\"),
                        func.lower(MediaItemModel.search_text).like(pattern, escape="\\"),
                    )
                )
                exact_title = case(
                    (func.lower(MediaItemModel.title) == normalized_query, 1),
                    else_=0,
                )
                partial_title = case(
                    (func.lower(MediaItemModel.title).like(pattern, escape="\\"), 1),
                    else_=0,
                )
                tag_hit = case(
                    (func.lower(TagModel.slug).like(pattern, escape="\\"), 1),
                    else_=0,
                )
                description_hit = case(
                    (func.lower(MediaItemModel.description).like(pattern, escape="\\"), 1),
                    else_=0,
                )
                content_hit = case(
                    (func.lower(MediaItemModel.content_text).like(pattern, escape="\\"), 1),
                    else_=0,
                )
                query = query.order_by(
                    desc(exact_title),
                    desc(partial_title),
                    desc(tag_hit),
                    desc(description_hit),
                    desc(content_hit),
                    desc(MediaItemModel.usage_count),
                    desc(MediaItemModel.created_at),
                )
            else:
                query = query.order_by(desc(MediaItemModel.usage_count), desc(MediaItemModel.created_at))

            result = await session.execute(query.offset(offset).limit(limit))
            return [_to_domain(row) for row in result.scalars().unique().all()]

    async def get_popular_media(self, *, limit: int, offset: int = 0) -> list[MediaItem]:
        async with session_scope(self._session_factory) as session:
            result = await session.execute(
                select(MediaItemModel)
                .options(selectinload(MediaItemModel.tags))
                .where(MediaItemModel.is_active.is_(True))
                .order_by(desc(MediaItemModel.usage_count), desc(MediaItemModel.created_at))
                .offset(offset)
                .limit(limit)
            )
            return [_to_domain(row) for row in result.scalars().unique().all()]

    async def get_media_by_id(self, media_id: int) -> MediaItem | None:
        async with session_scope(self._session_factory) as session:
            result = await session.execute(
                select(MediaItemModel)
                .options(selectinload(MediaItemModel.tags))
                .where(MediaItemModel.id == media_id)
            )
            model = result.scalar_one_or_none()
            return _to_domain(model) if model is not None else None

    async def get_media_by_title(self, title: str) -> MediaItem | None:
        normalized_title = normalize_record_title(title)
        async with session_scope(self._session_factory) as session:
            result = await session.execute(
                select(MediaItemModel)
                .options(selectinload(MediaItemModel.tags))
                .where(
                    MediaItemModel.is_active.is_(True),
                    MediaItemModel.normalized_title == normalized_title,
                )
                .limit(1)
            )
            model = result.scalar_one_or_none()
            return _to_domain(model) if model is not None else None

    async def list_media(self, *, limit: int, offset: int = 0, query: str | None = None) -> list[MediaItem]:
        normalized_query = normalize_text(query or "")
        async with session_scope(self._session_factory) as session:
            statement = (
                select(MediaItemModel)
                .options(selectinload(MediaItemModel.tags))
                .where(MediaItemModel.is_active.is_(True))
            )
            if normalized_query:
                pattern = _like_contains_pattern(normalized_query)
                statement = (
                    statement.outerjoin(MediaItemModel.tags)
                    .where(
                        or_(
                            func.lower(MediaItemModel.title).like(pattern, escape="\\"),
                            func.lower(MediaItemModel.description).like(pattern, escape="\\"),
                            func.lower(MediaItemModel.content_text).like(pattern, escape="\\"),
                            func.lower(MediaItemModel.search_text).like(pattern, escape="\\"),
                            func.lower(TagModel.slug).like(pattern, escape="\\"),
                        )
                    )
                    .distinct()
                )
            statement = statement.order_by(desc(MediaItemModel.created_at)).offset(offset).limit(limit)
            result = await session.execute(statement)
            return [_to_domain(row) for row in result.scalars().unique().all()]

    async def count_media(self, *, query: str | None = None) -> int:
        normalized_query = normalize_text(query or "")
        async with session_scope(self._session_factory) as session:
            statement = select(func.count(func.distinct(MediaItemModel.id))).where(MediaItemModel.is_active.is_(True))
            if normalized_query:
                pattern = _like_contains_pattern(normalized_query)
                statement = (
                    statement.select_from(MediaItemModel)
                    .outerjoin(MediaItemModel.tags)
                    .where(
                        or_(
                            func.lower(MediaItemModel.title).like(pattern, escape="\\"),
                            func.lower(MediaItemModel.description).like(pattern, escape="\\"),
                            func.lower(MediaItemModel.content_text).like(pattern, escape="\\"),
                            func.lower(MediaItemModel.search_text).like(pattern, escape="\\"),
                            func.lower(TagModel.slug).like(pattern, escape="\\"),
                        )
                    )
                )
            result = await session.execute(statement)
            return int(result.scalar_one())

    async def get_all_media(self) -> list[MediaItem]:
        async with session_scope(self._session_factory) as session:
            result = await session.execute(
                select(MediaItemModel)
                .options(selectinload(MediaItemModel.tags))
                .where(MediaItemModel.is_active.is_(True))
                .order_by(MediaItemModel.id)
            )
            return [_to_domain(row) for row in result.scalars().unique().all()]

    async def delete_media(self, media_id: int) -> MediaItem | None:
        async with session_scope(self._session_factory) as session:
            result = await session.execute(
                select(MediaItemModel)
                .options(selectinload(MediaItemModel.tags))
                .where(MediaItemModel.id == media_id)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            item = _to_domain(model)
            await session.delete(model)
            return item

    async def increment_usage_count(self, media_id: int) -> None:
        async with session_scope(self._session_factory) as session:
            model = await session.get(MediaItemModel, media_id)
            if model is not None:
                model.usage_count += 1

    async def _find_existing(
        self,
        *,
        session: AsyncSession,
        item: MediaItem,
    ) -> MediaItemModel | None:
        if item.id:
            result = await session.execute(
                select(MediaItemModel)
                .options(selectinload(MediaItemModel.tags))
                .where(MediaItemModel.id == item.id)
            )
            model = result.scalar_one_or_none()
            if model is not None:
                await self._ensure_unique_media_identity(session=session, item=item, current_id=model.id)
                return model

        if item.telegram_file_id:
            result = await session.execute(
                select(MediaItemModel)
                .options(selectinload(MediaItemModel.tags))
                .where(MediaItemModel.telegram_file_id == item.telegram_file_id)
            )
            model = result.scalar_one_or_none()
            if model is not None:
                return model
        if item.storage_path:
            result = await session.execute(
                select(MediaItemModel)
                .options(selectinload(MediaItemModel.tags))
                .where(MediaItemModel.storage_path == item.storage_path)
            )
            model = result.scalar_one_or_none()
            if model is not None:
                return model

        return None

    async def _ensure_unique_media_identity(
        self,
        *,
        session: AsyncSession,
        item: MediaItem,
        current_id: int,
    ) -> None:
        if item.telegram_file_id:
            result = await session.execute(
                select(MediaItemModel.id).where(
                    MediaItemModel.telegram_file_id == item.telegram_file_id,
                    MediaItemModel.id != current_id,
                )
            )
            if result.scalar_one_or_none() is not None:
                raise ValueError("Telegram file_id уже привязан к другой записи каталога.")
        if item.storage_path:
            result = await session.execute(
                select(MediaItemModel.id).where(
                    MediaItemModel.storage_path == item.storage_path,
                    MediaItemModel.id != current_id,
                )
            )
            if result.scalar_one_or_none() is not None:
                raise ValueError("Файл уже привязан к другой записи каталога.")

    async def _resolve_tags(
        self,
        session: AsyncSession,
        tags: Iterable[str],
    ) -> list[TagModel]:
        resolved = []
        for tag in tags:
            slug = normalize_text(tag).replace(" ", "-")
            result = await session.execute(select(TagModel).where(TagModel.slug == slug))
            model = result.scalar_one_or_none()
            if model is None:
                model = TagModel(name=tag, slug=slug)
                session.add(model)
                await session.flush()
            resolved.append(model)
        return resolved


class SqlAlchemyAnalyticsRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def log_search(
        self,
        *,
        user_id: int,
        query_raw: str,
        query_type: str,
        result_count: int,
    ) -> None:
        async with session_scope(self._session_factory) as session:
            session.add(
                SearchLogModel(
                    user_id=user_id,
                    query_raw=query_raw,
                    query_type=query_type,
                    result_count=result_count,
                )
            )

    async def log_chosen_result(
        self,
        *,
        user_id: int,
        result_id: str,
        query_raw: str,
    ) -> None:
        async with session_scope(self._session_factory) as session:
            session.add(
                ChosenResultLogModel(
                    user_id=user_id,
                    result_id=result_id,
                    query_raw=query_raw,
                )
            )


class SqlAlchemyAdminDraftRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_or_replace_draft(
        self,
        *,
        admin_user_id: int,
        draft: AdminMediaDraft,
    ) -> AdminMediaDraft:
        async with session_scope(self._session_factory) as session:
            existing = await self._get_model(session, admin_user_id)
            if existing is None:
                model = AdminMediaDraftModel(admin_user_id=admin_user_id)
                session.add(model)
            else:
                model = existing

            model.media_type = draft.media_type.value
            model.storage_path = draft.path
            model.suggested_title = draft.suggested_title
            model.awaiting_alias_input = draft.awaiting_alias_input
            model.description = draft.description
            model.caption = draft.caption
            model.content_text = draft.content
            model.tags_json = json.dumps(draft.tags)
            model.performer = draft.performer
            model.duration = draft.duration
            model.width = draft.width
            model.height = draft.height
            model.mime_type = draft.mime_type

            await session.flush()
            await session.refresh(model)
            return _to_draft_domain(model)

    async def get_draft_for_admin(self, admin_user_id: int) -> AdminMediaDraft | None:
        async with session_scope(self._session_factory) as session:
            model = await self._get_model(session, admin_user_id)
            return _to_draft_domain(model) if model is not None else None

    async def delete_draft_for_admin(self, admin_user_id: int) -> None:
        async with session_scope(self._session_factory) as session:
            model = await self._get_model(session, admin_user_id)
            if model is not None:
                await session.delete(model)

    async def set_awaiting_alias_input(self, *, admin_user_id: int, value: bool) -> AdminMediaDraft | None:
        async with session_scope(self._session_factory) as session:
            model = await self._get_model(session, admin_user_id)
            if model is None:
                return None
            model.awaiting_alias_input = value
            await session.flush()
            await session.refresh(model)
            return _to_draft_domain(model)

    async def list_draft_paths(self) -> list[str]:
        async with session_scope(self._session_factory) as session:
            result = await session.execute(select(AdminMediaDraftModel.storage_path))
            return [row[0] for row in result.all() if row[0]]

    async def _get_model(
        self,
        session: AsyncSession,
        admin_user_id: int,
    ) -> AdminMediaDraftModel | None:
        result = await session.execute(
            select(AdminMediaDraftModel).where(AdminMediaDraftModel.admin_user_id == admin_user_id)
        )
        return result.scalar_one_or_none()


class SqlAlchemyUserSubmissionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_submission(self, submission: UserMediaSubmission) -> UserMediaSubmission:
        async with session_scope(self._session_factory) as session:
            model = UserMediaSubmissionModel()
            session.add(model)
            _copy_submission_fields(model, submission)
            await session.flush()
            await session.refresh(model)
            return _to_submission_domain(model)

    async def update_submission(self, submission: UserMediaSubmission) -> UserMediaSubmission:
        async with session_scope(self._session_factory) as session:
            model = await session.get(UserMediaSubmissionModel, submission.id)
            if model is None:
                raise LookupError(f"Submission {submission.id} not found")
            _copy_submission_fields(model, submission)
            await session.flush()
            await session.refresh(model)
            return _to_submission_domain(model)

    async def delete_submission(self, submission_id: int) -> None:
        async with session_scope(self._session_factory) as session:
            model = await session.get(UserMediaSubmissionModel, submission_id)
            if model is not None:
                await session.delete(model)

    async def get_submission_by_id(self, submission_id: int) -> UserMediaSubmission | None:
        async with session_scope(self._session_factory) as session:
            model = await session.get(UserMediaSubmissionModel, submission_id)
            return _to_submission_domain(model) if model is not None else None

    async def get_latest_actionable_for_user(self, user_id: int) -> UserMediaSubmission | None:
        async with session_scope(self._session_factory) as session:
            result = await session.execute(
                select(UserMediaSubmissionModel)
                .where(
                    UserMediaSubmissionModel.submitter_user_id == user_id,
                    UserMediaSubmissionModel.status.in_(
                        [
                            SubmissionStatus.AWAITING_USER_CHOICE.value,
                            SubmissionStatus.AWAITING_USER_TITLE.value,
                        ]
                    ),
                )
                .order_by(desc(UserMediaSubmissionModel.updated_at), desc(UserMediaSubmissionModel.id))
                .limit(1)
            )
            model = result.scalar_one_or_none()
            return _to_submission_domain(model) if model is not None else None

    async def get_latest_admin_edit_submission(self, admin_user_id: int) -> UserMediaSubmission | None:
        async with session_scope(self._session_factory) as session:
            result = await session.execute(
                select(UserMediaSubmissionModel)
                .where(
                    UserMediaSubmissionModel.editing_admin_user_id == admin_user_id,
                    UserMediaSubmissionModel.status == SubmissionStatus.AWAITING_ADMIN_TITLE.value,
                )
                .order_by(desc(UserMediaSubmissionModel.updated_at), desc(UserMediaSubmissionModel.id))
                .limit(1)
            )
            model = result.scalar_one_or_none()
            return _to_submission_domain(model) if model is not None else None

    async def list_submission_paths(self) -> list[str]:
        async with session_scope(self._session_factory) as session:
            result = await session.execute(select(UserMediaSubmissionModel.storage_path))
            return [row[0] for row in result.all() if row[0]]


def _to_domain(model: MediaItemModel) -> MediaItem:
    return MediaItem(
        id=model.id,
        media_type=MediaType(model.type),
        title=model.title,
        storage_path=model.storage_path,
        description=model.description,
        caption=model.caption,
        content=model.content_text,
        search_text=model.search_text,
        telegram_file_id=model.telegram_file_id,
        mime_type=model.mime_type,
        performer=model.performer,
        duration=model.duration,
        width=model.width,
        height=model.height,
        tags=[tag.name for tag in model.tags],
        is_active=model.is_active,
        usage_count=model.usage_count,
        created_at=model.created_at.replace(tzinfo=UTC) if model.created_at.tzinfo is None else model.created_at,
        updated_at=model.updated_at.replace(tzinfo=UTC) if model.updated_at.tzinfo is None else model.updated_at,
    )


def _is_duplicate_title_error(error: IntegrityError) -> bool:
    message = str(error.orig).lower()
    return "normalized_title" in message


def _is_duplicate_media_identity_error(error: IntegrityError) -> bool:
    message = str(error.orig).lower()
    return "storage_path" in message or "telegram_file_id" in message


def _like_contains_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _to_draft_domain(model: AdminMediaDraftModel) -> AdminMediaDraft:
    return AdminMediaDraft(
        id=model.id,
        admin_user_id=model.admin_user_id,
        media_type=MediaType(model.media_type),
        path=model.storage_path,
        suggested_title=model.suggested_title,
        awaiting_alias_input=model.awaiting_alias_input,
        description=model.description,
        caption=model.caption,
        content=model.content_text,
        tags=json.loads(model.tags_json),
        performer=model.performer,
        duration=model.duration,
        width=model.width,
        height=model.height,
        mime_type=model.mime_type,
        created_at=model.created_at.replace(tzinfo=UTC) if model.created_at.tzinfo is None else model.created_at,
    )


def _copy_submission_fields(model: UserMediaSubmissionModel, submission: UserMediaSubmission) -> None:
    model.submitter_user_id = submission.submitter_user_id
    model.media_type = submission.media_type.value
    model.storage_path = submission.path
    model.suggested_title = submission.suggested_title
    model.status = submission.status.value
    model.title = submission.title
    model.description = submission.description
    model.caption = submission.caption
    model.content_text = submission.content
    model.tags_json = json.dumps(submission.tags)
    model.performer = submission.performer
    model.duration = submission.duration
    model.width = submission.width
    model.height = submission.height
    model.mime_type = submission.mime_type
    model.review_chat_id = submission.review_chat_id
    model.review_message_id = submission.review_message_id
    model.editing_admin_user_id = submission.editing_admin_user_id


def _to_submission_domain(model: UserMediaSubmissionModel) -> UserMediaSubmission:
    return UserMediaSubmission(
        id=model.id,
        submitter_user_id=model.submitter_user_id,
        media_type=MediaType(model.media_type),
        path=model.storage_path,
        suggested_title=model.suggested_title,
        status=SubmissionStatus(model.status),
        title=model.title,
        description=model.description,
        caption=model.caption,
        content=model.content_text,
        tags=json.loads(model.tags_json),
        performer=model.performer,
        duration=model.duration,
        width=model.width,
        height=model.height,
        mime_type=model.mime_type,
        review_chat_id=model.review_chat_id,
        review_message_id=model.review_message_id,
        editing_admin_user_id=model.editing_admin_user_id,
        created_at=model.created_at.replace(tzinfo=UTC) if model.created_at.tzinfo is None else model.created_at,
        updated_at=model.updated_at.replace(tzinfo=UTC) if model.updated_at.tzinfo is None else model.updated_at,
    )
