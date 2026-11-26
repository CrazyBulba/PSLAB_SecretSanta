"""
Secret Santa Telegram Bot — точка входа v1.13.0
Вся логика в модулях: messages, storage, handlers, utils.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from handlers import (
    start,
    cmd_create,
    cmd_setintro,
    cmd_setamount,
    cmd_join,
    cmd_mygames,
    cmd_setwish,
    cmd_participants,
    cmd_draw,
    cmd_export,
    cmd_close,
    cmd_avoid,
    cmd_import_previous,
    cmd_import_from,
    cmd_myresult,
    cmd_info,
    callback,
    private_message,
    setup,
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
VERSION = Path("VERSION").read_text(encoding="utf-8").strip() if Path("VERSION").exists() else "unknown"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    if not TOKEN:
        print("BOT_TOKEN missing")
        return
    app = Application.builder().token(TOKEN).build()
    handlers = [
        CommandHandler("start", start),
        CommandHandler("help", start),
        CommandHandler("create", cmd_create),
        CommandHandler("setintro", cmd_setintro),
        CommandHandler("setamount", cmd_setamount),
        CommandHandler("join", cmd_join),
        CommandHandler("mygames", cmd_mygames),
        CommandHandler("setwish", cmd_setwish),
        CommandHandler("participants", cmd_participants),
        CommandHandler("draw", cmd_draw),
        CommandHandler("export", cmd_export),
        CommandHandler("close", cmd_close),
        CommandHandler("avoid", cmd_avoid),
        CommandHandler("import_previous", cmd_import_previous),
        CommandHandler("import_from", cmd_import_from),
        CommandHandler("myresult", cmd_myresult),
        CommandHandler("info", cmd_info),
        CallbackQueryHandler(callback),
        MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, private_message),
    ]
    for h in handlers:
        app.add_handler(h)
    app.post_init = setup
    logger.info(f"Bot v{VERSION} started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
