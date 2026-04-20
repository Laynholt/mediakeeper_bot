from multimedia_bot.domain.repositories import AnalyticsRepository, MediaRepository


class ChosenResultService:
    def __init__(
        self,
        media_repository: MediaRepository,
        analytics_repository: AnalyticsRepository,
    ) -> None:
        self._media_repository = media_repository
        self._analytics_repository = analytics_repository

    async def record(self, *, user_id: int, result_id: str, query_raw: str) -> None:
        if result_id.startswith("media:"):
            media_id = int(result_id.split(":", 1)[1])
            await self._media_repository.increment_usage_count(media_id)
        await self._analytics_repository.log_chosen_result(
            user_id=user_id,
            result_id=result_id,
            query_raw=query_raw,
        )
