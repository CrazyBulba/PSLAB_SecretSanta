"""
Обработчики команд и callback-запросов.
"""

import logging
import time
from typing import Optional, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ContextTypes

from messages import PROMPTS, HELP_TEXT, create_success_message, join_success
from storage import manager
from utils import (
    get_key,
    extract_amount,
    derangement,
    build_game_info,
    build_edit_keyboard,
)

logger = logging.getLogger(__name__)
START_TIME = time.time()


async def select_game(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    organizer: bool = False,
    active: bool = True,
    action: str = "info",
    include_all: bool = False,
) -> Optional[Tuple[str, dict]]:
    user_id = update.effective_user.id
    args = context.args or []
    code = args[0].upper() if args and args[0].upper() in manager.games else None

    games = manager.user_games(user_id, organizer=organizer, active_only=active)
    if not games:
        await update.message.reply_text("Нет подходящих игр.")
        return None

    if code:
        game = next((g for c, g in games if c == code), None)
        if game:
            return code, game
        await update.message.reply_text("Игра не найдена.")
        return None

    if len(games) == 1:
        return games[0]

    buttons = [
        [InlineKeyboardButton(f"✅ {c} ({len(g['participants'])} чел.)", callback_data=f"{action}:{c}")]
        for c, g in games
    ]
    if include_all and len(games) > 1:
        buttons.append([InlineKeyboardButton("🗑 Удалить все", callback_data=f"{action}:ALL")])
    await update.message.reply_text("Выберите игру:", reply_markup=InlineKeyboardMarkup(buttons))
    return None


async def send_result(bot, uid: int, code: str, game: dict) -> bool:
    if uid not in game.get("assignments", {}):
        return False
    rec_id = game["assignments"][uid]
    rec = game["participants"].get(rec_id)
    if not rec:
        return False
    uname = f"@{rec['username']}" if rec.get("username") else ""
    text = f"🎁 Тайный Санта!\n\nВы дарите: {rec['name']} {uname}\n\nПожелания:\n{rec['wishlist'] or 'Нет'}\n\nGameID: {code}"
    try:
        await bot.send_message(uid, text)
        game["participants"][uid]["notified"] = True
        manager.save()
        return True
    except Exception:
        game["participants"][uid]["notified"] = False
        manager.save()
        return False


async def check_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    sent = False
    for code, g in list(manager.games.items()):
        if g.get("assignments") and uid in g["participants"] and not g["participants"][uid].get("notified"):
            if await send_result(context.bot, uid, code, g):
                sent = True
    if sent and update.message:
        await update.message.reply_text("✅ Результат отправлен!")


async def handle_awaiting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    awaiting = context.user_data.get("awaiting")
    if not awaiting or not update.message or not update.message.text:
        return False

    text = update.message.text.strip()
    if not text or text.startswith("/"):
        return False

    kind = awaiting.get("type")
    code = awaiting.get("code")
    context.user_data.pop("awaiting", None)

    if kind == "intro" and code and code in manager.games:
        manager.games[code]["intro"] = text
        amount = extract_amount(text)
        if amount and not manager.games[code].get("gift_amount"):
            manager.games[code]["gift_amount"] = amount
        manager.save()
        await update.message.reply_text(f"✅ Вступительное для игры {code} сохранено!")
        return True

    if kind == "wish" and code and code in manager.games:
        uid = update.effective_user.id
        if uid in manager.games[code]["participants"]:
            manager.games[code]["participants"][uid]["wishlist"] = text
            manager.save()
            await update.message.reply_text(f"✅ Пожелания для игры {code} сохранены!")
            return True

    if kind == "import_pairs" and code and code in manager.games:
        added = 0
        for p in text.split():
            if ":" in p:
                a, b = p.split(":", 1)
                a, b = a.lower().lstrip("@"), b.lower().lstrip("@")
                if a and b:
                    manager.games[code].setdefault("forbidden_pairs", set()).add((a, b))
                    added += 1
        manager.save()
        await update.message.reply_text(f"✅ Добавлено {added} пар.")
        return True

    if kind == "create_intro":
        intro = "" if text.lower() in ("пропустить", "skip", "-", "нет") else text
        context.user_data["pending_intro"] = intro
        context.user_data["awaiting"] = {"type": "create_amount"}
        await update.message.reply_text(PROMPTS["amount"] + "\n\nИли отправьте «пропустить».")
        return True

    if kind == "create_amount":
        amount = "" if text.lower() in ("пропустить", "skip", "-", "нет") else text
        intro = context.user_data.pop("pending_intro", "")
        new_code = manager.create(update.effective_user, intro, amount)
        await update.message.reply_text(create_success_message(new_code))
        return True

    if kind == "amount" and code and code in manager.games:
        manager.games[code]["gift_amount"] = text
        manager.save()
        await update.message.reply_text(f"✅ Сумма для {code}: {text}")
        return True

    return False


