"""Графический интерфейс на CustomTkinter в стиле киберпанк.

Окно управляет ``MatchMonitor``: запуск/остановка мониторинга, выбор
игры, лог событий и проверка уведомлений. Интерфейс обновляется через
``after()``, потому что мониторинг работает в фоновом потоке.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import replace
from datetime import datetime
from typing import Callable, Optional

from PIL import Image

import customtkinter as ctk

from config import Config, resolve_path, save_config
from core.clicker import ClickError, bring_game_to_front, click_at
from core.monitor import MatchMonitor
from detector.matcher import ButtonDetector
from gui.telegram_dialog import TelegramConnectDialog
from notifier import (
    BaseNotifier,
    TelegramListener,
    TelegramNotifier,
    build_notifiers,
)

logger = logging.getLogger(__name__)

THEME_PATH = resolve_path("assets/theme_cyberpunk.json")
WALLPAPER_PATH = resolve_path("assets/wallpaper.jpg")
ICON_PATH = resolve_path("assets/icon.ico")

# Премиальная палитра: глубокий графит + циан + золото
BG = "#0a0d12"
FRAME = "#121722"
CARD_BORDER = "#222b3b"
NEON_CYAN = "#2bd4e6"
NEON_CYAN_DIM = "#0f6f7a"
NEON_CYAN_HOVER = "#5ee7f2"
NEON_MAGENTA = "#c77dff"
NEON_RED = "#f4547a"
NEON_RED_HOVER = "#f77595"
GOLD = "#d4af37"
GOLD_DIM = "#8a6f23"
GOLD_HOVER = "#e6c95e"
TEXT = "#e9eef8"
MUTED = "#8a94ab"
FOOTER = "#4a5568"
ON_ACCENT = "#061214"

WINDOW_SIZE = "600x704"
APP_TITLE = "NEXUS MATCHLINK"
APP_SUBTITLE = "NEURAL MATCH DETECTOR // MULTI-GAME UPLINK"
APP_FOOTER = "NEXUS TERMINAL v0.4 // SYSTEM NOMINAL"
TEST_MESSAGE = "Тест уведомления из Nexus Matchlink."

# Ответы бота при удалённом приёме матча. {game} — выбранная игра
# (Dota 2, CS2): ответы одинаково корректны для обеих.
ACCEPT_ANSWER_OK = "✅ Матч {game} принят! Удачной катки."
ACCEPT_ANSWER_GONE = "⚠️ Не успел принять {game} — кнопка принятия уже исчезла."
ACCEPT_ANSWER_NO_MONITOR = "⚠️ Мониторинг не запущен — принять нечего."
ACCEPT_ANSWER_ERROR = "❌ Не удалось принять: {error}"

# Секунды ожидания отрисовки кадра игры после разворачивания окна.
# Кнопка ищется через PrintWindow (захват самого окна), поэтому ждать
# полного появления на экране не нужно — 0.3с достаточно, чтобы ОС
# завершила вывод окна на передний план перед кликом.
ACCEPT_WINDOW_SETTLE = 0.3
# Случайная пауза (сек.) перед кликом — делает приём «похожим на
# человека» и меньше похожим на автоматизацию.
ACCEPT_HUMAN_DELAY = (0.3, 0.9)
# Попыток найти кнопку на экране после разворачивания окна.
ACCEPT_LOCATE_ATTEMPTS = 6
# Секунды паузы между попытками поиска кнопки.
ACCEPT_LOCATE_DELAY = 1.0


def _mono(size: int = 13, bold: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(
        family="Consolas",
        size=size,
        weight="bold" if bold else "normal",
    )


class Application(ctk.CTk):
    """Главное окно приложения."""

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._monitor: Optional[MatchMonitor] = None
        self._notifiers: list[BaseNotifier] = build_notifiers(config)
        self._telegram: Optional[TelegramNotifier] = next(
            (n for n in self._notifiers if isinstance(n, TelegramNotifier)), None
        )
        self._detector: Optional[ButtonDetector] = None
        self._accept_listener: Optional[TelegramListener] = None
        self._accepting = False
        self._anim_job: Optional[str] = None
        self._dot_on = False

        ctk.set_appearance_mode("dark")
        try:
            ctk.set_default_color_theme(str(THEME_PATH))
        except Exception:
            ctk.set_default_color_theme("blue")

        self.title("Nexus Matchlink")
        self.geometry(WINDOW_SIZE)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            self.iconbitmap(str(ICON_PATH))
        except Exception:
            pass

        self._build_ui()
        self._refresh_status()
        self._log_event("Система готова. Выберите игру и запустите мониторинг.")
        if config.telegram.enabled and config.telegram.chat_id == 0:
            self._log_event(
                "Telegram не подключён: нажмите «CONNECT TG» и отправьте код боту."
            )

    # ---------- построение интерфейса ----------

    def _build_ui(self) -> None:
        self.configure(fg_color=BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(6, weight=1)

        self._build_background()

        # двойная акцентная линия сверху: золото поверх циана
        ctk.CTkFrame(self, fg_color=GOLD, height=3, corner_radius=0).grid(
            row=0, column=0, sticky="ew"
        )
        ctk.CTkFrame(self, fg_color=NEON_CYAN, height=3, corner_radius=0).grid(
            row=1, column=0, sticky="ew"
        )

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=2, column=0, pady=(18, 2), padx=20, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="◈",
            font=ctk.CTkFont(family="Segoe UI Symbol", size=34),
            text_color=GOLD,
        ).grid(row=0, column=0, padx=(4, 10))

        ctk.CTkLabel(
            header,
            text="NEXUS ",
            font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=1, sticky="w")

        ctk.CTkLabel(
            header,
            text="MATCHLINK",
            font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
            text_color=NEON_CYAN,
        ).grid(row=0, column=2, sticky="w")

        ctk.CTkLabel(
            self,
            text=APP_SUBTITLE,
            font=_mono(11),
            text_color=MUTED,
        ).grid(row=3, column=0, pady=(0, 4))

        self._build_controls(row=4)
        self._build_status(row=5)
        self._build_log(row=6)

        ctk.CTkLabel(
            self,
            text=APP_FOOTER,
            font=_mono(10),
            text_color=FOOTER,
        ).grid(row=7, column=0, pady=(0, 10))

    def _build_section_card(self, title: str) -> ctk.CTkFrame:
        """Карточка с золотым заголовком раздела и линией-разделителем."""
        card = ctk.CTkFrame(
            self,
            fg_color=FRAME,
            corner_radius=10,
            border_width=1,
            border_color=CARD_BORDER,
        )
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            card, text=title, font=_mono(10, bold=True), text_color=GOLD
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 0))
        ctk.CTkFrame(card, fg_color=GOLD_DIM, height=1, corner_radius=0).grid(
            row=1, column=0, sticky="ew", padx=14, pady=(6, 0)
        )
        return card

    def _build_background(self) -> None:
        """Лёгкий затемнённый фон позади контента (если файл найден)."""
        self._wallpaper_image = None
        try:
            image = Image.open(str(WALLPAPER_PATH)).convert("RGB")
        except Exception:
            return
        width, height = map(int, WINDOW_SIZE.split("x"))
        image = image.resize((width, height), Image.LANCZOS)
        # Затемнение превращает пёстрые обои в едва заметную фактуру фона
        dark = Image.new("RGB", image.size, BG)
        image = Image.blend(image, dark, alpha=0.86)
        self._wallpaper_image = ctk.CTkImage(
            light_image=image, dark_image=image, size=(width, height)
        )
        ctk.CTkLabel(self, image=self._wallpaper_image, text="").grid(
            row=0, column=0, rowspan=8, sticky="nsew"
        )

    def _build_controls(self, row: int) -> None:
        controls = self._build_section_card("CONTROL PANEL")
        controls.grid(row=row, column=0, padx=16, pady=(10, 8), sticky="ew")
        controls.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            controls, text="GAME", font=_mono(11, bold=True), text_color=MUTED
        ).grid(row=2, column=0, padx=(14, 8), pady=14, sticky="w")

        self.game_combo = ctk.CTkComboBox(
            controls,
            values=list(self._config.games),
            command=self._on_game_change,
            width=210,
            font=_mono(12),
            state="readonly",
        )
        self.game_combo.set(self._config.game_name)
        self.game_combo.grid(row=2, column=1, padx=8, pady=14, sticky="ew")

        self.start_button = ctk.CTkButton(
            controls,
            text="▶ START MONITOR",
            command=self._on_start,
            width=160,
            fg_color=NEON_CYAN,
            hover_color=NEON_CYAN_HOVER,
            text_color=ON_ACCENT,
            font=_mono(12, bold=True),
            corner_radius=8,
        )
        self.start_button.grid(row=2, column=2, padx=(8, 6), pady=14)

        self.stop_button = ctk.CTkButton(
            controls,
            text="■ STOP",
            command=self._on_stop,
            width=110,
            fg_color="transparent",
            hover_color="#1c2332",
            border_width=2,
            border_color=NEON_RED,
            text_color=NEON_RED,
            font=_mono(12, bold=True),
            corner_radius=8,
        )
        self.stop_button.grid(row=2, column=3, padx=(0, 14), pady=14)

    def _build_status(self, row: int) -> None:
        status = self._build_section_card("SYSTEM STATUS")
        status.grid(row=row, column=0, padx=16, pady=(0, 8), sticky="ew")
        status.grid_columnconfigure(2, weight=1)

        self.status_dot = ctk.CTkLabel(
            status, text="●", font=ctk.CTkFont(size=18), text_color=MUTED
        )
        self.status_dot.grid(row=2, column=0, padx=(14, 4), pady=(12, 2))

        self.status_text = ctk.CTkLabel(
            status,
            text="OFFLINE",
            font=_mono(15, bold=True),
            text_color=MUTED,
        )
        self.status_text.grid(row=2, column=1, padx=(0, 12), pady=(12, 2), sticky="w")

        self.channels_label = ctk.CTkLabel(
            status,
            text="",
            font=_mono(11),
            text_color=MUTED,
            wraplength=340,
            anchor="w",
        )
        self.channels_label.grid(
            row=3, column=0, columnspan=2, padx=14, pady=(0, 12), sticky="w"
        )

        self.test_button = ctk.CTkButton(
            status,
            text="TEST SIGNAL",
            command=self._on_test,
            width=160,
            fg_color="transparent",
            hover_color="#1c2332",
            border_width=2,
            border_color=NEON_CYAN,
            text_color=NEON_CYAN,
            font=_mono(11, bold=True),
            corner_radius=8,
        )
        self.test_button.grid(row=2, column=3, padx=14, pady=(12, 4), sticky="e")

        self.connect_button = ctk.CTkButton(
            status,
            text="CONNECT TG",
            command=self._on_connect_telegram,
            width=160,
            fg_color="transparent",
            hover_color="#1c2332",
            border_width=2,
            border_color=GOLD,
            text_color=GOLD,
            font=_mono(11, bold=True),
            corner_radius=8,
        )
        self.connect_button.grid(row=3, column=3, padx=14, pady=(0, 12), sticky="e")

    def _build_log(self, row: int) -> None:
        log_frame = self._build_section_card("SYSTEM LOG")
        log_frame.grid(row=row, column=0, padx=16, pady=(0, 8), sticky="nsew")
        log_frame.grid_rowconfigure(2, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        self.log_box = ctk.CTkTextbox(
            log_frame, font=_mono(11), corner_radius=8
        )
        self.log_box.grid(row=2, column=0, padx=10, pady=(8, 10), sticky="nsew")
        self.log_box.configure(state="disabled")

    # ---------- действия ----------

    def _on_start(self) -> None:
        if not self._telegram_ready():
            self._log_event(
                "Запуск заблокирован: сначала подключите Telegram (CONNECT TG)."
            )
            return
        if self._monitor is not None and self._monitor.is_running:
            return
        try:
            detector = self._build_detector()
        except ValueError as exc:
            self._log_event(f"Ошибка: {exc}")
            return
        profile = self._config.detector
        self._detector = detector
        self._monitor = MatchMonitor(
            detector=detector,
            notifiers=self._notifiers,
            check_interval=self._config.check_interval,
            game_name=self._config.game_name,
            window_hints=profile.window_hints,
            exe_hints=profile.exe_hints,
            screenshot_dir=self._config.log_dir,
            send_screenshot=self._config.telegram.send_screenshot,
            on_match_found=lambda: self._schedule(self._on_match_found),
            on_button_lost=lambda: self._schedule(self._on_button_lost),
        )
        self._monitor.start()
        self._start_accept_listener()
        self._refresh_status()
        self._log_event(f"Мониторинг запущен. Игра: {self._config.game_name}")
        self._log_event(
            "Держите окно игры открытым (можно под другими окнами) — "
            "программа сама развернёт его, если оно свёрнуто."
        )

    def _on_stop(self) -> None:
        if self._monitor is None:
            return
        self._monitor.stop()
        self._monitor.join(timeout=2)
        self._monitor = None
        self._stop_accept_listener()
        self._refresh_status()
        self._log_event("Мониторинг остановлен")

    def _on_game_change(self, choice: str) -> None:
        self._config = replace(self._config, selected_game=choice)
        if self._monitor is not None and self._monitor.is_running:
            self._log_event(f"Смена игры: {choice}. Перезапуск мониторинга...")
            self._restart_monitor()
        else:
            self._log_event(f"Выбрана игра: {choice}")

    def _on_match_found(self) -> None:
        self.status_text.configure(text="MATCH DETECTED", text_color=NEON_MAGENTA)
        self.status_dot.configure(text_color=NEON_MAGENTA)
        if self._accept_listener is not None and self._accept_listener.is_running:
            self._log_event("Матч найден! Кнопка приёма отправлена в Telegram.")
        else:
            self._log_event("Матч найден! Уведомления отправлены.")
        self.after(2500, self._refresh_status)

    def _on_button_lost(self) -> None:
        self._log_event("Кнопка исчезла. Жду следующий матч.")
        self._refresh_status()

    def _on_test(self) -> None:
        self._log_event("Отправляю тестовое уведомление...")
        for notifier in self._notifiers:
            try:
                notifier.notify_test(TEST_MESSAGE)
            except Exception as exc:
                self._log_event(f"Ошибка {type(notifier).__name__}: {exc}")

    def _on_connect_telegram(self) -> None:
        """Открывает диалог автоподключения Telegram по коду."""
        token = self._config.telegram.bot_token
        if not token:
            self._log_event("Ошибка: bot_token не указан в настройках.")
            return
        self._log_event("Открываю подключение Telegram...")
        TelegramConnectDialog(
            self, token=token, on_success=self._on_telegram_connected
        )

    def _on_telegram_connected(self, chat_id: int) -> None:
        """Сохраняет новый chat_id и обновляет интерфейс."""
        self._config = replace(
            self._config,
            telegram=replace(self._config.telegram, chat_id=chat_id),
        )
        save_config(self._config)
        self._notifiers = build_notifiers(self._config)
        self._telegram = next(
            (n for n in self._notifiers if isinstance(n, TelegramNotifier)), None
        )
        self._log_event(f"Telegram подключён. Chat ID: {chat_id}")
        if self._monitor is not None and self._monitor.is_running:
            self._monitor.set_notifiers(self._notifiers)
            self._start_accept_listener()
        self._refresh_status()

    # ---------- удалённый приём матча по кнопке в Telegram ----------

    def _start_accept_listener(self) -> None:
        """Запускает прослушивание кнопки «ПРИНЯТЬ МАТЧ» (если подключён TG)."""
        if self._telegram is None or not self._telegram.enabled:
            return
        if not self._config.telegram.chat_id or not self._config.telegram.accept_enabled:
            return
        if self._accept_listener is not None and self._accept_listener.is_running:
            return
        self._accept_listener = TelegramListener(
            token=self._config.telegram.bot_token,
            chat_id=self._config.telegram.chat_id,
            on_accept=lambda: self._schedule(self._on_accept_from_phone),
        )
        self._accept_listener.start()
        self._log_event("Слушатель кнопки «ПРИНЯТЬ» запущен.")

    def _stop_accept_listener(self) -> None:
        if self._accept_listener is None:
            return
        self._accept_listener.stop()
        self._accept_listener.join(timeout=2)
        self._accept_listener = None

    def _on_accept_from_phone(self) -> None:
        """Приём матча по кнопке в Telegram (запускает рабочий поток).

        Сначала разворачивается окно игры (даже если оно свёрнуто),
        затем ищется кнопка на уже видимом экране и выполняется клик.
        """
        if self._accepting:
            return
        if self._detector is None or self._monitor is None or not self._monitor.is_running:
            self._log_event("Приём отклонён: мониторинг не запущен.")
            self._telegram_result(ACCEPT_ANSWER_NO_MONITOR)
            return

        self._accepting = True
        self._log_event("Принимаю игру: разворачиваю окно...")
        threading.Thread(
            target=self._accept_worker,
            name="telegram-accept",
            daemon=True,
        ).start()

    def _accept_worker(self) -> None:
        """Рабочий поток приёма: фокус игры -> поиск кнопки -> клик."""
        try:
            profile = self._config.detector
        except ValueError as exc:
            self._schedule(lambda e=exc: self._log_event(f"Ошибка: {e}"))
            self._telegram_result(ACCEPT_ANSWER_ERROR.format(error=exc))
            self._accepting = False
            return

        try:
            bring_game_to_front(profile.window_hints, profile.exe_hints)
            self._schedule(lambda: self._log_event("Окно игры выведено на передний план."))
        except ClickError as exc:
            self._schedule(lambda e=exc: self._log_event(f"Ошибка: {e}"))
            self._telegram_result(ACCEPT_ANSWER_ERROR.format(error=exc))
            self._accepting = False
            return

        # После разворачивания игра рисует кадр не мгновенно.
        time.sleep(ACCEPT_WINDOW_SETTLE)

        region = None
        for attempt in range(ACCEPT_LOCATE_ATTEMPTS):
            region = self._detector.locate_for(profile.window_hints, profile.exe_hints)
            if region is not None:
                break
            if attempt < ACCEPT_LOCATE_ATTEMPTS - 1:
                time.sleep(ACCEPT_LOCATE_DELAY)

        if region is None:
            self._schedule(lambda: self._log_event("Кнопка принятия не найдена на экране."))
            self._telegram_result(ACCEPT_ANSWER_GONE.format(game=self._config.game_name))
            self._accepting = False
            return

        x, y, width, height = region
        cx, cy = x + width // 2, y + height // 2
        # Короткая случайная пауза перед кликом (человекоподобность).
        time.sleep(random.uniform(*ACCEPT_HUMAN_DELAY))
        self._schedule(
            lambda cx=cx, cy=cy: self._log_event(f"Принимаю матч: клик в ({cx}, {cy})...")
        )
        try:
            click_at(cx, cy)
            self._schedule(lambda: self._log_event("Кнопка принятия нажата."))
            self._telegram_result(ACCEPT_ANSWER_OK.format(game=self._config.game_name))
        except ClickError as exc:
            self._schedule(lambda e=exc: self._log_event(f"Ошибка клика: {e}"))
            self._telegram_result(ACCEPT_ANSWER_ERROR.format(error=exc))
        except Exception as exc:
            logger.exception("Ошибка при удалённом приёме матча")
            self._schedule(lambda e=exc: self._log_event(f"Неожиданная ошибка: {e}"))
            self._telegram_result(ACCEPT_ANSWER_ERROR.format(error=exc))
        finally:
            self._accepting = False

    def _telegram_result(self, message: str) -> None:
        """Отправляет результат приёма в Telegram (в фоновом потоке)."""
        if self._telegram is None or not self._telegram.enabled:
            return
        threading.Thread(
            target=self._telegram.send,
            args=(message,),
            name="telegram-result",
            daemon=True,
        ).start()

    # ---------- внутренние помощники ----------

    def _build_detector(self) -> ButtonDetector:
        profile = self._config.detector  # может бросить ValueError
        try:
            return ButtonDetector(
                image_path=profile.image,
                confidence=profile.confidence,
                region=profile.search_region,
            )
        except OSError as exc:
            raise ValueError(
                f"Для игры «{self._config.game_name}» не найден шаблон кнопки "
                f"{profile.image_path!r}. Сделайте скриншот кнопки Accept и "
                f"сохраните его в images/."
            ) from exc

    def _restart_monitor(self) -> None:
        self._on_stop()
        self._on_start()

    def _telegram_ready(self) -> bool:
        """Подключён ли Telegram (нужен для запуска мониторинга)."""
        return (
            self._telegram is not None
            and self._telegram.enabled
            and bool(self._config.telegram.chat_id)
        )

    def _refresh_status(self) -> None:
        running = self._monitor is not None and self._monitor.is_running
        if running:
            self.status_text.configure(text="MONITORING", text_color=NEON_CYAN)
            self.status_dot.configure(text_color=NEON_CYAN)
            self._start_animation()
        else:
            self.status_text.configure(text="OFFLINE", text_color=MUTED)
            self.status_dot.configure(text_color=MUTED)
            self._stop_animation()

        # START можно нажать только после подключения Telegram
        # (и пока мониторинг не запущен — дальше работает STOP).
        if not self._telegram_ready() or running:
            self.start_button.configure(state="disabled")
        else:
            self.start_button.configure(state="normal")

        channels = ", ".join(
            type(n).__name__ for n in self._notifiers if n.enabled
        )
        text = f"CHANNELS: {channels}" if channels else "CHANNELS: нет"
        if self._config.telegram.enabled and self._config.telegram.chat_id == 0:
            text += "  //  TELEGRAM: ТРЕБУЕТСЯ ПОДКЛЮЧЕНИЕ"
        self.channels_label.configure(text=text)

    def _start_animation(self) -> None:
        if self._anim_job is not None:
            return
        self._dot_on = True
        self._anim_job = self.after(400, self._animate_dot)

    def _animate_dot(self) -> None:
        if not (self._monitor is not None and self._monitor.is_running):
            self._anim_job = None
            self.status_dot.configure(text_color=MUTED)
            return
        self._dot_on = not self._dot_on
        self.status_dot.configure(
            text_color=NEON_CYAN if self._dot_on else NEON_CYAN_DIM
        )
        self._anim_job = self.after(400, self._animate_dot)

    def _stop_animation(self) -> None:
        if self._anim_job is not None:
            try:
                self.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None
        self.status_dot.configure(text_color=MUTED)

    def _schedule(self, callback: Callable[[], None]) -> None:
        """Выполняет колбэк в потоке GUI (вызывается из потока монитора)."""
        self.after(0, callback)

    def _log_event(self, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{datetime.now():%H:%M:%S}] {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _on_close(self) -> None:
        self._stop_animation()
        self._stop_accept_listener()
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor.join(timeout=2)
        self.destroy()


__all__ = ["Application"]
