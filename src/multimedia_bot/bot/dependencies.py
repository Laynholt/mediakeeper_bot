from dataclasses import dataclass

from multimedia_bot.application.admin_catalog import AdminCatalogService
from multimedia_bot.application.admin_ingestion import AdminIngestionService
from multimedia_bot.application.chosen_result import ChosenResultService
from multimedia_bot.application.inline_service import InlineQueryService
from multimedia_bot.application.orphan_cleanup import OrphanCleanupService
from multimedia_bot.application.user_submission import UserSubmissionService


@dataclass(slots=True)
class AppContainer:
    inline_query_service: InlineQueryService
    chosen_result_service: ChosenResultService
    admin_ingestion_service: AdminIngestionService
    admin_catalog_service: AdminCatalogService
    orphan_cleanup_service: OrphanCleanupService
    user_submission_service: UserSubmissionService
    inline_cache_time: int
