"""Загрузка и предоставление настроек приложения.

Конфигурация поддерживает реестр игр: у каждой игры свои
настройки детектора, а активная игра выбирается через
поле ``selected_game``. Это фундамент для поддержки
нескольких игр и будущего GUI.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.json"

_DEFAULT_RAW_JSON = """{
  "selected_game": "Dota 2",
  "games": {
    "Dota 2": {
      "image_path": "images/accept.png",
      "confidence": 0.8,
      "search_region": null,
      "window_hints": ["dota 2"],
      "exe_hints": ["dota2.exe"]
    },
    "CS2": {
      "image_path": "images/accept_cs2.png",
      "confidence": 0.8,
      "search_region": null,
      "window_hints": ["counter-strike"],
      "exe_hints": ["cs2.exe"]
    }
  },
  "check_interval": 1.0,
  "log_dir": "logs",
  "telegram": {
    "enabled": true,
    "bot_token": "",
    "chat_id": 0,
    "accept_enabled": true,
    "send_screenshot": false
  },
  "sound": {
    "enabled": true,
    "repeats": 3
  }
}"""


def user_config_path() -> Path:
    """Путь к пользовательскому конфигу.

    В собранном .exe это каталог рядом с исполняемым файлом
    (чтобы настройки сохранялись после перезапуска), иначе —
    обычный путь в проекте.
    """
    if getattr(sys, "frozen", False):
        return writable_root() / "config" / "settings.json"
    return DEFAULT_CONFIG_PATH

logger = logging.getLogger(__name__)

Region = tuple[int, int, int, int]


def app_root() -> Path:
    """Корень приложения.

    В собранном .exe (PyInstaller) ресурсы находятся в каталоге
    ``_MEIPASS``, в обычном запуске — это корень проекта.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
    return PROJECT_ROOT


def writable_root() -> Path:
    """Каталог для файлов, которые должны жить рядом с приложением.

    Для .exe это каталог рядом с исполняемым файлом, иначе — корень проекта.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


def resolve_path(path: str) -> Path:
    """Превращает относительный путь в абсолютный относительно корня приложения."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return app_root() / candidate


@dataclass(frozen=True)
class GameProfile:
    """Настройки детектора и поиска окна для конкретной игры.

    ``window_hints`` / ``exe_hints`` — фрагменты заголовка окна и имена
    процессов, по которым программа находит окно игры для автоклика.
    Пустые списки означают «использовать встроенные значения по умолчанию».
    """

    image_path: str
    confidence: float = 0.80
    search_region: Optional[Region] = None
    window_hints: tuple[str, ...] = ()
    exe_hints: tuple[str, ...] = ()

    @property
    def image(self) -> Path:
        """Абсолютный путь к изображению кнопки принятия."""
        return resolve_path(self.image_path)


@dataclass(frozen=True)
class TelegramSettings:
    """Настройки Telegram-уведомлений."""

    enabled: bool = True
    bot_token: str = ""
    chat_id: int = 0
    accept_enabled: bool = True
    send_screenshot: bool = False


@dataclass(frozen=True)
class SoundSettings:
    """Настройки звуковых уведомлений."""

    enabled: bool = True
    repeats: int = 3


@dataclass(frozen=True)
class Config:
    """Полная конфигурация программы."""

    games: dict[str, GameProfile] = field(default_factory=dict)
    selected_game: str = "Dota 2"
    check_interval: float = 1.0
    log_dir: str = "logs"
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    sound: SoundSettings = field(default_factory=SoundSettings)

    @property
    def game_name(self) -> str:
        """Название активной игры."""
        return self.selected_game

    @property
    def detector(self) -> GameProfile:
        """Профиль детектора активной игры."""
        profile = self.games.get(self.selected_game)
        if profile is None:
            raise ValueError(
                f"Игра {self.selected_game!r} отсутствует в реестре "
                f"config/games. Доступно: {', '.join(self.games) or '<нет>'}."
            )
        return profile

    @property
    def log_path(self) -> Path:
        """Каталог логов рядом с приложением (работоспособно в .exe)."""
        return writable_root() / self.log_dir


def _load_raw(path: Path) -> dict[str, Any]:
    # utf-8-sig молча пропускает BOM, который могут записать
    # Блокнот/PowerShell — иначе json.load падает на первом символе.
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Конфиг {path} должен содержать JSON-объект")
    return data


def _parse_search_region(value: Any) -> Optional[Region]:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("search_region должен быть массивом из 4 чисел или null")
    x, y, width, height = (int(v) for v in value)
    return x, y, width, height


