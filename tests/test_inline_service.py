from multimedia_bot.application.ingestion import IngestionService
from multimedia_bot.application.inline_service import InlineQueryService
from multimedia_bot.application.search import SearchService
from multimedia_bot.domain.models import IngestionMetadata, MediaType
from multimedia_bot.infrastructure.repositories import SqlAlchemyAnalyticsRepository, SqlAlchemyMediaRepository


class FakeUploader:
    def __init__(self) -> None:
        self.calls = 0

    async def upload_media(self, **_: object) -> str:
        self.calls += 1
        return f"telegram-file-{self.calls}"


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


async def test_inline_query_uses_next_offset_for_additional_pages(session_factory, tmp_path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True)
    media_repository = SqlAlchemyMediaRepository(session_factory)
    analytics_repository = SqlAlchemyAnalyticsRepository(session_factory)
    ingestion_service = IngestionService(media_repository, FakeUploader(), media_root)

    for index in range(3):
        path = media_root / f"voice-{index}.ogg"
        path.write_bytes(b"voice")
        await ingestion_service.ingest(
            IngestionMetadata(
                media_type=MediaType.VOICE,
                path=str(path),
                title=f"voice-{index}",
            )
        )

    service = InlineQueryService(
        SearchService(media_repository, analytics_repository),
        search_limit=2,
    )

    first_page = await service.build_page(user_id=1, raw_query="voice")
    assert len(first_page.results) == 2
    assert first_page.next_offset == "2"

    second_page = await service.build_page(user_id=1, raw_query="voice", offset=first_page.next_offset)
    assert len(second_page.results) == 1
    assert second_page.next_offset == ""
