"""
Secret Santa Telegram Bot — v1.12.2
Упрощённое сообщение после создания игры.
"""

import json
import logging
import os
import random
import re
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
DATA_DIR = Path(os.getenv("DATA_DIR", "/data" if Path("/data").exists() else "."))
DATA_FILE = DATA_DIR / "games.json"
VERSION = Path("VERSION").read_text(encoding="utf-8").strip() if Path("VERSION").exists() else "unknown"
START_TIME = time.time()

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


class GameManager:
    def __init__(self):
        self.games: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self):
        if not DATA_FILE.exists():
            return
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            for code, g in raw.items():
                if g.get("closed"):
                    continue
                g["participants"] = {int(k): v for k, v in g.get("participants", {}).items()}
                if "assignments" in g:
                    g["assignments"] = {int(k): int(v) for k, v in g["assignments"].items()}
                g["forbidden_pairs"] = {tuple(p) for p in g.get("forbidden_pairs", [])}
                g.setdefault("avoid_previous", False)
                g.setdefault("intro", "")
                g.setdefault("gift_amount", "")
                self.games[code] = g
            logger.info(f"Загружено {len(self.games)} игр")
        except Exception as e:
            logger.error(f"Load error: {e}")

    def save(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            out = {}
            for code, g in self.games.items():
                d = dict(g)
                d["participants"] = {str(k): v for k, v in g["participants"].items()}
                if "assignments" in g:
                    d["assignments"] = {str(k): v for k, v in g["assignments"].items()}
                d["forbidden_pairs"] = [list(p) for p in g.get("forbidden_pairs", set())]
                out[code] = d
            DATA_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Save error: {e}")

    def delete(self, code: str):
        if code in self.games:
            del self.games[code]
            self.save()

    def user_games(self, user_id: int, organizer: bool = False, active_only: bool = False) -> List[Tuple[str, Dict]]:
        res = []
        for code, g in self.games.items():
            if active_only and g.get("closed"):
                continue
            if organizer and g.get("organizer") == user_id:
                res.append((code, g))
            elif not organizer and user_id in g.get("participants", {}):
                res.append((code, g))
        return res

    def create(self, user, intro: str = "", gift_amount: str = "") -> str:
        code = uuid.uuid4().hex[:6].upper()
        self.games[code] = {
            "organizer": user.id,
            "participants": {
                user.id: {
                    "name": user.full_name or user.username or "Участник",
                    "wishlist": "",
                    "username": user.username,
                    "notified": False,
                }
            },
            "closed": False,
            "assignments": {},
            "avoid_previous": False,
            "forbidden_pairs": set(),
            "intro": intro,
            "gift_amount": gift_amount,
        }
        self.save()
        return code

    def join(self, code: str, user) -> Optional[str]:
        g = self.games.get(code)
        if not g:
            return "Игра не найдена"
        if g.get("closed"):
            return "Игра закрыта"
        if user.id in g["participants"]:
            return "Вы уже в игре"
        g["participants"][user.id] = {
            "name": user.full_name or user.username or "Участник",
            "wishlist": "",
            "username": user.username,
            "notified": False,
        }
        self.save()
        return None


manager = GameManager()


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


async def select_game(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    organizer: bool = False,
    active: bool = True,
    action: str = "info",
    include_all: bool = False,
) -> Optional[Tuple[str, Dict]]:
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


# ─── Conversational state ───

PROMPTS = {
    "intro": "📝 Напишите вступительное слово.",
    "wish": "🎁 Напишите ваши пожелания к подарку.",
    "import_pairs": "🔗 Отправьте пары в формате:\n@user1:@user2 @user3:@user4",
    "amount": "💰 Укажите сумму на подарок (например: 3000 рублей или 50$)",
}


def create_success_message(code: str) -> str:
    return (
        f"✅ Игра создана!\n"
        f"GameID: {code}\n\n"
        f"Для присоединения к игре другим участникам необходимо отправить боту:\n"
        f"/join {code}"
    )


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


def build_game_info(code: str, game: dict, user_id: int) -> str:
    parts = game["participants"]
    is_org = game.get("organizer") == user_id
    my_info = parts.get(user_id, {})

    lines = []

    intro = game.get("intro", "").strip()
    if intro:
        lines.append(f"📝 {intro}")
    else:
        lines.append("📝 Вступительное не задано")

    amount = game.get("gift_amount") or extract_amount(intro)
    lines.append(f"💰 Сумма на подарок: {amount or '—'}")

    lines.append(f"🆔 ID: {code}")
    lines.append("")

    lines.append("── Участник ──")
    assignments = game.get("assignments", {})
    if user_id in assignments:
        rec_id = assignments[user_id]
        rec = parts.get(rec_id, {})
        rec_name = rec.get("name", "?")
        rec_un = f" @{rec['username']}" if rec.get("username") else ""
        lines.append(f"🎁 Подопечный: {rec_name}{rec_un}")
        wish = rec.get("wishlist", "").strip()
        if wish:
            lines.append(f"💬 Подопечный желает: {wish}")
    else:
        lines.append("🎁 Подопечный: —")

    my_wish = my_info.get("wishlist", "").strip()
    lines.append(f"✨ Мое желание: {my_wish or '—'}")
    lines.append(f"👥 Участников: {len(parts)}")

    if is_org:
        lines.append("")
        lines.append("── Организатор ──")
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
            InlineKeyboardButton("🛡 Избегать on/off", callback_data=f"toggle_avoid:{code}"),
            InlineKeyboardButton("← Назад", callback_data=f"info:{code}"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


# ─── Commands ───

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting", None)
    await check_pending(update, context)
    await update.message.reply_text(
        "🎅 Secret Santa Bot\n\n"
        "/create — создать игру\n"
        "/setintro — вступительное\n"
        "/setamount — сумма на подарок\n"
        "/join CODE — вступить\n"
        "/mygames — мои игры\n"
        "/setwish — пожелания\n"
        "/participants — участники\n"
        "/draw — розыгрыш\n"
        "/export — экспорт пар\n"
        "/close [all] — удалить\n"
        "/avoid on|off\n"
        "/import_previous\n"
        "/import_from OLDCODE\n"
        "/myresult\n"
        "/info"
    )


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
    msg = f"✅ Вы в игре {code}!"
    if game.get("intro"):
        msg += f"\n\n📝 {game['intro']}"
    await update.message.reply_text(msg)


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
        await query.edit_message_text(f"✅ Избегание: {status}\n\nВернуться в меню?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data=f"info:{code}")]]))
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


async def setup(app: Application):
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
