"""
Обработчики команд и callback-запросов.
"""

import logging
import time
import re
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

NOT_ENOUGH = "Недостаточно участников! Должно быть больше 1."


async def notify_participants(bot, game: dict, code: str, text: str, exclude: int = None):
    """Отправить уведомление всем участникам (кроме exclude)."""
    for uid in list(game["participants"].keys()):
        if uid == exclude:
            continue
        try:
            await bot.send_message(uid, text)
        except Exception:
            pass


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
        old = manager.games[code].get("intro", "")
        manager.games[code]["intro"] = text
        amount = extract_amount(text)
        if amount and not manager.games[code].get("gift_amount"):
            manager.games[code]["gift_amount"] = amount
        manager.save()
        await update.message.reply_text(f"✅ Вступительное для игры {code} сохранено!")
        if old != text:
            await notify_participants(
                context.bot,
                manager.games[code],
                code,
                f"📝 В игре {code} изменено вступительное слово:\n\n{text}",
                exclude=update.effective_user.id,
            )
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
        old = manager.games[code].get("gift_amount", "")
        manager.games[code]["gift_amount"] = text
        manager.save()
        await update.message.reply_text(f"✅ Сумма для {code}: {text}")
        if old != text:
            await notify_participants(
                context.bot,
                manager.games[code],
                code,
                f"💰 В игре {code} изменена сумма на подарок: {text}",
                exclude=update.effective_user.id,
            )
        return True

    if kind == "new_id" and code and code in manager.games:
        new_code = text.upper().strip()
        if not re.fullmatch(r"[A-Z0-9]{4,10}", new_code):
            await update.message.reply_text("❌ GameID должен состоять из 4–10 латинских букв и цифр.")
            return True
        if new_code in manager.games:
            await update.message.reply_text("❌ Такой GameID уже занят.")
            return True
        game = manager.games.pop(code)
        manager.games[new_code] = game
        manager.save()
        await update.message.reply_text(f"✅ GameID изменён: {code} → {new_code}")
        await notify_participants(
            context.bot,
            game,
            new_code,
            f"🆔 GameID игры изменён: {code} → {new_code}\nИспользуйте новый код для присоединения.",
            exclude=update.effective_user.id,
        )
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
    org = game.get("organizer")
    if org and org != update.effective_user.id:
        try:
            name = update.effective_user.full_name or update.effective_user.username or "Участник"
            await context.bot.send_message(org, f"✅ В игру {code} вступил: {name}")
        except Exception:
            pass


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


