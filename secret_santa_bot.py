"""
Бот для Тайного Санты (Secret Santa) в Telegram.
Поддержка нескольких игр, инлайн-меню выбора, повторного розыгрыша и сохранения состояния.
"""

import json
import logging
import os
import random
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

DATA_DIR = Path(os.getenv("DATA_DIR", "/data" if Path("/data").exists() else "."))
DATA_FILE = DATA_DIR / "games.json"

VERSION_FILE = Path("VERSION")
def get_version() -> str:
    try:
        if VERSION_FILE.exists():
            return VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return "unknown"

BOT_VERSION = get_version()
START_TIME = time.time()

games: Dict[str, Dict[str, Any]] = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def load_games() -> None:
    global games
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            games = {}
            for code, game in raw.items():
                game["participants"] = {
                    int(uid): info for uid, info in game.get("participants", {}).items()
                }
                if "assignments" in game:
                    game["assignments"] = {
                        int(k): int(v) for k, v in game["assignments"].items()
                    }
                games[code] = game
            logger.info(f"Загружено игр: {len(games)}")
        except Exception as e:
            logger.error(f"Ошибка загрузки игр: {e}")
            games = {}
    else:
        logger.info("Файл с играми не найден, начинаем с пустого хранилища")
        games = {}


def save_games() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        to_save = {}
        for code, game in games.items():
            g = dict(game)
            g["participants"] = {str(uid): info for uid, info in game.get("participants", {}).items()}
            if "assignments" in game:
                g["assignments"] = {str(k): v for k, v in game["assignments"].items()}
            to_save[code] = g
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)
        logger.debug("Игры сохранены")
    except Exception as e:
        logger.error(f"Ошибка сохранения игр: {e}")


def get_user_games(user_id: int, as_organizer: bool = False, only_active: bool = False) -> List[Tuple[str, Dict]]:
    result = []
    for code, game in games.items():
        if only_active and game.get("closed"):
            continue
        if as_organizer:
            if game.get("organizer") == user_id:
                result.append((code, game))
        else:
            if user_id in game.get("participants", {}):
                result.append((code, game))
    return result


def build_game_keyboard(user_games: List[Tuple[str, Dict]], action: str, include_all: bool = False) -> InlineKeyboardMarkup:
    """Создаёт инлайн-клавиатуру для выбора игры."""
    buttons = []
    for code, game in user_games:
        status = "❌" if game.get("closed") else "✅"
        parts = len(game.get("participants", {}))
        text = f"{status} {code} ({parts} чел.)"
        buttons.append([InlineKeyboardButton(text, callback_data=f"{action}:{code}")])

    if include_all and len(user_games) > 1:
        buttons.append([InlineKeyboardButton("🔒 Закрыть все", callback_data=f"{action}:ALL")])

    return InlineKeyboardMarkup(buttons)


def make_derangement(items: list) -> dict:
    if len(items) < 2:
        return {}
    receivers = items[:]
    while True:
        random.shuffle(receivers)
        if all(a != b for a, b in zip(items, receivers)):
            break
    return dict(zip(items, receivers))


async def send_assignment(bot, user_id: int, code: str, game: dict) -> bool:
    if user_id not in game["assignments"]:
        return False

    receiver_id = game["assignments"][user_id]
    receiver = game["participants"].get(receiver_id)
    if not receiver:
        return False

    name = receiver["name"]
    wish = receiver["wishlist"] or "Пожеланий нет"
    username = f"@{receiver['username']}" if receiver.get("username") else ""

    text = (
        f"🎁 Тайный Санта!\n\n"
        f"Вы дарите подарок: {name} {username}\n\n"
        f"Пожелания:\n{wish}\n\n"
        f"Код игры: {code}"
    )

    try:
        await bot.send_message(chat_id=user_id, text=text)
        game["participants"][user_id]["notified"] = True
        save_games()
        logger.info(f"Результат отправлен пользователю {user_id} (игра {code})")
        return True
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение {user_id}: {e}")
        game["participants"][user_id]["notified"] = False
        save_games()
        return False


