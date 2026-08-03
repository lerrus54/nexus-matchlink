"""Точка входа графического интерфейса.

Запуск: ``python gui_main.py`` (с консолью) или двойным кликом по
``run.bat`` (через ``pythonw.exe``, без консоли).

При запуске без консоли необработанные ошибки пишутся в
``logs/crash.log``, чтобы их можно было найти и исправить.
"""

from __future__ import annotations

import logging
import sys
import traceback
from datetime import datetime

from config import load_config, writable_root
from core.logging_utils import setup_logging
from gui.app import Application

logger = logging.getLogger(__name__)


def _log_uncaught(exc_type, exc_value, exc_tb) -> None:
    """Сохраняет необработанную ошибку в logs/crash.log (без консоли)."""
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        logging.getLogger("uncaught").critical("Необработанная ошибка:\n%s", text)
    finally:
        crash_dir = writable_root() / "logs"
        try:
            crash_dir.mkdir(parents=True, exist_ok=True)
            with open(crash_dir / "crash.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{text}\n")
        except OSError:
            pass


sys.excepthook = _log_uncaught


def main() -> int:
    config = load_config()
    setup_logging(config.log_path)

    app = Application(config)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
