"""
Бот для Тайного Санты (Secret Santa) в Telegram.
С возможностью повторного розыгрыша, закрытием игры и сохранением состояния между перезапусками.
"""

import json
import logging
import os
import random
import time
import uuid
from pathlib import Path
from typing import Dict, Any

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Путь к файлу с данными. На Railway при монтировании Volume в /data используйте /data/games.json
DATA_DIR = Path(os.getenv("DATA_DIR", "/data" if Path("/data").exists() else "."))
DATA_FILE = DATA_DIR / "games.json"

# Версия из файла VERSION (контроль версий в Git)
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

# Хранилище игр
games: Dict[str, Dict[str, Any]] = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def load_games() -> None:
    """Загружает игры из файла."""
    global games
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # JSON сохраняет ключи как строки — преобразуем user_id обратно в int
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
    """Сохраняет игры в файл."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Преобразуем int-ключи в строки для JSON
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


def make_derangement(items: list) -> dict:
    """Создаёт случайное распределение без фиксированных точек (никто не получает себя)."""
    if len(items) < 2:
        return {}
    receivers = items[:]
    while True:
        random.shuffle(receivers)
        if all(a != b for a, b in zip(items, receivers)):
            break
    return dict(zip(items, receivers))


async def send_assignment(bot, user_id: int, code: str, game: dict) -> bool:
    """Пытается отправить результат конкретному участнику. Возвращает True при успехе."""
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
    """Проверяет, есть ли у пользователя неполученные результаты, и отправляет их."""
    user_id = update.effective_user.id
    bot = context.bot
    sent_any = False

    for code, game in games.items():
        if game.get("assignments") and user_id in game.get("participants", {}):
            if not game["participants"][user_id].get("notified", False):
                if await send_assignment(bot, user_id, code, game):
                    sent_any = True

    if sent_any:
        await update.message.reply_text("✅ Я отправил тебе результат розыгрыша!")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приветствие + проверка неотправленных результатов."""
    await check_and_send_pending(update, context)

    text = (
        "🎅 Привет! Это бот для организации Тайного Санты.\n\n"
        "Команды:\n"
        "/create — создать новую игру\n"
        "/join КОД — присоединиться к игре\n"
        "/setwish текст — указать свои пожелания\n"
        "/participants — список участников (для организатора)\n"
        "/draw — провести / перекрутить розыгрыш (организатор)\n"
        "/close — закрыть игру (организатор)\n"
        "/myresult — получить свой результат (если ещё не получил)\n"
        "/info — информация о боте и версии\n"
        "/help — помощь\n\n"
        "Важно: чтобы получить результат, нужно хотя бы раз написать боту в личку."
    )
    await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать информацию о боте, версию и статистику."""
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
        f"Данные сохраняются в games.json\n"
        f"Репозиторий: github.com/CrazyBulba/PSLAB_SecretSanta"
    )
    await update.message.reply_text(text)


async def myresult(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Принудительно проверить и отправить результат."""
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
    """Создать новую игру."""
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
        f"Отправьте друзьям: /join {game_code}\n\n"
        f"Участники должны написать боту /start в личку, чтобы получить результат."
    )


async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Присоединиться к игре по коду."""
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
    await update.message.reply_text(
        f"✅ Вы присоединились к игре {code}!\n"
        f"Не забудьте указать пожелания: /setwish Ваши пожелания\n\n"
        f"Результат розыгрыша придёт сюда в личку после /draw."
    )


async def set_wish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Установить список пожеланий."""
    if not context.args:
        await update.message.reply_text("Использование: /setwish Ваши пожелания к подарку")
        return

    wish = " ".join(context.args)
    user_id = update.effective_user.id
    found = False

    for code, game in games.items():
        if user_id in game["participants"] and not game["closed"]:
            game["participants"][user_id]["wishlist"] = wish
            save_games()
            await update.message.reply_text("✅ Пожелания сохранены!")
            found = True
            break

    if not found:
        await update.message.reply_text("Вы не участвуете ни в одной активной игре.")


async def list_participants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать участников (для организатора)."""
    user_id = update.effective_user.id
    found = False

    for code, game in games.items():
        if game["organizer"] == user_id and not game["closed"]:
            parts = game["participants"]
            if not parts:
                await update.message.reply_text("Пока никого нет.")
                return
            lines = [f"Участники игры {code} ({len(parts)} чел.):"]
            for uid, info in parts.items():
                name = info["name"]
                wish = info["wishlist"] or "—"
                lines.append(f"• {name} — {wish}")
            await update.message.reply_text("\n".join(lines))
            found = True
            break

    if not found:
        await update.message.reply_text("У вас нет активных игр как организатора.")


async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Провести или перекрутить розыгрыш."""
    user_id = update.effective_user.id
    target_game = None
    code = None

    for c, game in games.items():
        if game["organizer"] == user_id and not game["closed"]:
            target_game = game
            code = c
            break

    if not target_game:
        await update.message.reply_text("У вас нет активной игры для розыгрыша.")
        return

    participants = list(target_game["participants"].keys())
    if len(participants) < 2:
        await update.message.reply_text("Нужно минимум 2 участника.")
        return

    assignments = make_derangement(participants)
    target_game["assignments"] = assignments

    # Сбрасываем флаги уведомлений
    for uid in participants:
        target_game["participants"][uid]["notified"] = False

    save_games()

    bot = context.bot
    success = 0
    failed_names = []

    for giver_id in participants:
        if await send_assignment(bot, giver_id, code, target_game):
            success += 1
        else:
            name = target_game["participants"][giver_id]["name"]
            failed_names.append(name)

    reply = (
        f"✅ Розыгрыш проведён!\n"
        f"Уведомления отправлены {success} из {len(participants)} участникам.\n"
        f"Игра остаётся открытой — можно перекрутить ещё раз командой /draw.\n"
        f"Закрыть игру: /close"
    )

    if failed_names:
        reply += (
            f"\n\n⚠️ Не удалось отправить:\n"
            + "\n".join(f"• {n}" for n in failed_names)
            + "\n\nОни получат результат автоматически, когда напишут боту в личку."
        )

    await update.message.reply_text(reply)


async def close_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Закрыть игру."""
    user_id = update.effective_user.id
    found = False

    for code, game in games.items():
        if game["organizer"] == user_id and not game["closed"]:
            game["closed"] = True
            save_games()
            await update.message.reply_text(
                f"✅ Игра {code} закрыта.\n"
                f"Больше нельзя присоединяться и крутить рулетку."
            )
            found = True
            break

    if not found:
        await update.message.reply_text("У вас нет активных игр для закрытия.")


def main() -> None:
    if not TOKEN:
        print("Ошибка: установите BOT_TOKEN в .env файле")
        return

    load_games()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("create", create_game))
    application.add_handler(CommandHandler("join", join_game))
    application.add_handler(CommandHandler("setwish", set_wish))
    application.add_handler(CommandHandler("participants", list_participants))
    application.add_handler(CommandHandler("draw", draw))
    application.add_handler(CommandHandler("close", close_game))
    application.add_handler(CommandHandler("myresult", myresult))

    # На любое личное сообщение проверяем, не нужно ли дослать результат
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, check_and_send_pending)
    )

    logger.info(f"Бот запущен... Версия {BOT_VERSION}")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
