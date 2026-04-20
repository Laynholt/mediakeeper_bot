from pathlib import Path

from aiogram import F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChosenInlineResult, FSInputFile, InlineQuery, Message

from multimedia_bot.application.file_storage import delete_local_file
from multimedia_bot.bot.dependencies import AppContainer
from multimedia_bot.bot.keyboards import (
    admin_draft_keyboard,
    admin_media_delete_keyboard,
    admin_media_list_keyboard,
    admin_edit_cancel_keyboard,
    admin_media_keyboard,
    orphan_cleanup_keyboard,
    review_submission_keyboard,
    user_submission_keyboard,
)
from multimedia_bot.bot.states import AdminCatalogStates
from multimedia_bot.domain.models import SubmissionStatus
from multimedia_bot.application.validation import is_valid_record_title


def create_router(container: AppContainer) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        is_admin = message.from_user is not None and container.admin_ingestion_service.is_admin(message.from_user.id)
        await message.answer(_build_start_text(is_admin=is_admin), parse_mode="HTML")

    @router.inline_query()
    async def handle_inline_query(inline_query: InlineQuery) -> None:
        results = await container.inline_query_service.build_results(
            user_id=inline_query.from_user.id,
            raw_query=inline_query.query,
        )
        await inline_query.answer(
            results=results,
            cache_time=container.inline_cache_time,
            is_personal=True,
        )

    @router.chosen_inline_result()
    async def handle_chosen_result(chosen_result: ChosenInlineResult) -> None:
        await container.chosen_result_service.record(
            user_id=chosen_result.from_user.id,
            result_id=chosen_result.result_id,
            query_raw=chosen_result.query,
        )

    @router.message(
        F.chat.type == "private",
        StateFilter(AdminCatalogStates.waiting_for_replacement_file),
        F.content_type.in_({"audio", "photo", "video"}),
    )
    async def handle_admin_media_replacement(message: Message, state: FSMContext) -> None:
        if not container.admin_catalog_service.is_admin(message.from_user.id):
            await _clear_admin_catalog_state(state)
            return

        data = await state.get_data()
        media_id = data.get("media_id")
        if not media_id:
            await _clear_admin_catalog_state(state)
            await message.answer("Состояние замены файла повреждено. Начните заново через /admin_media.")
            return

        try:
            item = await container.admin_catalog_service.replace_media_file(
                media_id=int(media_id),
                message=message,
            )
        except (LookupError, ValueError) as error:
            await message.answer(str(error))
            return

        await _clear_admin_catalog_state(state)
        await message.answer(
            "Файл медиа заменён.\n" + container.admin_catalog_service.format_media_card(item),
            reply_markup=admin_media_keyboard(item.id, item.media_type),
        )

    @router.message(F.chat.type == "private", StateFilter(None), F.content_type.in_({"audio", "photo", "video"}))
    async def handle_private_media(message: Message) -> None:
        if container.admin_ingestion_service.is_admin(message.from_user.id):
            draft = await container.admin_ingestion_service.create_draft_from_message(message)
            has_suggested_alias = is_valid_record_title(draft.suggested_title)
            await message.answer(
                (
                    "Черновик администратора создан.\n"
                    f"Предложенный алиас: {draft.suggested_title}\n"
                    "Выберите следующее действие."
                    if has_suggested_alias
                    else "Черновик администратора создан.\nКорректный предложенный алиас не найден.\nВыберите следующее действие."
                ),
                reply_markup=admin_draft_keyboard(has_suggested_alias=has_suggested_alias),
            )
            return

        if not container.user_submission_service.review_enabled():
            await message.answer("Пользовательские заявки отключены: ADMIN_USER_ID не настроен.")
            return

        submission = await container.user_submission_service.create_submission_from_message(message)
        has_suggested_title = is_valid_record_title(submission.suggested_title)
        await message.answer(
            (
                "Медиа получено.\n"
                f"Предложенное название: {submission.suggested_title}\n"
                "Выберите вариант ниже."
                if has_suggested_title
                else "Медиа получено.\nКорректное предложенное название не найдено.\nВыберите вариант ниже."
            ),
            reply_markup=user_submission_keyboard(
                submission.id,
                has_suggested_title=has_suggested_title,
            ),
        )

    @router.message(F.chat.type == "private", F.text.startswith("/admin_media"))
    async def handle_admin_media_command(message: Message, state: FSMContext) -> None:
        if not container.admin_catalog_service.is_admin(message.from_user.id):
            return

        query = message.text.partition(" ")[2].strip() or None
        await state.set_state(None)
        await state.update_data(catalog_query=query, catalog_page=0)
        await _send_admin_media_page(message=message, state=state, container=container)

    @router.message(F.chat.type == "private", F.text == "/admin_export")
    async def handle_admin_export(message: Message) -> None:
        if not container.admin_catalog_service.is_admin(message.from_user.id):
            return

        path, count = await container.admin_catalog_service.export_manifest()
        try:
            await message.answer_document(
                document=FSInputFile(str(path)),
                caption=f"Экспортировано {count} медиафайлов.",
            )
        finally:
            delete_local_file(str(path))

    @router.message(F.chat.type == "private", F.text == "/admin_reimport")
    async def handle_admin_reimport(message: Message) -> None:
        if not container.admin_catalog_service.is_admin(message.from_user.id):
            return

        imported = await container.admin_catalog_service.reimport_current_catalog()
        await message.answer(f"Переимпортировано {imported} медиафайлов в текущего бота.")

    @router.message(F.chat.type == "private", F.text.startswith("/admin_cleanup_orphans"))
    async def handle_admin_cleanup_orphans(message: Message) -> None:
        if not container.orphan_cleanup_service.is_admin(message.from_user.id):
            return

        result = await container.orphan_cleanup_service.find_orphans()
        if result.count == 0:
            await message.answer("Лишних файлов в хранилище не найдено.")
            return

        preview = "\n".join(str(path) for path in result.files[:20])
        suffix = "\n..." if result.count > 20 else ""
        await message.answer(
            "Найдены лишние файлы.\n"
            f"Количество: {result.count}\n\n"
            f"{preview}{suffix}\n\n"
            "Нажмите кнопку ниже, чтобы удалить их или отменить действие.",
            reply_markup=orphan_cleanup_keyboard(),
        )

    @router.message(F.chat.type == "private", F.document)
    async def handle_admin_import_document(message: Message) -> None:
        if not container.admin_catalog_service.is_admin(message.from_user.id):
            return
        if message.document is None or not (message.document.file_name or "").lower().endswith(".json"):
            return

        destination = Path("data/imports") / message.document.file_name
        await container.admin_catalog_service.download_document(
            file_id=message.document.file_id,
            destination=destination,
        )
        try:
            imported = await container.admin_catalog_service.import_manifest(destination)
        except Exception as error:
            await message.answer(f"Импорт завершился ошибкой: {error}")
        else:
            await message.answer(f"Импортировано {imported} медиафайлов из манифеста.")
        finally:
            delete_local_file(str(destination))

    @router.callback_query(F.message.chat.type == "private", F.data.startswith("admin_media_list:"))
    async def handle_admin_media_list_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not container.admin_catalog_service.is_admin(callback.from_user.id):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        data = await state.get_data()
        page = int(data.get("catalog_page", 0))
        action = callback.data.split(":", maxsplit=1)[1]
        if action == "prev":
            page -= 1
        elif action == "next":
            page += 1

        await state.update_data(catalog_page=page)
        await _edit_admin_media_page(message=callback.message, state=state, container=container)
        await callback.answer()

    @router.callback_query(F.message.chat.type == "private", F.data.startswith("admin_draft:"))
    async def handle_admin_draft_callback(callback: CallbackQuery) -> None:
        if not container.admin_ingestion_service.is_admin(callback.from_user.id):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        action = callback.data.split(":", maxsplit=1)[1]
        if action == "use":
            draft = await container.admin_ingestion_service.get_pending_draft(callback.from_user.id)
            if draft is None or not is_valid_record_title(draft.suggested_title):
                await callback.answer("Нет корректного предложенного алиаса.", show_alert=True)
                return
            try:
                item = await container.admin_ingestion_service.finalize_draft_with_suggested_title(
                    admin_user_id=callback.from_user.id,
                )
            except ValueError as error:
                await callback.answer(str(error), show_alert=True)
                return
            await callback.message.edit_text(
                f"Опубликован {item.media_type.value} с алиасом: {item.title}\n"
                "Теперь пользователи могут найти его через inline-режим."
            )
            await callback.answer("Опубликовано.")
            return

        if action == "alias":
            try:
                draft = await container.admin_ingestion_service.request_alias_input(callback.from_user.id)
            except LookupError:
                await callback.answer("Черновик больше не существует.", show_alert=True)
                return
            await callback.message.edit_text(
                "Отправьте алиас следующим текстовым сообщением.\n"
                f"Предложенный алиас: {draft.suggested_title}"
            )
            await callback.answer("Ожидаю алиас.")
            return

        cancelled = await container.admin_ingestion_service.cancel_pending_draft(callback.from_user.id)
        await callback.message.edit_text(
            "Черновик отменён." if cancelled else "Нет черновика для отмены."
        )
        await callback.answer("Отменено.")

    @router.callback_query(F.message.chat.type == "private", F.data.startswith("user_submission:"))
    async def handle_user_submission_callback(callback: CallbackQuery) -> None:
        _, action, submission_id_raw = callback.data.split(":")
        submission_id = int(submission_id_raw)

        if action == "use":
            submission = await container.user_submission_service.get_submission_for_user(
                submission_id=submission_id,
                user_id=callback.from_user.id,
            )
            if submission is None or not is_valid_record_title(submission.suggested_title):
                await callback.answer("Нет корректного предложенного названия.", show_alert=True)
                return
            try:
                submission = await container.user_submission_service.submit_with_suggested_title(
                    submission_id=submission_id,
                    user_id=callback.from_user.id,
                    submitter=callback.from_user,
                    reply_markup=review_submission_keyboard(submission_id),
                )
            except ValueError as error:
                await callback.answer(str(error), show_alert=True)
                return
            await callback.message.edit_text(
                "Заявка отправлена администраторам на проверку.\n"
                f"Название: {submission.title}"
            )
            await callback.answer("Отправлено на модерацию.")
            return

        if action == "title":
            try:
                submission = await container.user_submission_service.request_user_title_input(
                    submission_id=submission_id,
                    user_id=callback.from_user.id,
                )
            except (LookupError, ValueError):
                await callback.answer("Заявка больше недоступна.", show_alert=True)
                return
            await callback.message.edit_text(
                "Отправьте название следующим текстовым сообщением.\n"
                f"Предложенное название: {submission.suggested_title}"
            )
            await callback.answer("Ожидаю название.")
            return

        try:
            await container.user_submission_service.cancel_submission(
                submission_id=submission_id,
                user_id=callback.from_user.id,
            )
        except (LookupError, ValueError):
            await callback.answer("Заявка больше недоступна.", show_alert=True)
            return
        await callback.message.edit_text("Заявка отменена.")
        await callback.answer("Отменено.")

    @router.callback_query(F.message.chat.type == "private", F.data.startswith("admin_media:"))
    async def handle_admin_media_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not container.admin_catalog_service.is_admin(callback.from_user.id):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        _, action, *rest = callback.data.split(":")
        media_id_raw = rest[-1]
        media_id = int(media_id_raw)

        if action == "open":
            item = await container.admin_catalog_service.get_media(media_id)
            if item is None:
                await callback.answer("Медиафайл больше не существует.", show_alert=True)
                return
            await callback.message.edit_text(
                container.admin_catalog_service.format_media_card(item),
                reply_markup=admin_media_keyboard(item.id, item.media_type),
            )
            await callback.answer()
            return

        if action == "back":
            await _edit_admin_media_page(message=callback.message, state=state, container=container)
            await callback.answer()
            return

        if action == "delete_prompt":
            item = await container.admin_catalog_service.get_media(media_id)
            if item is None:
                await callback.answer("Медиафайл больше не существует.", show_alert=True)
                return
            await callback.message.edit_text(
                container.admin_catalog_service.format_media_card(item) + "\n\nУдалить этот медиафайл?",
                reply_markup=admin_media_delete_keyboard(item.id),
            )
            await callback.answer("Подтвердите удаление.")
            return

        if action == "delete_confirm":
            try:
                item = await container.admin_catalog_service.delete_media(media_id)
            except LookupError:
                await callback.answer("Медиафайл больше не существует.", show_alert=True)
                return
            await callback.answer("Удалено.")
            await _edit_admin_media_page(
                message=callback.message,
                state=state,
                container=container,
                notice=f"Удалён медиафайл #{item.id}: {item.title}",
            )
            return

        if action == "delete_cancel":
            item = await container.admin_catalog_service.get_media(media_id)
            if item is None:
                await callback.answer("Медиафайл больше не существует.", show_alert=True)
                return
            await callback.message.edit_text(
                container.admin_catalog_service.format_media_card(item),
                reply_markup=admin_media_keyboard(item.id, item.media_type),
            )
            await callback.answer("Удаление отменено.")
            return

        if action == "replace":
            item = await container.admin_catalog_service.get_media(media_id)
            if item is None:
                await callback.answer("Медиафайл больше не существует.", show_alert=True)
                return
            await state.set_state(AdminCatalogStates.waiting_for_replacement_file)
            await state.update_data(media_id=media_id)
            await callback.message.answer(
                f"Отправьте новый файл типа {item.media_type.value} для медиа #{media_id}.",
                reply_markup=admin_edit_cancel_keyboard(),
            )
            await callback.answer("Ожидаю файл.")
            return

        await state.set_state(AdminCatalogStates.waiting_for_edit_value)
        await state.update_data(media_id=media_id, field=action)
        field_label = {
            "title": "новый алиас",
            "description": "новое описание",
            "caption": "новую подпись",
            "content": "новый текст",
            "tags": "теги через запятую",
        }[action]
        await callback.message.answer(
            f"Отправьте {field_label} для медиа #{media_id}.",
            reply_markup=admin_edit_cancel_keyboard(),
        )
        await callback.answer("Ожидаю значение.")

    @router.callback_query(F.message.chat.type == "private", F.data == "admin_media_edit:cancel")
    async def handle_admin_edit_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        if not container.admin_catalog_service.is_admin(callback.from_user.id):
            await callback.answer("Только для администраторов.", show_alert=True)
            return
        await _clear_admin_catalog_state(state)
        await callback.message.edit_text("Редактирование админом отменено.")
        await callback.answer("Отменено.")

    @router.callback_query(F.message.chat.type == "private", F.data.startswith("orphan_cleanup:"))
    async def handle_orphan_cleanup_callback(callback: CallbackQuery) -> None:
        if not container.orphan_cleanup_service.is_admin(callback.from_user.id):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        action = callback.data.split(":", maxsplit=1)[1]
        if action == "confirm":
            result = await container.orphan_cleanup_service.cleanup_orphans()
            await callback.message.edit_text(
                "Очистка лишних файлов завершена.\n"
                f"Удалено файлов: {result.count}"
            )
            await callback.answer("Очистка завершена.")
            return

        await callback.message.edit_text("Очистка лишних файлов отменена.")
        await callback.answer("Отменено.")

    @router.callback_query(F.data.startswith("review_submission:"))
    async def handle_review_submission_callback(callback: CallbackQuery) -> None:
        if not container.user_submission_service.is_admin(callback.from_user.id):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        _, action, submission_id_raw = callback.data.split(":")
        submission_id = int(submission_id_raw)

        if action == "accept":
            try:
                submission, item = await container.user_submission_service.accept_submission(
                    submission_id=submission_id,
                    admin_user_id=callback.from_user.id,
                )
            except (LookupError, ValueError) as error:
                await callback.answer(str(error), show_alert=True)
                return
            await container.user_submission_service.clear_review_markup(submission)
            await container.user_submission_service.notify_user_about_acceptance(submission, item)
            await callback.message.answer(f"Одобрено: {item.title}")
            await callback.answer("Одобрено.")
            return

        if action == "reject":
            try:
                submission = await container.user_submission_service.reject_submission(
                    submission_id=submission_id,
                    admin_user_id=callback.from_user.id,
                )
            except (LookupError, ValueError) as error:
                await callback.answer(str(error), show_alert=True)
                return
            await container.user_submission_service.clear_review_markup(submission)
            await container.user_submission_service.notify_user_about_rejection(submission)
            await callback.message.answer(f"Заявка #{submission.id} отклонена.")
            await callback.answer("Отклонено.")
            return

        try:
            submission = await container.user_submission_service.start_admin_edit(
                submission_id=submission_id,
                admin_user_id=callback.from_user.id,
            )
        except (LookupError, ValueError) as error:
            await callback.answer(str(error), show_alert=True)
            return
        await callback.answer("Отправьте новое название текстовым сообщением.")
        await callback.message.answer(
            f"Редактирование заявки #{submission.id}.\n"
            "Отправьте новое название следующим текстовым сообщением."
        )

    @router.message(F.chat.type == "private", StateFilter(AdminCatalogStates.waiting_for_edit_value), F.text)
    async def handle_admin_catalog_edit_text(message: Message, state: FSMContext) -> None:
        if not container.admin_catalog_service.is_admin(message.from_user.id):
            await _clear_admin_catalog_state(state)
            return

        data = await state.get_data()
        media_id = data.get("media_id")
        field = data.get("field")
        if not media_id or not field:
            await _clear_admin_catalog_state(state)
            await message.answer("Состояние редактирования повреждено. Начните заново через /admin_media.")
            return

        try:
            item = await container.admin_catalog_service.update_media_field(
                media_id=int(media_id),
                field=field,
                raw_value=message.text,
            )
        except (LookupError, ValueError) as error:
            await message.answer(str(error))
            return

        await _clear_admin_catalog_state(state)
        await message.answer(
            "Медиа обновлено.\n" + container.admin_catalog_service.format_media_card(item),
            reply_markup=admin_media_keyboard(item.id, item.media_type),
        )

    @router.message(F.chat.type == "private", StateFilter(None), F.text)
    async def handle_private_text(message: Message) -> None:
        if container.admin_ingestion_service.is_admin(message.from_user.id):
            if message.text == "/cancel":
                cancelled = await container.admin_ingestion_service.cancel_pending_draft(message.from_user.id)
                await message.answer("Черновик отменён." if cancelled else "Нет черновика для отмены.")
                return

            draft = await container.admin_ingestion_service.get_pending_draft(message.from_user.id)
            if draft is not None and draft.awaiting_alias_input:
                try:
                    item = await container.admin_ingestion_service.finalize_draft_with_alias(
                        admin_user_id=message.from_user.id,
                        alias=message.text,
                    )
                except ValueError as error:
                    await message.answer(str(error))
                    return
                await message.answer(
                    f"Опубликован {item.media_type.value} с алиасом: {item.title}\n"
                    "Теперь пользователи могут найти его через inline-режим."
                )
                return

        pending_submission = await container.user_submission_service.get_latest_actionable_submission(
            message.from_user.id
        )
        if pending_submission is not None and pending_submission.status is SubmissionStatus.AWAITING_USER_TITLE:
            try:
                submission = await container.user_submission_service.submit_with_custom_title(
                    user_id=message.from_user.id,
                    title=message.text,
                    submitter=message.from_user,
                    reply_markup=review_submission_keyboard(pending_submission.id),
                )
            except ValueError as error:
                await message.answer(str(error))
                return
            await message.answer(
                "Заявка отправлена администраторам на проверку.\n"
                f"Название: {submission.title}"
            )
            return

        if container.user_submission_service.is_admin(message.from_user.id):
            handled = await _handle_admin_review_title(message, container)
            if handled:
                return

        if message.text.startswith("/"):
            return

        if container.admin_ingestion_service.is_admin(message.from_user.id):
            draft = await container.admin_ingestion_service.create_text_draft(
                admin_user_id=message.from_user.id,
                text=message.text,
            )
            has_suggested_alias = is_valid_record_title(draft.suggested_title)
            await message.answer(
                (
                    "Текстовый черновик администратора создан.\n"
                    f"Предложенный алиас: {draft.suggested_title}\n"
                    "Выберите следующее действие."
                    if has_suggested_alias
                    else "Текстовый черновик администратора создан.\nКорректный предложенный алиас не найден.\nВыберите следующее действие."
                ),
                reply_markup=admin_draft_keyboard(has_suggested_alias=has_suggested_alias),
            )
            return

        if not container.user_submission_service.review_enabled():
            await message.answer("Пользовательские заявки отключены: ADMIN_USER_ID не настроен.")
            return

        submission = await container.user_submission_service.create_text_submission(
            user_id=message.from_user.id,
            text=message.text,
        )
        has_suggested_title = is_valid_record_title(submission.suggested_title)
        await message.answer(
            (
                "Текст получен.\n"
                f"Предложенное название: {submission.suggested_title}\n"
                "Выберите вариант ниже."
                if has_suggested_title
                else "Текст получен.\nКорректное предложенное название не найдено.\nВыберите вариант ниже."
            ),
            reply_markup=user_submission_keyboard(
                submission.id,
                has_suggested_title=has_suggested_title,
            ),
        )

    return router


