"""
Хранение игр и GameManager.
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("DATA_DIR", "/data" if Path("/data").exists() else "."))
DATA_FILE = DATA_DIR / "games.json"


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
