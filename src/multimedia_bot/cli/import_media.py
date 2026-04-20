from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from aiogram import Bot

from multimedia_bot.application.ingestion import IngestionService
from multimedia_bot.application.manifest import build_metadata_from_manifest_item, load_manifest
from multimedia_bot.config import get_settings
from multimedia_bot.infrastructure.db import create_session_factory
from multimedia_bot.infrastructure.repositories import SqlAlchemyMediaRepository
from multimedia_bot.infrastructure.telegram_uploader import TelegramStorageUploader
from multimedia_bot.logging import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import media into the bot catalog")
    parser.add_argument("--manifest", required=True, help="Path to JSON manifest")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.media_root.mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(parents=True, exist_ok=True)

    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    items = manifest.get("items")
    if not isinstance(items, list):
        raise ValueError("Manifest must contain an 'items' list")

    session_factory = create_session_factory(settings.database_url)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    bot = Bot(token=settings.bot_token)
    try:
        uploader = TelegramStorageUploader(bot, settings.telegram_storage_chat_id)
        ingestion_service = IngestionService(media_repository, uploader, settings.media_root)

        for raw_item in items:
            metadata = build_metadata_from_manifest_item(
                media_root=settings.media_root,
                manifest_parent=manifest_path.parent,
                raw_item=raw_item,
            )
            await ingestion_service.ingest(metadata)
    finally:
        await bot.session.close()


def run() -> None:
    asyncio.run(main())

if __name__ == "__main__":
    run()
