from multimedia_bot.bot.keyboards import orphan_cleanup_keyboard


def test_orphan_cleanup_keyboard_has_confirm_and_cancel_buttons() -> None:
    keyboard = orphan_cleanup_keyboard()

    assert len(keyboard.inline_keyboard) == 1
    buttons = keyboard.inline_keyboard[0]
    assert [button.text for button in buttons] == ["Очистить", "Отмена"]
    assert [button.callback_data for button in buttons] == [
        "orphan_cleanup:confirm",
        "orphan_cleanup:cancel",
    ]
