from __future__ import annotations

from dataclasses import dataclass

from multimedia_bot.application.query_parser import parse_inline_query
from multimedia_bot.application.result_mapper import map_media_item_to_inline_result
from multimedia_bot.application.search import SearchService
from multimedia_bot.domain.models import QueryCategory, SearchRequest


@dataclass(slots=True)
class InlineQueryPage:
    results: list
    next_offset: str = ""


class InlineQueryService:
    _empty_query_limit = 7

    def __init__(self, search_service: SearchService, search_limit: int) -> None:
        self._search_service = search_service
        self._search_limit = search_limit

    async def build_page(self, *, user_id: int, raw_query: str, offset: str = "") -> InlineQueryPage:
        parsed = parse_inline_query(raw_query)
        page_offset = _parse_offset(offset)
        if parsed.category is QueryCategory.NONE:
            page_limit = min(self._empty_query_limit, self._search_limit)
            popular = await self._search_service.get_popular_media(
                user_id=user_id,
                limit=page_limit + 1,
                offset=page_offset,
            )
            return self._build_page_from_items(popular, page_offset, page_limit=page_limit)

        items = await self._search_service.search(
            user_id=user_id,
            request=SearchRequest(
                query_text=parsed.search_text,
                category=parsed.category,
                limit=self._search_limit + 1,
                offset=page_offset,
            ),
        )
        return self._build_page_from_items(items, page_offset, page_limit=self._search_limit)

    async def build_results(self, *, user_id: int, raw_query: str) -> list:
        return (await self.build_page(user_id=user_id, raw_query=raw_query)).results

    def _build_page_from_items(self, items: list, offset: int, *, page_limit: int) -> InlineQueryPage:
        page_items = items[:page_limit]
        next_offset = str(offset + page_limit) if len(items) > page_limit else ""
        return InlineQueryPage(results=self._map_media(page_items), next_offset=next_offset)

    def _map_media(self, items: list) -> list:
        results = []
        for item in items:
            result = map_media_item_to_inline_result(item)
            if result is not None:
                results.append(result)
        return results


def _parse_offset(offset: str) -> int:
    try:
        parsed = int(offset)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)
