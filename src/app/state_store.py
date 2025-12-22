import json
from pathlib import Path
from typing import Dict


class StateStore:
    """
    Простое хранение последнего отправленного message_id по chat_id.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state: Dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._state = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._state = {str(k): int(v) for k, v in raw.items()}
        except Exception:
            self._state = {}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_last(self, chat_id: int) -> int:
        return int(self._state.get(str(chat_id), 0))

    def set_last(self, chat_id: int, msg_id: int) -> None:
        self._state[str(chat_id)] = int(msg_id)
        self._save()
