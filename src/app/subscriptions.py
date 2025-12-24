import json
from pathlib import Path
from typing import Dict, List, Optional


class SubscriptionsStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, dict] = {"users": {}}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._save()
            return
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._data = {"users": {}}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def ensure_user(self, user_id: int, username: Optional[str], name: Optional[str]) -> None:
        users = self._data.setdefault("users", {})
        uid = str(user_id)
        if uid not in users:
            users[uid] = {"chats": [], "username": username, "name": name}
        else:
            if username:
                users[uid]["username"] = username
            if name:
                users[uid]["name"] = name
        self._save()

    def subscribe(self, user_id: int, chat_id: int) -> None:
        users = self._data.setdefault("users", {})
        uid = str(user_id)
        users.setdefault(uid, {"chats": []})
        chats = set(users[uid].get("chats", []))
        chats.add(int(chat_id))
        users[uid]["chats"] = sorted(chats)
        self._save()

    def unsubscribe(self, user_id: int, chat_id: int) -> None:
        users = self._data.setdefault("users", {})
        uid = str(user_id)
        if uid not in users:
            return
        chats = set(users[uid].get("chats", []))
        if int(chat_id) in chats:
            chats.remove(int(chat_id))
            users[uid]["chats"] = sorted(chats)
            self._save()

    def get_user_chats(self, user_id: int) -> List[int]:
        users = self._data.get("users", {})
        user = users.get(str(user_id), {})
        return [int(c) for c in user.get("chats", [])]

    def get_subscribers_for_chat(self, chat_id: int) -> List[int]:
        users = self._data.get("users", {})
        result: List[int] = []
        for uid, payload in users.items():
            chats = payload.get("chats", [])
            if int(chat_id) in chats:
                result.append(int(uid))
        return result

    def list_users(self) -> Dict[int, dict]:
        users = self._data.get("users", {})
        return {int(uid): data for uid, data in users.items()}


class CatalogStore:
    def __init__(self, path: Path, initial_chat_ids: List[int]):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, list] = {"groups": []}
        if not self.path.exists():
            self._data["groups"] = [{"id": int(cid), "hidden": False} for cid in sorted(set(initial_chat_ids))]
            self._save()
        else:
            self._load()
            self._merge_initial(initial_chat_ids)

    def _load(self) -> None:
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._data = {"groups": []}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _merge_initial(self, initial_chat_ids: List[int]) -> None:
        existing = {g.get("id") for g in self._data.get("groups", [])}
        for cid in set(initial_chat_ids):
            if int(cid) not in existing:
                self._data.setdefault("groups", []).append({"id": int(cid), "hidden": False})
        self._save()

    def list_visible(self) -> List[int]:
        return [int(g["id"]) for g in self._data.get("groups", []) if not g.get("hidden")]

    def list_all(self) -> List[dict]:
        return self._data.get("groups", [])

    def add_group(self, chat_id: int) -> None:
        groups = self._data.setdefault("groups", [])
        for g in groups:
            if int(g.get("id")) == int(chat_id):
                g["hidden"] = False
                self._save()
                return
        groups.append({"id": int(chat_id), "hidden": False})
        self._save()

    def hide_group(self, chat_id: int) -> None:
        groups = self._data.setdefault("groups", [])
        for g in groups:
            if int(g.get("id")) == int(chat_id):
                g["hidden"] = True
                self._save()
                return

    def unhide_group(self, chat_id: int) -> None:
        groups = self._data.setdefault("groups", [])
        for g in groups:
            if int(g.get("id")) == int(chat_id):
                g["hidden"] = False
                self._save()
                return
