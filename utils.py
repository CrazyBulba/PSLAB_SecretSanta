"""
Вспомогательные функции.
"""

import random
import re
from typing import Dict, Optional, Set, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_key(uid: int, parts: dict) -> str:
    info = parts.get(uid, {})
    u = info.get("username")
    return u.lower().lstrip("@") if u else f"id:{uid}"


def extract_amount(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(\d+[\s]?[рублей₽$]|до\s*\d+|\d+\s*р\.?)", text, re.IGNORECASE)
    return m.group(0).strip() if m else ""


def derangement(items: list, forbidden: Optional[Set[Tuple[str, str]]] = None, parts: dict = None) -> dict:
    if len(items) < 2:
        return {}

    def valid(a: dict) -> bool:
        if not forbidden or not parts:
            return True
        return all((get_key(g, parts), get_key(r, parts)) not in forbidden for g, r in a.items())

    for _ in range(500):
        rec = items[:]
        random.shuffle(rec)
        if all(a != b for a, b in zip(items, rec)):
            ass = dict(zip(items, rec))
            if valid(ass):
                return ass
    rec = items[:]
    while True:
        random.shuffle(rec)
        if all(a != b for a, b in zip(items, rec)):
            return dict(zip(items, rec))


def _val(v: str) -> str:
    """Пустое значение → '-'"""
    return v.strip() if v and v.strip() else "-"


def build_game_info(code: str, game: dict, user_id: int) -> str:
    parts = game["participants"]
    is_org = game.get("organizer") == user_id
    my_info = parts.get(user_id, {})

    lines = []

    intro = game.get("intro", "").strip()
    lines.append(f"📝 {intro or '-'}")
    lines.append("")
    lines.append("────────────────────")
    lines.append("")

    amount = game.get("gift_amount") or extract_amount(intro)
    lines.append(f"💰 Сумма на подарок: {_val(amount)}")

    lines.append(f"🆔 ID: {code}")
    lines.append("")

    assignments = game.get("assignments", {})
    if user_id in assignments:
        rec_id = assignments[user_id]
        rec = parts.get(rec_id, {})
        rec_name = rec.get("name", "?")
        rec_un = f" @{rec['username']}" if rec.get("username") else ""
        lines.append(f"🎁 Подопечный: {rec_name}{rec_un}")
        wish = rec.get("wishlist", "").strip()
        lines.append(f"💬 Подопечный желает: {_val(wish)}")
    else:
        lines.append("🎁 Подопечный: -")

    my_wish = my_info.get("wishlist", "").strip()
    lines.append(f"✨ Мое желание: {_val(my_wish)}")
    lines.append(f"👥 Участников: {len(parts)}")

    if is_org:
        lines.append("")
        drawn = "да" if assignments else "нет"
        lines.append(f"🎲 Розыгрыш: {drawn}")
        avoid = game.get("avoid_previous", False)
        forbidden = game.get("forbidden_pairs", set())
        status = "вкл" if avoid else "выкл"
        lines.append(f"🛡 Избегать: {status} ({len(forbidden)} пар)")
        if avoid and forbidden:
            pairs = [f"@{a}→@{b}" for a, b in list(forbidden)[:10]]
            lines.append("   " + ", ".join(pairs))
            if len(forbidden) > 10:
                lines.append(f"   ... и ещё {len(forbidden)-10}")

    return "\n".join(lines)


def build_edit_keyboard(code: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("📝 Вступительное", callback_data=f"edit_intro:{code}"),
            InlineKeyboardButton("💰 Сумма", callback_data=f"edit_amount:{code}"),
        ],
        [
            InlineKeyboardButton("🆔 Изменить ID", callback_data=f"edit_id:{code}"),
            InlineKeyboardButton("🛡 Избегать on/off", callback_data=f"toggle_avoid:{code}"),
        ],
        [
            InlineKeyboardButton("📤 Экспорт", callback_data=f"export:{code}"),
            InlineKeyboardButton("🔗 Импорт пар", callback_data=f"import_prev:{code}"),
        ],
        [
            InlineKeyboardButton("← Назад", callback_data=f"info:{code}"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)