async def check_and_send_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    bot = context.bot
    sent_any = False

    for code, game in games.items():
        if game.get("assignments") and user_id in game.get("participants", {}):
            if not game["participants"][user_id].get("notified", False):
                if await send_assignment(bot, user_id, code, game):
                    sent_any = True

    if sent_any and update.message:
        await update.message.reply_text("✅ Я отправил тебе результат розыгрыша!")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await check_and_send_pending(update, context)

    text = (
        "🎅 Привет! Это бот для организации Тайного Санты.\n\n"
        "Команды:\n"
        "/create — создать новую игру\n"
        "/join КОД — присоединиться к игре\n"
        "/mygames — список ваших игр (с кнопками)\n"
        "/setwish [КОД] текст — указать пожелания\n"
        "/participants [КОД] — список участников\n"
        "/draw [КОД] — розыгрыш (организатор)\n"
        "/close [КОД|all] — закрыть игру или все игры (организатор)\n"
        "/myresult — получить свой результат\n"
        "/info — информация о боте\n"
        "/help — помощь\n\n"
        "Если игр несколько — появится меню с кнопками."
    )
    await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uptime_sec = int(time.time() - START_TIME)
    hours, rem = divmod(uptime_sec, 3600)
    minutes, seconds = divmod(rem, 60)
    uptime_str = f"{hours}ч {minutes}м {seconds}с"

    active_games = sum(1 for g in games.values() if not g.get("closed"))
    total_participants = sum(len(g.get("participants", {})) for g in games.values())

    text = (
        f"ℹ️ Информация о боте\n\n"
        f"Версия: {BOT_VERSION}\n"
        f"Время работы: {uptime_str}\n"
        f"Активных игр: {active_games}\n"
        f"Всего игр: {len(games)}\n"
        f"Всего участников: {total_participants}\n\n"
        f"Репозиторий: github.com/CrazyBulba/PSLAB_SecretSanta"
    )
    await update.message.reply_text(text)


