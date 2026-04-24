from __future__ import annotations

import asyncio
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

from multimedia_bot.application.admin_catalog import AdminCatalogService
from multimedia_bot.application.admin_ingestion import AdminIngestionService
from multimedia_bot.application.ingestion import IngestionService
from multimedia_bot.application.chosen_result import ChosenResultService
from multimedia_bot.application.inline_service import InlineQueryService
from multimedia_bot.application.orphan_cleanup import OrphanCleanupService
from multimedia_bot.application.search import SearchService
from multimedia_bot.application.user_submission import UserSubmissionService
from multimedia_bot.bot.dependencies import AppContainer
from multimedia_bot.bot.handlers import create_router
from multimedia_bot.config import get_settings, resolve_admin_user_id
from multimedia_bot.infrastructure.db import create_session_factory
from multimedia_bot.infrastructure.repositories import (
    SqlAlchemyAdminDraftRepository,
    SqlAlchemyAnalyticsRepository,
    SqlAlchemyMediaRepository,
    SqlAlchemyUserSubmissionRepository,
)
from multimedia_bot.infrastructure.telegram_uploader import TelegramStorageUploader
from multimedia_bot.logging import configure_logging


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    admin_user_id = resolve_admin_user_id(settings.admin_user_id, settings.admin_user_ids_raw)

    database_path = _ensure_database_parent(settings.database_url)
    if database_path is not None:
        database_path.parent.mkdir(parents=True, exist_ok=True)

    _apply_migrations(settings.database_url)

    session_factory = create_session_factory(settings.database_url)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    draft_repository = SqlAlchemyAdminDraftRepository(session_factory)
    submission_repository = SqlAlchemyUserSubmissionRepository(session_factory)
    analytics_repository = SqlAlchemyAnalyticsRepository(session_factory)
    search_service = SearchService(media_repository, analytics_repository)
    chosen_result_service = ChosenResultService(media_repository, analytics_repository)
    inline_query_service = InlineQueryService(search_service, search_limit=settings.search_limit)
    bot = Bot(token=settings.bot_token)
    try:
        await _configure_bot_commands(bot, admin_user_id)
        uploader = TelegramStorageUploader(bot, settings.telegram_storage_chat_id)
        ingestion_service = IngestionService(media_repository, uploader, settings.media_root)
        admin_ingestion_service = AdminIngestionService(
            bot=bot,
            ingestion_service=ingestion_service,
            draft_repository=draft_repository,
            media_repository=media_repository,
            media_root=settings.media_root,
            admin_user_id=admin_user_id,
        )
        admin_catalog_service = AdminCatalogService(
            bot=bot,
            media_repository=media_repository,
            ingestion_service=ingestion_service,
            media_root=settings.media_root,
            admin_user_id=admin_user_id,
            export_part_size_bytes=settings.export_part_size_mb * 1024 * 1024,
        )
        orphan_cleanup_service = OrphanCleanupService(
            media_repository=media_repository,
            draft_repository=draft_repository,
            submission_repository=submission_repository,
            media_root=settings.media_root,
            admin_user_id=admin_user_id,
        )
        user_submission_service = UserSubmissionService(
            bot=bot,
            ingestion_service=ingestion_service,
            submission_repository=submission_repository,
            media_repository=media_repository,
            media_root=settings.media_root,
            admin_user_id=admin_user_id,
        )
        container = AppContainer(
            inline_query_service=inline_query_service,
            chosen_result_service=chosen_result_service,
            admin_ingestion_service=admin_ingestion_service,
            admin_catalog_service=admin_catalog_service,
            orphan_cleanup_service=orphan_cleanup_service,
            user_submission_service=user_submission_service,
            inline_cache_time=settings.inline_cache_time,
        )

        dispatcher = Dispatcher()
        dispatcher.include_router(create_router(container))
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


def run() -> None:
    asyncio.run(main())


def _ensure_database_parent(database_url: str) -> Path | None:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return None
    return Path(database_url.removeprefix(prefix))


def _apply_migrations(database_url: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    config = Config(str(_project_root() / "alembic.ini"))
    command.upgrade(config, "head")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


async def _configure_bot_commands(bot: Bot, admin_user_id: int | None) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Показать справку и примеры"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )
    admin_commands = [
        BotCommand(command="start", description="Показать справку и примеры"),
        BotCommand(command="cancel", description="Отменить текущий черновик администратора"),
        BotCommand(command="admin_media", description="Открыть каталог медиа для админа"),
        BotCommand(command="admin_export", description="Экспортировать каталог и медиа"),
        BotCommand(command="admin_reimport", description="Переимпортировать текущий каталог"),
        BotCommand(command="admin_cleanup_orphans", description="Найти или удалить лишние файлы"),
    ]
    if admin_user_id is not None:
        await bot.set_my_commands(
            admin_commands,
            scope=BotCommandScopeChat(chat_id=admin_user_id),
        )
    await bot.set_my_short_description(
        "Inline-бот для аудио, изображений, видео и текстов."
    )
    await bot.set_my_description(
        "Отправляйте медиа и тексты в личный чат, публикуйте их в inline-каталоге и модерируйте пользовательские заявки."
    )
