from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from multimedia_bot.domain.models import MediaType


def admin_draft_keyboard(*, has_suggested_alias: bool) -> InlineKeyboardMarkup:
    first_row = []
    if has_suggested_alias:
        first_row.append(InlineKeyboardButton(text="Использовать предложенный алиас", callback_data="admin_draft:use"))
    first_row.append(InlineKeyboardButton(text="Ввести алиас", callback_data="admin_draft:alias"))
    return InlineKeyboardMarkup(inline_keyboard=[first_row, [InlineKeyboardButton(text="Отменить", callback_data="admin_draft:cancel")]])


def user_submission_keyboard(submission_id: int, *, has_suggested_title: bool) -> InlineKeyboardMarkup:
    first_row = []
    if has_suggested_title:
        first_row.append(
            InlineKeyboardButton(
                text="Использовать предложенное название",
                callback_data=f"user_submission:use:{submission_id}",
            )
        )
    first_row.append(
        InlineKeyboardButton(
            text="Ввести название",
            callback_data=f"user_submission:title:{submission_id}",
        )
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            first_row,
            [
                InlineKeyboardButton(
                    text="Отменить",
                    callback_data=f"user_submission:cancel:{submission_id}",
                ),
            ],
        ]
    )


def review_submission_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Принять",
                    callback_data=f"review_submission:accept:{submission_id}",
                ),
                InlineKeyboardButton(
                    text="Отклонить",
                    callback_data=f"review_submission:reject:{submission_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Изменить название",
                    callback_data=f"review_submission:edit:{submission_id}",
                ),
            ],
        ]
    )


def admin_media_list_keyboard(media_ids: list[tuple[int, str]], *, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=label, callback_data=f"admin_media:open:{media_id}")]
        for media_id, label in media_ids
    ]

    navigation_row = []
    if page > 0:
        navigation_row.append(
            InlineKeyboardButton(text="Назад", callback_data="admin_media_list:prev")
        )
    if page + 1 < total_pages:
        navigation_row.append(
            InlineKeyboardButton(text="Вперёд", callback_data="admin_media_list:next")
        )
    if navigation_row:
        rows.append(navigation_row)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_media_keyboard(media_id: int, media_type: MediaType) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Изменить алиас", callback_data=f"admin_media:title:{media_id}"),
            InlineKeyboardButton(text="Изменить описание", callback_data=f"admin_media:description:{media_id}"),
        ]
    ]
    if media_type is MediaType.TEXT:
        rows.append(
            [
                InlineKeyboardButton(text="Изменить текст", callback_data=f"admin_media:content:{media_id}"),
                InlineKeyboardButton(text="Изменить теги", callback_data=f"admin_media:tags:{media_id}"),
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(text="Изменить подпись", callback_data=f"admin_media:caption:{media_id}"),
                InlineKeyboardButton(text="Изменить теги", callback_data=f"admin_media:tags:{media_id}"),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(text="Заменить файл", callback_data=f"admin_media:replace:{media_id}"),
                InlineKeyboardButton(text="Удалить", callback_data=f"admin_media:delete_prompt:{media_id}"),
            ]
        )
    if media_type is MediaType.TEXT:
        rows.append(
            [
                InlineKeyboardButton(text="Удалить", callback_data=f"admin_media:delete_prompt:{media_id}"),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="Назад к списку", callback_data=f"admin_media:back:{media_id}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_media_delete_keyboard(media_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить удаление", callback_data=f"admin_media:delete_confirm:{media_id}"),
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data=f"admin_media:delete_cancel:{media_id}"),
            ],
        ]
    )


def admin_edit_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Отменить редактирование", callback_data="admin_media_edit:cancel"),
            ]
        ]
    )


def orphan_cleanup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Очистить", callback_data="orphan_cleanup:confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="orphan_cleanup:cancel"),
            ]
        ]
    )
