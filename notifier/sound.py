"""Звуковые уведомления пользователя."""

from __future__ import annotations

import logging
import time
from typing import Optional

from config import SoundSettings
from notifier.base import BaseNotifier

logger = logging.getLogger(__name__)

try:
    import winsound
except ImportError:  # не-Windows платформы
    winsound = None


class SoundNotifier(BaseNotifier):
    """Проигрывает серию коротких сигналов через winsound."""

    BEEP_FREQUENCY = 900
    BEEP_DURATION_MS = 250
    PAUSE_SECONDS = 0.35

    def __init__(self, settings: SoundSettings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    def play(self) -> None:
        """Проигрывает звуковой сигнал (при включённых настройках)."""
        if not self._settings.enabled:
            return
        if winsound is None:
            logger.warning("Звуковые уведомления доступны только в Windows")
            return
        for _ in range(max(1, self._settings.repeats)):
            winsound.Beep(self.BEEP_FREQUENCY, self.BEEP_DURATION_MS)
            time.sleep(self.PAUSE_SECONDS)

    def notify(self, message: str, image_path: Optional[str] = None) -> None:
        """Текст и картинка не используются — это звуковой канал."""
        self.play()


__all__ = ["SoundNotifier"]
