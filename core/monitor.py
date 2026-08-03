"""Цикл мониторинга экрана в отдельном фоновом потоке.

``MatchMonitor`` изолирует логику слежения: его можно запускать и
останавливать, а события доступны через колбэки. Это делает монитор
независимым от интерфейса — консольный CLI и будущий GUI используют
его одинаково.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from detector.matcher import ButtonDetector, _frame_is_black
from detector.screen import capture as capture_screen
from detector.screen import capture_window
from notifier.base import BaseNotifier

logger = logging.getLogger(__name__)

# Сколько сканирований подряд кнопка должна присутствовать, чтобы
# матч считался найденным (защита от случайного срабатывания), и
# сколько отсутствовать, чтобы считаться исчезнувшим.
MATCH_CONFIRM_FRAMES = 2
MATCH_LOST_FRAMES = 2


def build_message(game_name: str) -> str:
    """Формирует текст уведомления о найденном матче."""
    sent_at = datetime.now().strftime("%H:%M:%S")
    return f"🎮 {game_name}\n\n⚡ Матч найден!\nСкорее принимай игру! [{sent_at}]"


class MatchMonitor:
    """Отслеживает появление кнопки принятия матча на экране.

    Параметры-колбэки:
        on_match_found — вызывается при первом обнаружении кнопки;
        on_button_lost — вызывается, когда кнопка исчезает.
    """

    def __init__(
        self,
        detector: ButtonDetector,
        notifiers: list[BaseNotifier],
        check_interval: float = 1.0,
        game_name: str = "Game",
        window_hints: Optional[tuple[str, ...]] = None,
        exe_hints: Optional[tuple[str, ...]] = None,
        screenshot_dir: str = "logs",
        send_screenshot: bool = False,
        on_match_found: Optional[Callable[[], None]] = None,
        on_button_lost: Optional[Callable[[], None]] = None,
    ) -> None:
        self._detector = detector
        self._notifiers = list(notifiers)
        self._check_interval = max(0.05, float(check_interval))
        self._game_name = game_name
        self._window_hints = window_hints
        self._exe_hints = exe_hints
        self._screenshot_dir = screenshot_dir
        self._send_screenshot = bool(send_screenshot)
        self.on_match_found = on_match_found
        self.on_button_lost = on_button_lost

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_message_id: Optional[int] = None

    @property
    def is_running(self) -> bool:
        """Идёт ли фоновый поток мониторинга."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Запускает мониторинг в фоновом потоке."""
        if self.is_running:
            logger.debug("Мониторинг уже запущен")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="match-monitor",
            daemon=True,
        )
        self._thread.start()
        logger.info("Мониторинг запущен в фоновом потоке")

    def stop(self) -> None:
        """Запрашивает остановку мониторинга."""
        self._stop_event.set()

    def set_notifiers(self, notifiers: list[BaseNotifier]) -> None:
        """Обновляет каналы уведомлений на лету (например, после подключения TG)."""
        self._notifiers = list(notifiers)

    def set_send_screenshot(self, value: bool) -> None:
        """Включает/выключает отправку скриншота в уведомлениях на лету."""
        self._send_screenshot = bool(value)

    def wait(self, timeout: Optional[float] = None) -> None:
        """Блокирует текущий поток до остановки мониторинга.

        В CLI вызывается до нажатия Ctrl+C, в GUI не используется —
        GUI работает в своём цикле событий.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.is_running:
            if deadline is not None and time.monotonic() >= deadline:
                return
            time.sleep(0.2)

    def join(self, timeout: Optional[float] = None) -> None:
        """Ожидает завершения фонового потока."""
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        match_detected = False
        hit_streak = 0
        miss_streak = 0
        while not self._stop_event.is_set():
            try:
                detected = (
                    self._detector.locate_for(
                        self._window_hints,
                        self._exe_hints,
                        restore_minimized=False,
                    )
                    is not None
                )
            except Exception as exc:
                logger.exception("Ошибка при поиске кнопки: %s", exc)
                detected = False

            if detected:
                miss_streak = 0
                hit_streak += 1
                if not match_detected and hit_streak >= MATCH_CONFIRM_FRAMES:
                    logger.info("Матч найден! Отправляю уведомления.")
                    screenshot = (
                        self._capture_screenshot() if self._send_screenshot else None
                    )
                    self.last_message_id = self._notify(
                        build_message(self._game_name), image_path=screenshot
                    )
                    self._emit(self.on_match_found)
                    match_detected = True
            else:
                hit_streak = 0
                miss_streak += 1
                if match_detected and miss_streak >= MATCH_LOST_FRAMES:
                    logger.info("Кнопка исчезла. Жду следующий матч.")
                    self._emit(self.on_button_lost)
                    match_detected = False

            # wait() вместо sleep() делает остановку мгновенной
            self._stop_event.wait(self._check_interval)

    def _notify(self, message: str, image_path: Optional[str] = None) -> Optional[int]:
        first_message_id: Optional[int] = None
        for notifier in self._notifiers:
            try:
                result = notifier.notify(message, image_path=image_path)
            except Exception as exc:
                logger.error(
                    "Ошибка уведомителя %s: %s", type(notifier).__name__, exc
                )
                continue
            if first_message_id is None and result is not None:
                first_message_id = result
        return first_message_id

    def _capture_screenshot(self) -> Optional[str]:
        """Скриншот окна игры для уведомления (None, если не получилось).

        Окно предварительно разворачивается (без фокуса), чтобы свёрнутая
        игра успела отрисовать кадр. Если PrintWindow вернул чёрный кадр
        (DX11 в эксклюзивном полноэкранном режиме, например CS2) — берётся
        захват всего экрана. Файл сохраняется в ``self._screenshot_dir``.
        """
        # Ленивый импорт: core.clicker тянет detector — см. matcher.locate_for.
        from core.clicker import find_game_window, restore_window_no_activate

        try:
            hwnd = find_game_window(self._window_hints, self._exe_hints)
            if hwnd is None:
                return None
            restore_window_no_activate(hwnd)
            image = capture_window(hwnd)
            if image is None or _frame_is_black(image):
                image = capture_screen()
            if image is None:
                return None
            directory = Path(self._screenshot_dir)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"screenshot_{datetime.now():%Y%m%d_%H%M%S}.png"
            image.save(path, "PNG")
            logger.info("Скриншот матча сохранён: %s", path)
            return str(path)
        except Exception as exc:
            logger.warning("Не удалось сделать скриншот матча: %s", exc)
            return None

    @staticmethod
    def _emit(callback: Optional[Callable[[], None]]) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            logger.error("Ошибка в колбэке монитора: %s", exc)


__all__ = ["MatchMonitor", "build_message"]
