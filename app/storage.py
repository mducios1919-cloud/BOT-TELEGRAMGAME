"""Simple JSON-file storage for users + admin cookie pool."""
import json
import os
import threading
import time
import uuid
from typing import Any

_LOCK = threading.RLock()
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "db.json")

_DEFAULT = {
    "user": None,             # {"username": str, "password_hash": str, "created_at": float}
    "cookies": [],            # [{"id","label","cookie_string","user_agent","created_at","active"}]
    "stats": {"total_runs": 0, "total_success": 0},
    "history": [],            # last 200 entries
}


def _load() -> dict[str, Any]:
    if not os.path.exists(DB_PATH):
        return json.loads(json.dumps(_DEFAULT))
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in _DEFAULT.items():
            data.setdefault(k, json.loads(json.dumps(v)))
        return data
    except Exception:
        return json.loads(json.dumps(_DEFAULT))


def _save(data: dict[str, Any]) -> None:
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_PATH)


def read() -> dict[str, Any]:
    with _LOCK:
        return _load()


def write(mut) -> dict[str, Any]:
    with _LOCK:
        data = _load()
        mut(data)
        _save(data)
        return data


def add_cookie(label: str, cookie_string: str, user_agent: str) -> dict:
    entry = {
        "id": uuid.uuid4().hex[:10],
        "label": label or f"Cookie-{int(time.time())}",
        "cookie_string": cookie_string,
        "user_agent": user_agent,
        "created_at": time.time(),
        "active": True,
    }
    def _m(d):
        d["cookies"].append(entry)
    write(_m)
    return entry


def delete_cookie(cookie_id: str) -> bool:
    found = {"v": False}
    def _m(d):
        before = len(d["cookies"])
        d["cookies"] = [c for c in d["cookies"] if c["id"] != cookie_id]
        found["v"] = len(d["cookies"]) < before
    write(_m)
    return found["v"]


def toggle_cookie(cookie_id: str) -> bool:
    found = {"v": False}
    def _m(d):
        for c in d["cookies"]:
            if c["id"] == cookie_id:
                c["active"] = not c.get("active", True)
                found["v"] = True
                break
    write(_m)
    return found["v"]


def pick_active_cookie() -> dict | None:
    data = read()
    actives = [c for c in data["cookies"] if c.get("active", True)]
    if not actives:
        return None
    # pick least recently used (rotate)
    actives.sort(key=lambda c: c.get("last_used", 0))
    chosen = actives[0]
    def _m(d):
        for c in d["cookies"]:
            if c["id"] == chosen["id"]:
                c["last_used"] = time.time()
                break
    write(_m)
    return chosen


def push_history(entry: dict) -> None:
    def _m(d):
        d["history"].insert(0, entry)
        d["history"] = d["history"][:200]
        d["stats"]["total_runs"] = d["stats"].get("total_runs", 0) + 1
        if entry.get("ok"):
            d["stats"]["total_success"] = d["stats"].get("total_success", 0) + 1
    write(_m)
