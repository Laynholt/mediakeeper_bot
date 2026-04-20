from multimedia_bot.application.chosen_result import ChosenResultService
from multimedia_bot.application.search import SearchService
from multimedia_bot.domain.models import MediaItem, MediaType, QueryCategory, SearchRequest
from multimedia_bot.infrastructure.repositories import (
    SqlAlchemyAnalyticsRepository,
    SqlAlchemyMediaRepository,
)


async def test_repository_upsert_and_tag_linking(session_factory) -> None:
    repository = SqlAlchemyMediaRepository(session_factory)
    item = MediaItem(
        id=0,
        media_type=MediaType.AUDIO,
        title="Rain Ambience",
        storage_path="audio/rain.mp3",
        search_text="rain ambience sleep",
        telegram_file_id="audio1",
        tags=["rain", "sleep"],
    )

    saved = await repository.upsert_media(item)
    assert saved.id > 0
    assert set(saved.tags) == {"rain", "sleep"}


async def test_search_ranking_and_category_filter(session_factory) -> None:
    media_repository = SqlAlchemyMediaRepository(session_factory)
    analytics_repository = SqlAlchemyAnalyticsRepository(session_factory)
    service = SearchService(media_repository, analytics_repository)

    await media_repository.upsert_media(
        MediaItem(
            id=0,
            media_type=MediaType.AUDIO,
            title="Rain",
            storage_path="audio/rain.mp3",
            search_text="rain storm ambience",
            telegram_file_id="audio-rain",
            tags=["storm"],
        )
    )
    await media_repository.upsert_media(
        MediaItem(
            id=0,
            media_type=MediaType.IMAGE,
            title="Storm Poster",
            storage_path="image/storm.jpg",
            search_text="poster rain storm",
            telegram_file_id="photo-storm",
            tags=["rain"],
        )
    )
    await media_repository.upsert_media(
        MediaItem(
            id=0,
            media_type=MediaType.AUDIO,
            title="Night Noise",
            storage_path="audio/night.mp3",
            description="Light rain in the distance",
            search_text="night noise rain distance",
            telegram_file_id="audio-night",
            tags=[],
        )
    )

    audio_results = await service.search(
        user_id=1,
        request=SearchRequest(query_text="rain", category=QueryCategory.AUDIO, limit=20),
    )
    assert [item.title for item in audio_results] == ["Rain", "Night Noise"]

    all_results = await service.search(
        user_id=1,
        request=SearchRequest(query_text="rain", category=QueryCategory.ALL, limit=20),
    )
    assert [item.title for item in all_results] == ["Rain", "Storm Poster", "Night Noise"]


async def test_chosen_result_increments_usage_count(session_factory) -> None:
    media_repository = SqlAlchemyMediaRepository(session_factory)
    analytics_repository = SqlAlchemyAnalyticsRepository(session_factory)
    saved = await media_repository.upsert_media(
        MediaItem(
            id=0,
            media_type=MediaType.VIDEO,
            title="Intro Clip",
            storage_path="video/intro.mp4",
            search_text="intro clip",
            telegram_file_id="video-1",
        )
    )

    service = ChosenResultService(media_repository, analytics_repository)
    await service.record(user_id=10, result_id=f"media:{saved.id}", query_raw="video intro")
    updated = await media_repository.get_media_by_id(saved.id)
    assert updated is not None
    assert updated.usage_count == 1


async def test_repository_rejects_duplicate_normalized_titles(session_factory) -> None:
    repository = SqlAlchemyMediaRepository(session_factory)
    await repository.upsert_media(
        MediaItem(
            id=0,
            media_type=MediaType.AUDIO,
            title="Rain Ambience",
            storage_path="audio/rain.mp3",
            search_text="rain ambience",
            telegram_file_id="audio-1",
        )
    )

    try:
        await repository.upsert_media(
            MediaItem(
                id=0,
                media_type=MediaType.AUDIO,
                title="  rain   ambience ",
                storage_path="audio/rain-2.mp3",
                search_text="rain ambience remix",
                telegram_file_id="audio-2",
            )
        )
    except ValueError as error:
        assert "уже существует" in str(error)
    else:
        raise AssertionError("Expected duplicate normalized title rejection")


async def test_repository_update_by_id_does_not_reassign_other_item_identity(session_factory) -> None:
    repository = SqlAlchemyMediaRepository(session_factory)
    first = await repository.upsert_media(
        MediaItem(
            id=0,
            media_type=MediaType.AUDIO,
            title="First",
            storage_path="audio/first.mp3",
            search_text="first",
            telegram_file_id="audio-first",
        )
    )
    second = await repository.upsert_media(
        MediaItem(
            id=0,
            media_type=MediaType.AUDIO,
            title="Second",
            storage_path="audio/second.mp3",
            search_text="second",
            telegram_file_id="audio-second",
        )
    )

    try:
        await repository.upsert_media(
            MediaItem(
                id=first.id,
                media_type=MediaType.AUDIO,
                title="First updated",
                storage_path=second.storage_path,
                search_text="first updated",
                telegram_file_id="audio-first-new",
            )
        )
    except ValueError as error:
        assert "другой записи" in str(error)
    else:
        raise AssertionError("Expected identity conflict rejection")

    still_second = await repository.get_media_by_id(second.id)
    assert still_second is not None
    assert still_second.title == "Second"