def _parse_games(raw_games: Any) -> dict[str, GameProfile]:
    if not isinstance(raw_games, dict):
        raise ValueError("Поле games должно быть объектом вида {имя игры: настройки}")
    games: dict[str, GameProfile] = {}
    for name, raw_profile in raw_games.items():
        if not isinstance(raw_profile, dict):
            raise ValueError(f"Настройки игры {name!r} должны быть объектом")
        games[name] = GameProfile(
            image_path=str(raw_profile.get("image_path", "")),
            confidence=float(raw_profile.get("confidence", 0.80)),
            search_region=_parse_search_region(raw_profile.get("search_region")),
            window_hints=tuple(str(h) for h in raw_profile.get("window_hints", [])),
            exe_hints=tuple(str(h) for h in raw_profile.get("exe_hints", [])),
        )
    return games


def _embedded_raw() -> dict[str, Any]:
    """Встроенные настройки по умолчанию (не зависят от файлов на диске)."""
    return json.loads(_DEFAULT_RAW_JSON)


def _read_effective_raw() -> dict[str, Any]:
    """Читает конфиг: user-конфиг рядом с .exe -> шаблон -> встроенные значения."""
    if getattr(sys, "frozen", False):
        user_path = user_config_path()
        if not user_path.exists():
            try:
                template = app_root() / "config" / "settings.json"
                if template.is_file():
                    user_path.parent.mkdir(parents=True, exist_ok=True)
                    user_path.write_bytes(template.read_bytes())
            except OSError as exc:
                logger.warning("Не удалось создать конфиг рядом с .exe: %s", exc)
        config_path = user_path
    else:
        config_path = DEFAULT_CONFIG_PATH
    try:
        return _load_raw(config_path)
    except (OSError, ValueError) as exc:
        logger.error("Не удалось прочитать конфиг %s: %s", config_path, exc)
        return _embedded_raw()


def load_config(path: Optional[Path] = None) -> Config:
    """Читает settings.json и возвращает объект Config.

    Порядок поиска: явный путь -> пользовательский конфиг рядом с .exe ->
    встроенный шаблон -> встроенные значения по умолчанию. Приложение
    никогда не падает из-за недоступного файла настроек.
    """
    if path is not None:
        config_path = Path(path)
        try:
            raw = _load_raw(config_path)
        except (OSError, ValueError) as exc:
            raise ValueError(f"Не удалось прочитать конфиг {config_path}: {exc}") from exc
    else:
        raw = _read_effective_raw()

    telegram_raw = raw.get("telegram", {})
    sound_raw = raw.get("sound", {})

    telegram = TelegramSettings(
        enabled=bool(telegram_raw.get("enabled", True)),
        bot_token=str(telegram_raw.get("bot_token", "")),
        chat_id=int(telegram_raw.get("chat_id", 0)),
        accept_enabled=bool(telegram_raw.get("accept_enabled", True)),
        send_screenshot=bool(telegram_raw.get("send_screenshot", False)),
    )
    sound = SoundSettings(
        enabled=bool(sound_raw.get("enabled", True)),
        repeats=int(sound_raw.get("repeats", 3)),
    )
    return Config(
        games=_parse_games(raw.get("games", {})),
        selected_game=str(raw.get("selected_game", "Dota 2")),
        check_interval=float(raw.get("check_interval", 1.0)),
        log_dir=str(raw.get("log_dir", "logs")),
        telegram=telegram,
        sound=sound,
    )


def save_config(config: Config, path: Optional[Path] = None) -> None:
    """Записывает Config обратно в settings.json.

    Используется при автоподключении Telegram: новый chat_id сохраняется
    в файл настроек, чтобы не теряться после перезапуска.
    """
    config_path = Path(path) if path else user_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        raw = _load_raw(config_path)
    else:
        raw = _embedded_raw()

    raw["selected_game"] = config.selected_game
    raw["check_interval"] = config.check_interval
    raw["log_dir"] = config.log_dir
    raw["telegram"] = {
        "enabled": config.telegram.enabled,
        "bot_token": config.telegram.bot_token,
        "chat_id": config.telegram.chat_id,
        "accept_enabled": config.telegram.accept_enabled,
        "send_screenshot": config.telegram.send_screenshot,
    }
    raw["sound"] = {
        "enabled": config.sound.enabled,
        "repeats": config.sound.repeats,
    }
    raw["games"] = {
        name: {
            "image_path": profile.image_path,
            "confidence": profile.confidence,
            "search_region": None
            if profile.search_region is None
            else list(profile.search_region),
            "window_hints": list(profile.window_hints),
            "exe_hints": list(profile.exe_hints),
        }
        for name, profile in config.games.items()
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)


__all__ = [
    "Config",
    "GameProfile",
    "PROJECT_ROOT",
    "Region",
    "SoundSettings",
    "TelegramSettings",
    "app_root",
    "load_config",
    "resolve_path",
    "save_config",
    "user_config_path",
    "writable_root",
]
