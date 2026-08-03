"""Статистика матчей: найдено, принято, упущено.

``MatchStats`` — потокобезопасный счётчик событий с сохранением в JSON
рядом с приложением (``writable_root()/stats.json``), чтобы статистика
переживала перезапуски и обновления .exe. События записываются из
потока монитора, из потока удалённого приёма и из GUI.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_STATS = {
    "matches_found": 0,
    "matches_accepted": 0,
    "matches_missed": 0,
    "last_match_at": None,
    "last_accept_at": None,
}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class MatchStats:
    """Потокобезопасный счётчик событий матчей с записью в JSON."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._data = dict(_DEFAULT_STATS)
        self._load()

    # ---------- публичный API ----------

    def record_found(self) -> None:
        """Записывает найденный матч."""
        with self._lock:
            self._data["matches_found"] += 1
            self._data["last_match_at"] = _now_text()
            self._save()

    def record_accepted(self) -> None:
        """Записывает принятый матч."""
        with self._lock:
            self._data["matches_accepted"] += 1
            self._data["last_accept_at"] = _now_text()
            self._save()

    def record_missed(self) -> None:
        """Записывает матч, который не успели принять."""
        with self._lock:
            self._data["matches_missed"] += 1
            self._save()

    def snapshot(self) -> dict[str, Any]:
        """Возвращает копию статистики для отображения."""
        with self._lock:
            return dict(self._data)

    # ---------- хранение ----------

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                merged = dict(_DEFAULT_STATS)
                merged.update(raw)
                self._data = merged
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            logger.warning("Не удалось прочитать статистику %s: %s", self._path, exc)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp = self._path.with_suffix(".json.tmp")
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            temp.replace(self._path)
        except OSError as exc:
            logger.warning("Не удалось сохранить статистику %s: %s", self._path, exc)


__all__ = ["MatchStats"]
