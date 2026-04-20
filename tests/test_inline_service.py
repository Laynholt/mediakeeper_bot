from multimedia_bot.application.ingestion import IngestionService
from multimedia_bot.application.inline_service import InlineQueryService
from multimedia_bot.application.search import SearchService
from multimedia_bot.domain.models import IngestionMetadata, MediaType
from multimedia_bot.infrastructure.repositories import SqlAlchemyAnalyticsRepository, SqlAlchemyMediaRepository


class FakeUploader:
    async def upload_media(self, **_: object) -> str:
        return "telegram-file"


async def test_empty_inline_query_returns_only_real_media(session_factory, tmp_path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    image_path = media_root / "image.png"
    image_path.write_bytes(b"image")

    media_repository = SqlAlchemyMediaRepository(session_factory)
    analytics_repository = SqlAlchemyAnalyticsRepository(session_factory)
    ingestion_service = IngestionService(media_repository, FakeUploader(), media_root)
    await ingestion_service.ingest(
        IngestionMetadata(
            media_type=MediaType.IMAGE,
            path=str(image_path),
            title="valid image",
        )
    )

    service = InlineQueryService(
        SearchService(media_repository, analytics_repository),
        search_limit=20,
    )
    results = await service.build_results(user_id=1, raw_query="")

    assert len(results) == 1
    assert results[0].id == "media:1"