# ─── Commands ───

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting", None)
    await check_pending(update, context)
    await update.message.reply_text(HELP_TEXT)


async def cmd_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        intro = " ".join(context.args)
        amount = extract_amount(intro)
        code = manager.create(update.effective_user, intro, amount)
        await update.message.reply_text(create_success_message(code))
        return
    context.user_data["awaiting"] = {"type": "create_intro"}
    await update.message.reply_text(
        "🎄 Создаём игру.\n\n" + PROMPTS["intro"] + "\n\nИли отправьте «пропустить»."
    )


async def cmd_setintro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = await select_game(update, context, organizer=True, action="setintro_select")
    if not res:
        return
    code, game = res
    if context.args and not (context.args[0].upper() == code and len(context.args) == 1):
        text = " ".join(context.args[1:] if context.args[0].upper() == code else context.args)
        game["intro"] = text
        amount = extract_amount(text)
        if amount:
            game["gift_amount"] = amount
        manager.save()
        await update.message.reply_text(f"✅ Вступительное для {code} сохранено.")
        return
    context.user_data["awaiting"] = {"type": "intro", "code": code}
    await update.message.reply_text(PROMPTS["intro"])


async def cmd_setamount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = await select_game(update, context, organizer=True, action="setamount")
    if not res:
        return
    code, game = res
    if context.args and not (context.args[0].upper() == code and len(context.args) == 1):
        text = " ".join(context.args[1:] if context.args[0].upper() == code else context.args)
        game["gift_amount"] = text
        manager.save()
        await update.message.reply_text(f"✅ Сумма для {code}: {text}")
        return
    context.user_data["awaiting"] = {"type": "amount", "code": code}
    await update.message.reply_text(PROMPTS["amount"])


async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/join GameID")
        return
    code = context.args[0].upper()
    err = manager.join(code, update.effective_user)
    if err:
        await update.message.reply_text(f"❌ {err}")
        return
    game = manager.games[code]
    await update.message.reply_text(join_success(code, game.get("intro", "")))


async def cmd_mygames(update: Update, context: ContextTypes.DEFAULT_TYPE):
    games = manager.user_games(update.effective_user.id, active_only=True)
    if not games:
        await update.message.reply_text("Нет активных игр. /create")
        return
    buttons = [
        [InlineKeyboardButton(f"✅ {c} ({len(g['participants'])})", callback_data=f"info:{c}")]
        for c, g in games
    ]
    await update.message.reply_text("Ваши активные игры:", reply_markup=InlineKeyboardMarkup(buttons))


async def cmd_setwish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = await select_game(update, context, organizer=False, action="setwish_select")
    if not res:
        return
    code, game = res
    if context.args and not (context.args[0].upper() == code and len(context.args) == 1):
        text = " ".join(context.args[1:] if context.args[0].upper() == code else context.args)
        game["participants"][update.effective_user.id]["wishlist"] = text
        manager.save()
        await update.message.reply_text(f"✅ Пожелания для {code} сохранены.")
        return
    context.user_data["awaiting"] = {"type": "wish", "code": code}
    await update.message.reply_text(PROMPTS["wish"])


async def cmd_participants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = await select_game(update, context, organizer=True, action="participants")
    if not res:
        return
    code, game = res
    lines = [f"Участники {code} ({len(game['participants'])}):"]
    for uid, info in game["participants"].items():
        un = f"@{info['username']}" if info.get("username") else ""
        lines.append(f"• {info['name']} {un} — {info['wishlist'] or '—'}")
    await update.message.reply_text("\n".join(lines))


async def cmd_draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = await select_game(update, context, organizer=True, action="draw")
    if not res:
        return
    code, game = res
    parts = list(game["participants"].keys())
    if len(parts) < 2:
        await update.message.reply_text("Нужно ≥2 участника")
        return
    forbidden = game.get("forbidden_pairs") if game.get("avoid_previous") else None
    game["assignments"] = derangement(parts, forbidden, game["participants"])
    for uid in parts:
        game["participants"][uid]["notified"] = False
    manager.save()
    ok = 0
    for uid in parts:
        if await send_result(context.bot, uid, code, game):
            ok += 1
    msg = f"✅ Розыгрыш {code}! Отправлено {ok}/{len(parts)}"
    if game.get("avoid_previous"):
        msg += "\n🛡 Учтены запрещённые пары"
    await update.message.reply_text(msg)


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = await select_game(update, context, organizer=True, active=True, action="export")
    if not res:
        return
    code, game = res
    if not game.get("assignments"):
        await update.message.reply_text("Нет розыгрыша")
        return
    lines = []
    for g_id, r_id in game["assignments"].items():
        gk = get_key(g_id, game["participants"])
        rk = get_key(r_id, game["participants"])
        if not gk.startswith("id:") and not rk.startswith("id:"):
            lines.append(f"@{gk}:@{rk}")
    if not lines:
        await update.message.reply_text("Нет пар с username")
        return
    text = " ".join(lines)
    await update.message.reply_text(f"📤 Экспорт {code}\n\n`/import_previous {text}`\n\n{text}", parse_mode="Markdown")


