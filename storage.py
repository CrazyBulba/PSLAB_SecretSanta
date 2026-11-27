"""
Хранение игр и GameManager + архив.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("DATA_DIR", "/data" if Path("/data").exists() else "."))
DATA_FILE = DATA_DIR / "games.json"
ARCHIVE_FILE = DATA_DIR / "archive.json"


class GameManager:
    def __init__(self):
        self.games: Dict[str, Dict[str, Any]] = {}
        self.archive: List[Dict[str, Any]] = []
        self.load()
        self.load_archive()

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
                g.setdefault("created_at", "")
                g.setdefault("last_draw_at", "")
                self.games[code] = g
            logger.info(f"Загружено {len(self.games)} игр")
        except Exception as e:
            logger.error(f"Load error: {e}")

    def load_archive(self):
        if not ARCHIVE_FILE.exists():
            return
        try:
            self.archive = json.loads(ARCHIVE_FILE.read_text(encoding="utf-8"))
            logger.info(f"Загружено {len(self.archive)} архивных записей")
        except Exception as e:
            logger.error(f"Archive load error: {e}")
            self.archive = []

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

    def save_archive(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            ARCHIVE_FILE.write_text(json.dumps(self.archive, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Archive save error: {e}")

    def delete(self, code: str):
        if code in self.games:
            del self.games[code]
            self.save()

    def delete_archive(self, code: str, organizer_id: int) -> bool:
        """Удалить запись из архива (только свою)."""
        before = len(self.archive)
        self.archive = [
            r for r in self.archive
            if not (r.get("code") == code and r.get("organizer_id") == organizer_id)
        ]
        if len(self.archive) < before:
            self.save_archive()
            return True
        return False

    def archive_game(self, code: str, organizer_id: int, organizer_name: str) -> Optional[Dict]:
        game = self.games.get(code)
        if not game or game.get("organizer") != organizer_id:
            return None

        # Формируем результат в формате @user1:@user2
        result_pairs = []
        if game.get("assignments"):
            for g_id, r_id in game["assignments"].items():
                g_info = game["participants"].get(g_id, {})
                r_info = game["participants"].get(r_id, {})
                gk = g_info.get("username") or f"id:{g_id}"
                rk = r_info.get("username") or f"id:{r_id}"
                if not str(gk).startswith("id:") and not str(rk).startswith("id:"):
                    result_pairs.append(f"@{gk}:@{rk}")

        record = {
            "code": code,
            "created_at": game.get("created_at") or datetime.now().strftime("%Y-%m-%d"),
            "organizer_id": organizer_id,
            "organizer_name": organizer_name,
            "last_draw_at": game.get("last_draw_at") or "",
            "participants_count": len(game["participants"]),
            "result": " ".join(result_pairs) if result_pairs else "-",
            "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        self.archive.append(record)
        self.save_archive()
        # Игра остаётся в активных
        return record

    def user_archive(self, user_id: int) -> List[Dict]:
        return [r for r in self.archive if r.get("organizer_id") == user_id]

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
            "created_at": datetime.now().strftime("%Y-%m-%d"),
            "last_draw_at": "",
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