def _build_start_text(*, is_admin: bool) -> str:
    common = (
        "<b>Мультимедиа-каталог</b>\n"
        "Быстрые ответы через inline-режим: аудио, изображения, видео и текстовые фразы.\n\n"
        "<b>Как искать</b>\n"
        "<code>@botname audio rain</code> - аудио\n"
        "<code>@botname image sunset</code> - изображение\n"
        "<code>@botname video intro</code> - видео\n"
        "<code>@botname text greeting</code> - текст\n"
        "<code>@botname rain ambience</code> - поиск по всему каталогу"
    )
    if is_admin:
        return (
            f"{common}\n\n"
            "<b>Панель администратора</b>\n"
            "1. Отправьте медиа или текст в этот чат.\n"
            "2. Проверьте предложенный алиас или задайте свой.\n"
            "3. После подтверждения запись появится в inline-каталоге.\n\n"
            "<b>Команды</b>\n"
            "<code>/admin_media</code> - каталог и редактирование\n"
            "<code>/admin_export</code> - экспорт JSON\n"
            "<code>/admin_reimport</code> - переимпорт текущих записей\n"
            "<code>/admin_cleanup_orphans</code> - поиск лишних файлов\n"
            "<code>/cancel</code> - отменить текущий черновик"
        )

    return (
        f"{common}\n\n"
        "<b>Отправить материал</b>\n"
        "Пришлите аудио, фото, видео или обычный текст в этот чат.\n\n"
        "<b>Что дальше</b>\n"
        "1. Бот предложит название.\n"
        "2. Вы подтвердите его или введёте своё.\n"
        "3. Администратор проверит заявку.\n"
        "4. После одобрения материал появится в inline-каталоге."
    )