async def mygames(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_games = get_user_games(user_id)

    if not user_games:
        await update.message.reply_text("Вы не участвуете ни в одной игре.\nСоздайте новую: /create")
        return

    keyboard = build_game_keyboard(user_games, "info")
    await update.message.reply_text("Ваши игры. Выберите для подробностей:", reply_markup=keyboard)


async def show_game_info(code: str, game: dict, user_id: int) -> str:
    role = "организатор" if game.get("organizer") == user_id else "участник"
    status = "закрыта" if game.get("closed") else "активна"
    parts = len(game.get("participants", {}))
    drawn = "Да" if game.get("assignments") else "Нет"
    return (
        f"Игра: {code}\n"
        f"Статус: {status}\n"
        f"Ваша роль: {role}\n"
        f"Участников: {parts}\n"
        f"Розыгрыш был: {drawn}"
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    if ":" not in data:
        return

    action, code = data.split(":", 1)
    user_id = query.from_user.id

    if action == "close" and code == "ALL":
        user_games = get_user_games(user_id, as_organizer=True, only_active=True)
        if not user_games:
            await query.edit_message_text("Нет активных игр для закрытия.")
            return
        closed_count = 0
        for c, g in user_games:
            g["closed"] = True
            closed_count += 1
        save_games()
        await query.edit_message_text(f"✅ Закрыто игр: {closed_count}")
        return

    if code not in games:
        await query.edit_message_text("❌ Игра больше не существует.")
        return

    game = games[code]

    if action == "info":
        text = await show_game_info(code, game, user_id)
        buttons = []
        if game.get("organizer") == user_id and not game.get("closed"):
            buttons.append([
                InlineKeyboardButton("🎲 Розыгрыш", callback_data=f"draw:{code}"),
                InlineKeyboardButton("👥 Участники", callback_data=f"participants:{code}"),
            ])
            buttons.append([InlineKeyboardButton("🔒 Закрыть игру", callback_data=f"close:{code}")])
        if buttons:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await query.edit_message_text(text)
        return

    if action == "setwish_select":
        wish = context.user_data.get("pending_wish")
        if not wish:
            await query.edit_message_text("❌ Нет сохранённых пожеланий. Попробуйте снова /setwish")
            return
        if user_id not in game.get("participants", {}):
            await query.edit_message_text("❌ Вы не участник этой игры.")
            return
        game["participants"][user_id]["wishlist"] = wish
        save_games()
        context.user_data.pop("pending_wish", None)
        await query.edit_message_text(f"✅ Пожелания сохранены для игры {code}!")
        return

    if action == "draw":
        if game.get("organizer") != user_id or game.get("closed"):
            await query.edit_message_text("❌ Нет прав на розыгрыш этой игры.")
            return
        participants = list(game["participants"].keys())
        if len(participants) < 2:
            await query.edit_message_text("Нужно минимум 2 участника.")
            return
        assignments = make_derangement(participants)
        game["assignments"] = assignments
        for uid in participants:
            game["participants"][uid]["notified"] = False
        save_games()

        bot = context.bot
        success = 0
        for giver_id in participants:
            if await send_assignment(bot, giver_id, code, game):
                success += 1

        await query.edit_message_text(
            f"✅ Розыгрыш игры {code} проведён!\n"
            f"Уведомления отправлены {success} из {len(participants)} участникам."
        )
        return

    if action == "close":
        if game.get("organizer") != user_id or game.get("closed"):
            await query.edit_message_text("❌ Нельзя закрыть эту игру.")
            return
        game["closed"] = True
        save_games()
        await query.edit_message_text(f"✅ Игра {code} закрыта.")
        return

    if action == "participants":
        if game.get("organizer") != user_id:
            await query.edit_message_text("❌ Только организатор может смотреть участников.")
            return
        parts = game["participants"]
        lines = [f"Участники игры {code} ({len(parts)} чел.):"]
        for uid, info in parts.items():
            name = info["name"]
            wish = info["wishlist"] or "—"
            lines.append(f"• {name} — {wish}")
        await query.edit_message_text("\n".join(lines))


async def myresult(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await check_and_send_pending(update, context)
    user_id = update.effective_user.id
    has_pending = False
    for game in games.values():
        if game.get("assignments") and user_id in game.get("participants", {}):
            if not game["participants"][user_id].get("notified", False):
                has_pending = True
                break
    if not has_pending:
        await update.message.reply_text("У тебя нет неполученных результатов розыгрыша.")


async def create_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    game_code = uuid.uuid4().hex[:6].upper()
    games[game_code] = {
        "organizer": user.id,
        "participants": {},
        "closed": False,
        "assignments": {},
    }
    games[game_code]["participants"][user.id] = {
        "name": user.full_name or user.username or "Участник",
        "wishlist": "",
        "username": user.username,
        "notified": False,
    }
    save_games()
    await update.message.reply_text(
        f"✅ Игра создана!\n\n"
        f"Код игры: {game_code}\n\n"
        f"Отправьте друзьям: /join {game_code}"
    )


async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /join КОД")
        return

    code = context.args[0].upper()
    if code not in games:
        await update.message.reply_text("❌ Игра с таким кодом не найдена.")
        return

    game = games[code]
    if game["closed"]:
        await update.message.reply_text("❌ Игра закрыта, присоединиться нельзя.")
        return

    user = update.effective_user
    if user.id in game["participants"]:
        await update.message.reply_text("Вы уже в этой игре.")
        return

    game["participants"][user.id] = {
        "name": user.full_name or user.username or "Участник",
        "wishlist": "",
        "username": user.username,
        "notified": False,
    }
    save_games()
    await update.message.reply_text(f"✅ Вы присоединились к игре {code}!")


async def set_wish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /setwish [КОД] Ваши пожелания")
        return

    user_id = update.effective_user.id
    args = context.args
    possible_code = args[0].upper()
    code = None
    wish_parts = args

    if possible_code in games and user_id in games[possible_code].get("participants", {}):
        code = possible_code
        wish_parts = args[1:]

    if not wish_parts:
        await update.message.reply_text("Укажите текст пожеланий.")
        return

    wish = " ".join(wish_parts)
    user_games = get_user_games(user_id, only_active=True)

    if code:
        game = next((g for c, g in user_games if c == code), None)
        if not game:
            await update.message.reply_text("❌ Игра не найдена.")
            return
    elif len(user_games) == 1:
        code, game = user_games[0]
    else:
        keyboard = build_game_keyboard(user_games, "setwish_select")
        context.user_data["pending_wish"] = wish
        await update.message.reply_text("Выберите игру для пожеланий:", reply_markup=keyboard)
        return

    game["participants"][user_id]["wishlist"] = wish
    save_games()
    await update.message.reply_text(f"✅ Пожелания сохранены для игры {code}!")


async def list_participants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    code = context.args[0].upper() if context.args else None
    user_games = get_user_games(user_id, as_organizer=True, only_active=True)

    if not user_games:
        await update.message.reply_text("У вас нет активных игр как организатора.")
        return

    if code:
        game = next((g for c, g in user_games if c == code), None)
        if not game:
            await update.message.reply_text("❌ Игра не найдена.")
            return
    elif len(user_games) == 1:
        code, game = user_games[0]
    else:
        keyboard = build_game_keyboard(user_games, "participants")
        await update.message.reply_text("Выберите игру:", reply_markup=keyboard)
        return

    parts = game["participants"]
    lines = [f"Участники игры {code} ({len(parts)} чел.):"]
    for uid, info in parts.items():
        name = info["name"]
        wish = info["wishlist"] or "—"
        lines.append(f"• {name} — {wish}")
    await update.message.reply_text("\n".join(lines))


async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    code = context.args[0].upper() if context.args else None
    user_games = get_user_games(user_id, as_organizer=True, only_active=True)

    if not user_games:
        await update.message.reply_text("У вас нет активных игр для розыгрыша.")
        return

    if code:
        game = next((g for c, g in user_games if c == code), None)
        if not game:
            await update.message.reply_text("❌ Игра не найдена.")
            return
    elif len(user_games) == 1:
        code, game = user_games[0]
    else:
        keyboard = build_game_keyboard(user_games, "draw")
        await update.message.reply_text("Выберите игру для розыгрыша:", reply_markup=keyboard)
        return

    participants = list(game["participants"].keys())
    if len(participants) < 2:
        await update.message.reply_text("Нужно минимум 2 участника.")
        return

    assignments = make_derangement(participants)
    game["assignments"] = assignments
    for uid in participants:
        game["participants"][uid]["notified"] = False
    save_games()

    bot = context.bot
    success = 0
    failed_names = []
    for giver_id in participants:
        if await send_assignment(bot, giver_id, code, game):
            success += 1
        else:
            failed_names.append(game["participants"][giver_id]["name"])

    reply = f"✅ Розыгрыш игры {code} проведён!\nУведомления отправлены {success} из {len(participants)} участникам."
    if failed_names:
        reply += "\n\n⚠️ Не удалось отправить:\n" + "\n".join(f"• {n}" for n in failed_names)
    await update.message.reply_text(reply)


async def close_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    arg = context.args[0].upper() if context.args else None
    user_games = get_user_games(user_id, as_organizer=True, only_active=True)

    if not user_games:
        await update.message.reply_text("У вас нет активных игр для закрытия.")
        return

    if arg in ("ALL", "ВСЕ", "ЗАКРЫТЬВСЕ"):
        closed_count = 0
        for c, g in user_games:
            g["closed"] = True
            closed_count += 1
        save_games()
        await update.message.reply_text(f"✅ Закрыто игр: {closed_count}")
        return

    code = arg
    if code:
        game = next((g for c, g in user_games if c == code), None)
        if not game:
            await update.message.reply_text("❌ Игра не найдена.")
            return
    elif len(user_games) == 1:
        code, game = user_games[0]
    else:
        keyboard = build_game_keyboard(user_games, "close", include_all=True)
        await update.message.reply_text("Выберите игру для закрытия:", reply_markup=keyboard)
        return

    game["closed"] = True
    save_games()
    await update.message.reply_text(f"✅ Игра {code} закрыта.")


async def setup_bot_commands(application: Application) -> None:
    """Регистрирует команды бота для меню в Telegram."""
    commands = [
        BotCommand("start", "Приветствие и помощь"),
        BotCommand("create", "Создать новую игру"),
        BotCommand("join", "Присоединиться к игре"),
        BotCommand("mygames", "Мои игры"),
        BotCommand("setwish", "Указать пожелания"),
        BotCommand("participants", "Список участников"),
        BotCommand("draw", "Провести розыгрыш"),
        BotCommand("close", "Закрыть игру"),
        BotCommand("myresult", "Получить результат"),
        BotCommand("info", "Информация о боте"),
        BotCommand("help", "Помощь"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Меню команд зарегистрировано")


def main() -> None:
    if not TOKEN:
        print("Ошибка: установите BOT_TOKEN в .env файле")
        return

    load_games()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("mygames", mygames))
    application.add_handler(CommandHandler("create", create_game))
    application.add_handler(CommandHandler("join", join_game))
    application.add_handler(CommandHandler("setwish", set_wish))
    application.add_handler(CommandHandler("participants", list_participants))
    application.add_handler(CommandHandler("draw", draw))
    application.add_handler(CommandHandler("close", close_game))
    application.add_handler(CommandHandler("myresult", myresult))
    application.add_handler(CallbackQueryHandler(callback_handler))

    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, check_and_send_pending)
    )

    # Регистрируем меню команд при запуске
    application.post_init = setup_bot_commands

    logger.info(f"Бот запущен... Версия {BOT_VERSION}")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