async def cmd_myresult(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_pending(update, context)
    uid = update.effective_user.id
    games = manager.user_games(uid, active_only=True)
    if not games:
        await update.message.reply_text("Нет активных игр.")
        return

    lines = ["🎁 Ваши результаты:"]
    has_any = False
    for code, game in games:
        if not game.get("assignments") or uid not in game["assignments"]:
            lines.append(f"\n🆔 {code}: розыгрыш ещё не проведён")
            continue
        has_any = True
        rec_id = game["assignments"][uid]
        rec = game["participants"].get(rec_id, {})
        rec_name = rec.get("name", "?")
        rec_un = f" @{rec['username']}" if rec.get("username") else ""
        wish = rec.get("wishlist", "").strip() or "-"
        lines.append(f"\n🆔 {code}")
        lines.append(f"Подопечный: {rec_name}{rec_un}")
        lines.append(f"Желает: {wish}")

    if not has_any and len(lines) == 1:
        lines.append("\nПока нет розыгрышей в ваших играх.")

    await update.message.reply_text("\n".join(lines))


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
    try:
        await query.answer()
    except Exception:
        pass
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
                InlineKeyboardButton("👥 Участники", callback_data=f"participants:{code}"),
            ])
            buttons.append([
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit:{code}"),
                InlineKeyboardButton("🗑 Удалить", callback_data=f"close:{code}"),
            ])
        else:
            buttons.append([
                InlineKeyboardButton("🎁 Мои пожелания", callback_data=f"setwish_select:{code}"),
                InlineKeyboardButton("🚪 Выйти из игры", callback_data=f"leave_confirm:{code}"),
            ])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)
        return

    if action == "leave_confirm":
        buttons = [
            [
                InlineKeyboardButton("✅ Да, выйти", callback_data=f"leave_yes:{code}"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"info:{code}"),
            ]
        ]
        await query.edit_message_text(
            f"Вы точно хотите выйти из игры {code}?",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if action == "leave_yes":
        if uid not in game["participants"]:
            await query.edit_message_text("Вы уже не в игре")
            return
        if game.get("organizer") == uid:
            await query.edit_message_text("Организатор не может выйти. Удалите игру или передайте права.")
            return
        name = game["participants"][uid].get("name", "Участник")
        del game["participants"][uid]
        if "assignments" in game:
            game["assignments"].pop(uid, None)
            for k in list(game["assignments"].keys()):
                if game["assignments"][k] == uid:
                    del game["assignments"][k]
        manager.save()
        await query.edit_message_text(f"✅ Вы вышли из игры {code}")
        org = game.get("organizer")
        if org:
            try:
                await context.bot.send_message(org, f"🚪 {name} вышел из игры {code}")
            except Exception:
                pass
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

    if action == "edit_id":
        if game.get("organizer") != uid:
            await query.edit_message_text("Нет прав")
            return
        context.user_data["awaiting"] = {"type": "new_id", "code": code}
        await query.edit_message_text(PROMPTS["new_id"])
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

    if action == "export":
        if game.get("organizer") != uid or not game.get("assignments"):
            await query.edit_message_text("Нет розыгрыша или нет прав")
            return
        lines = []
        for g_id, r_id in game["assignments"].items():
            gk = get_key(g_id, game["participants"])
            rk = get_key(r_id, game["participants"])
            if not gk.startswith("id:") and not rk.startswith("id:"):
                lines.append(f"@{gk}:@{rk}")
        if lines:
            text = " ".join(lines)
            await query.edit_message_text(f"📤 Экспорт {code}\n\n{text}", parse_mode="Markdown")
        else:
            await query.edit_message_text("Нет пар с username")
        return

    if action == "import_prev":
        if game.get("organizer") != uid:
            await query.edit_message_text("Нет прав")
            return
        context.user_data["awaiting"] = {"type": "import_pairs", "code": code}
        await query.edit_message_text(PROMPTS["import_pairs"])
        return

    if action == "draw":
        if game.get("organizer") != uid:
            await query.edit_message_text("Нет прав")
            return
        parts = list(game["participants"].keys())
        if len(parts) < 2:
            await query.edit_message_text(NOT_ENOUGH)
            return
        try:
            forbidden = game.get("forbidden_pairs") if game.get("avoid_previous") else None
            game["assignments"] = derangement(parts, forbidden, game["participants"])
            for u in parts:
                game["participants"][u]["notified"] = False
            manager.save()
            ok = 0
            for u in parts:
                if await send_result(context.bot, u, code, game):
                    ok += 1
            result_text = f"✅ Розыгрыш {code}! Отправлено {ok}/{len(parts)}"
            if game.get("avoid_previous"):
                result_text += "\n🛡 Учтены запрещённые пары"
            await query.edit_message_text(result_text)
            await notify_participants(
                context.bot,
                game,
                code,
                f"🎲 В игре {code} проведён розыгрыш! Проверьте личные сообщения.",
                exclude=uid,
            )
        except Exception as e:
            logger.error(f"Draw error for {code}: {e}")
            try:
                await query.edit_message_text(f"❌ Ошибка при розыгрыше: {e}")
            except Exception:
                pass
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
        lines = [f"Участники {code} ({len(game['participants'])}):"]
        for _, info in game["participants"].items():
            un = f" @{info['username']}" if info.get("username") else ""
            lines.append(f"• {info['name']}{un}")
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


async def private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await handle_awaiting(update, context):
        return
    await check_pending(update, context)


async def setup(app):
    cmds = [
        BotCommand("start", "Помощь"),
        BotCommand("help", "Помощь"),
        BotCommand("create", "Создать игру"),
        BotCommand("join", "Вступить"),
        BotCommand("mygames", "Мои игры"),
        BotCommand("myresult", "Мой результат"),
        BotCommand("info", "Инфо"),
    ]
    await app.bot.set_my_commands(cmds)
