from __future__ import annotations

from multimedia_bot.application.query_parser import parse_inline_query
from multimedia_bot.application.result_mapper import map_media_item_to_inline_result
from multimedia_bot.application.search import SearchService
from multimedia_bot.domain.models import QueryCategory, SearchRequest


class InlineQueryService:
    def __init__(self, search_service: SearchService, search_limit: int) -> None:
        self._search_service = search_service
        self._search_limit = search_limit

    async def build_results(self, *, user_id: int, raw_query: str) -> list:
        parsed = parse_inline_query(raw_query)
        if parsed.category is QueryCategory.NONE:
            popular = await self._search_service.get_popular_media(user_id=user_id, limit=7)
            return self._map_media(popular)

        items = await self._search_service.search(
            user_id=user_id,
            request=SearchRequest(
                query_text=parsed.search_text,
                category=parsed.category,
                limit=self._search_limit,
            ),
        )
        return self._map_media(items)

    def _map_media(self, items: list) -> list:
        results = []
        for item in items:
            result = map_media_item_to_inline_result(item)
            if result is not None:
                results.append(result)
        return results
