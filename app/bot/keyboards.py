from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📈 Сигналы", callback_data="menu:signals"), InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats")],
            [InlineKeyboardButton(text="💰 Банкролл", callback_data="menu:bankroll"), InlineKeyboardButton(text="⚙️ Риск", callback_data="menu:risk")],
        ]
    )


def risk_profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Conservative", callback_data="risk:conservative")],
            [InlineKeyboardButton(text="Normal", callback_data="risk:normal")],
            [InlineKeyboardButton(text="Aggressive", callback_data="risk:aggressive")],
        ]
    )


def signal_keyboard(signal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Зашло", callback_data=f"signal:{signal_id}:won"),
                InlineKeyboardButton(text="❌ Не зашло", callback_data=f"signal:{signal_id}:lost"),
                InlineKeyboardButton(text="↩️ Возврат", callback_data=f"signal:{signal_id}:void"),
            ],
            [
                InlineKeyboardButton(text="⏳ Ожидает", callback_data=f"signal:{signal_id}:pending"),
                InlineKeyboardButton(text="📰 Инфополе", callback_data=f"signal:{signal_id}:news"),
                InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats"),
            ],
        ]
    )