async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = (context.args or [""])[0].upper()
    if arg in ("ALL", "ВСЕ"):
        games = manager.user_games(update.effective_user.id, organizer=True, active_only=True)
        count = len(games)
        for c, _ in games:
            manager.delete(c)
        await update.message.reply_text(f"✅ Удалено игр: {count}")
        return
    res = await select_game(update, context, organizer=True, action="close", include_all=True)
    if not res:
        return
    code, game = res
    manager.delete(code)
    await update.message.reply_text(f"✅ Игра {code} удалена")


async def cmd_avoid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[-1].lower() not in ("on", "off", "вкл", "выкл"):
        await update.message.reply_text("/avoid on|off")
        return
    enable = context.args[-1].lower() in ("on", "вкл")
    res = await select_game(update, context, organizer=True, action="avoid")
    if not res:
        return
    code, game = res
    game["avoid_previous"] = enable
    manager.save()
    await update.message.reply_text(f"✅ Избегание для {code}: {'вкл' if enable else 'выкл'}")


async def cmd_import_previous(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = await select_game(update, context, organizer=True, action="import_prev")
    if not res:
        return
    code, game = res
    if context.args and not (context.args[0].upper() == code and len(context.args) == 1):
        pairs = context.args[1:] if context.args[0].upper() == code else context.args
        added = 0
        for p in pairs:
            if ":" in p:
                a, b = p.split(":", 1)
                a, b = a.lower().lstrip("@"), b.lower().lstrip("@")
                if a and b:
                    game.setdefault("forbidden_pairs", set()).add((a, b))
                    added += 1
        manager.save()
        await update.message.reply_text(f"✅ Добавлено {added} пар.")
        return
    context.user_data["awaiting"] = {"type": "import_pairs", "code": code}
    await update.message.reply_text(PROMPTS["import_pairs"])


async def cmd_import_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/import_from OLDCODE")
        return
    old = context.args[-1].upper()
    if old not in manager.games or not manager.games[old].get("assignments"):
        await update.message.reply_text("Старая игра не найдена или без розыгрыша")
        return
    res = await select_game(update, context, organizer=True, action="import_from")
    if not res:
        return
    code, game = res
    old_g = manager.games[old]
    for g_id, r_id in old_g["assignments"].items():
        gk = get_key(g_id, old_g["participants"])
        rk = get_key(r_id, old_g["participants"])
        game.setdefault("forbidden_pairs", set()).add((gk, rk))
    manager.save()
    await update.message.reply_text(f"✅ Импортировано из {old}. Всего {len(game.get('forbidden_pairs', set()))} пар")


async def cmd_myresult(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_pending(update, context)
    uid = update.effective_user.id
    has = any(
        g.get("assignments") and uid in g["participants"] and not g["participants"][uid].get("notified")
        for g in manager.games.values()
    )
    if not has:
        await update.message.reply_text("Нет неполученных результатов")


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from pathlib import Path
    VERSION = Path("VERSION").read_text(encoding="utf-8").strip() if Path("VERSION").exists() else "unknown"
    up = int(time.time() - START_TIME)
    h, m = divmod(up // 60, 60)
    s = up % 60
    active = sum(1 for g in manager.games.values() if not g.get("closed"))
    total_p = sum(len(g["participants"]) for g in manager.games.values())
    await update.message.reply_text(
        f"ℹ️ v{VERSION}\n"
        f"Uptime: {h}ч {m}м {s}с\n"
        f"Активных: {active} / Всего: {len(manager.games)}\n"
        f"Участников: {total_p}\n"
        f"github.com/CrazyBulba/PSLAB_SecretSanta"
    )


# ─── Callbacks ───

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if ":" not in data:
        return
    action, code = data.split(":", 1)
    uid = query.from_user.id

    if action == "close" and code == "ALL":
        games = manager.user_games(uid, organizer=True, active_only=True)
        count = len(games)
        for c, _ in games:
            manager.delete(c)
        await query.edit_message_text(f"✅ Удалено игр: {count}")
        return

    if code not in manager.games:
        await query.edit_message_text("Игра не найдена")
        return
    game = manager.games[code]

    if action == "info":
        text = build_game_info(code, game, uid)
        buttons = []
        if game.get("organizer") == uid:
            buttons.append([
                InlineKeyboardButton("🎲 Розыгрыш", callback_data=f"draw:{code}"),
                InlineKeyboardButton("👥 Уч", callback_data=f"participants:{code}"),
            ])
            buttons.append([
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit:{code}"),
                InlineKeyboardButton("🗑 Удалить", callback_data=f"close:{code}"),
            ])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)
        return

    if action == "edit":
        if game.get("organizer") != uid:
            await query.edit_message_text("Только организатор")
            return
        text = f"✏️ Редактирование игры {code}\n\nВыберите, что изменить:"
        await query.edit_message_text(text, reply_markup=build_edit_keyboard(code))
        return

    if action == "edit_intro":
        if game.get("organizer") != uid:
            await query.edit_message_text("Нет прав")
            return
        context.user_data["awaiting"] = {"type": "intro", "code": code}
        await query.edit_message_text(PROMPTS["intro"])
        return

    if action == "edit_amount":
        if game.get("organizer") != uid:
            await query.edit_message_text("Нет прав")
            return
        context.user_data["awaiting"] = {"type": "amount", "code": code}
        await query.edit_message_text(PROMPTS["amount"])
        return

    if action == "toggle_avoid":
        if game.get("organizer") != uid:
            await query.edit_message_text("Нет прав")
            return
        game["avoid_previous"] = not game.get("avoid_previous", False)
        manager.save()
        status = "вкл" if game["avoid_previous"] else "выкл"
        await query.edit_message_text(
            f"✅ Избегание: {status}\n\nВернуться в меню?",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data=f"info:{code}")]]),
        )
        return

    if action == "draw":
        if game.get("organizer") != uid:
            await query.edit_message_text("Нет прав")
            return
        parts = list(game["participants"].keys())
        if len(parts) < 2:
            await query.edit_message_text("≥2 участника")
            return
        forbidden = game.get("forbidden_pairs") if game.get("avoid_previous") else None
        game["assignments"] = derangement(parts, forbidden, game["participants"])
        for u in parts:
            game["participants"][u]["notified"] = False
        manager.save()
        ok = sum(1 for u in parts if await send_result(context.bot, u, code, game))
        await query.edit_message_text(f"✅ Розыгрыш {code}! {ok}/{len(parts)}")
        return

    if action == "close":
        if game.get("organizer") != uid:
            await query.edit_message_text("Нет прав")
            return
        manager.delete(code)
        await query.edit_message_text(f"✅ Игра {code} удалена")
        return

    if action == "participants":
        if game.get("organizer") != uid:
            await query.edit_message_text("Только орг")
            return
        lines = [f"{code} ({len(game['participants'])}):"]
        for _, info in game["participants"].items():
            lines.append(f"• {info['name']} — {info['wishlist'] or '—'}")
        await query.edit_message_text("\n".join(lines))
        return

    if action == "setwish_select":
        context.user_data["awaiting"] = {"type": "wish", "code": code}
        await query.edit_message_text(PROMPTS["wish"])
        return

    if action == "setintro_select":
        context.user_data["awaiting"] = {"type": "intro", "code": code}
        await query.edit_message_text(PROMPTS["intro"])
        return

    if action == "setamount":
        context.user_data["awaiting"] = {"type": "amount", "code": code}
        await query.edit_message_text(PROMPTS["amount"])
        return

    if action == "export":
        if game.get("organizer") != uid or not game.get("assignments"):
            await query.edit_message_text("Недоступно")
            return
        lines = []
        for g_id, r_id in game["assignments"].items():
            gk = get_key(g_id, game["participants"])
            rk = get_key(r_id, game["participants"])
            if not gk.startswith("id:") and not rk.startswith("id:"):
                lines.append(f"@{gk}:@{rk}")
        if lines:
            text = " ".join(lines)
            await query.edit_message_text(f"📤 {code}\n\n`/import_previous {text}`\n\n{text}", parse_mode="Markdown")
        else:
            await query.edit_message_text("Нет пар с username")
        return


async def private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await handle_awaiting(update, context):
        return
    await check_pending(update, context)


async def setup(app):
    cmds = [
        BotCommand("start", "Помощь"),
        BotCommand("create", "Создать игру"),
        BotCommand("setintro", "Вступительное"),
        BotCommand("setamount", "Сумма на подарок"),
        BotCommand("join", "Вступить"),
        BotCommand("mygames", "Мои игры"),
        BotCommand("setwish", "Пожелания"),
        BotCommand("participants", "Участники"),
        BotCommand("draw", "Розыгрыш"),
        BotCommand("export", "Экспорт"),
        BotCommand("close", "Удалить игру"),
        BotCommand("avoid", "Избегать прошлые"),
        BotCommand("import_previous", "Загрузить пары"),
        BotCommand("import_from", "Импорт из игры"),
        BotCommand("myresult", "Мой результат"),
        BotCommand("info", "Инфо"),
    ]
    await app.bot.set_my_commands(cmds)
