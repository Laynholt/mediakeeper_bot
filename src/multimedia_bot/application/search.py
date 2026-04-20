from multimedia_bot.application.text import normalize_text
from multimedia_bot.domain.models import MediaItem, QueryCategory, SearchRequest
from multimedia_bot.domain.repositories import AnalyticsRepository, MediaRepository


class SearchService:
    def __init__(
        self,
        media_repository: MediaRepository,
        analytics_repository: AnalyticsRepository,
    ) -> None:
        self._media_repository = media_repository
        self._analytics_repository = analytics_repository

    async def search(
        self,
        *,
        user_id: int,
        request: SearchRequest,
    ) -> list[MediaItem]:
        normalized_query = normalize_text(request.query_text)
        items = await self._media_repository.search_media(
            normalized_query=normalized_query,
            category=request.category,
            limit=request.limit,
            offset=request.offset,
        )
        await self._analytics_repository.log_search(
            user_id=user_id,
            query_raw=request.query_text,
            query_type=request.category.value,
            result_count=len(items),
        )
        return items

    async def get_popular_media(self, *, user_id: int, limit: int, offset: int = 0) -> list[MediaItem]:
        items = await self._media_repository.get_popular_media(limit=limit, offset=offset)
        await self._analytics_repository.log_search(
            user_id=user_id,
            query_raw="",
            query_type=QueryCategory.NONE.value,
            result_count=len(items),
        )
        return items
