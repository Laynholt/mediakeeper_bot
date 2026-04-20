from aiogram.fsm.state import State, StatesGroup


class AdminCatalogStates(StatesGroup):
    waiting_for_edit_value = State()
    waiting_for_replacement_file = State()