async def _handle_admin_review_title(message: Message, container: AppContainer) -> bool:
    if not container.user_submission_service.is_admin(message.from_user.id):
        return False

    try:
        submission, item = await container.user_submission_service.complete_admin_edit(
            admin_user_id=message.from_user.id,
            title=message.text,
        )
    except (LookupError, ValueError):
        return False

    await container.user_submission_service.clear_review_markup(submission)
    await container.user_submission_service.notify_user_about_acceptance(submission, item)
    await message.answer(
        f"Заявка #{submission.id} одобрена с исправленным названием: {item.title}"
    )
    return True


async def _send_admin_media_page(
    *,
    message: Message,
    state: FSMContext,
    container: AppContainer,
) -> None:
    page_text, keyboard, normalized_page = await _build_admin_media_page(
        state=state,
        container=container,
    )
    await state.update_data(catalog_page=normalized_page)
    await message.answer(page_text, reply_markup=keyboard)


async def _edit_admin_media_page(
    *,
    message: Message,
    state: FSMContext,
    container: AppContainer,
    notice: str | None = None,
) -> None:
    page_text, keyboard, normalized_page = await _build_admin_media_page(
        state=state,
        container=container,
    )
    await state.update_data(catalog_page=normalized_page)
    text = f"{notice}\n\n{page_text}" if notice else page_text
    await message.edit_text(text, reply_markup=keyboard)


async def _build_admin_media_page(
    *,
    state: FSMContext,
    container: AppContainer,
) -> tuple[str, object, int]:
    data = await state.get_data()
    query = data.get("catalog_query")
    page = int(data.get("catalog_page", 0))
    items, total, normalized_page, total_pages = await container.admin_catalog_service.list_media_page(
        query=query,
        page=page,
    )
    text = container.admin_catalog_service.format_media_page(
        items=items,
        query=query,
        page=normalized_page,
        total=total,
        total_pages=total_pages,
    )
    keyboard = admin_media_list_keyboard(
        [(item.id, f"{item.title} [{item.media_type.value}]") for item in items],
        page=normalized_page,
        total_pages=total_pages,
    )
    return text, keyboard, normalized_page


async def _clear_admin_catalog_state(state: FSMContext) -> None:
    data = await state.get_data()
    preserved = {
        "catalog_query": data.get("catalog_query"),
        "catalog_page": data.get("catalog_page", 0),
    }
    await state.clear()
    await state.update_data(**preserved)
