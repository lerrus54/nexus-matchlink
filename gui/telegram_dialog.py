"""Диалог автоподключения Telegram по коду.

Показывает код и имя бота, слушает getUpdates в фоновом потоке и при
получении кода от пользователя возвращает его chat_id. Живой статус
показывает, есть ли связь с Telegram API, чтобы нельзя было спутать
«не пришёл код» с «нет доступа к сети».
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import customtkinter as ctk

from notifier.telegram import TelegramPairer

GREEN = "#2ecc71"
RED = "#ff2b6d"
CYAN = "#00e5ff"
MAGENTA = "#ff2b9c"
MUTED = "#6a7390"
ON_NEON = "#001018"

PAIR_DEADLINE_SECONDS = 60


class TelegramConnectDialog(ctk.CTkToplevel):
    """Модальное окно: код -> отправка боту -> автоопределение chat_id."""

    def __init__(
        self,
        master: ctk.CTk,
        token: str,
        on_success: Callable[[int], None],
    ) -> None:
        super().__init__(master)
        self._pairer = TelegramPairer(token)
        self._on_success = on_success
        self._code = self._pairer.generate_code()
        self._result: Optional[int] = None
        self._error: Optional[str] = None
        self._bot_username: Optional[str] = None
        self._bot_info_shown = False
        self._poll_job: Optional[str] = None
        self._stop_event = threading.Event()

        self.title("Подключение Telegram")
        self.geometry("480x360")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self._build_ui()
        self._start_pairing()

    # ---------- интерфейс ----------

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text="ПОДКЛЮЧЕНИЕ TELEGRAM",
            font=ctk.CTkFont(family="Consolas", size=16, weight="bold"),
            text_color=CYAN,
        ).grid(row=0, column=0, padx=20, pady=(18, 6))

        self.bot_label = ctk.CTkLabel(
            self,
            text="Определяю бота...",
            font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
            text_color=MAGENTA,
        )
        self.bot_label.grid(row=1, column=0, padx=20, pady=(0, 4))

        ctk.CTkLabel(
            self,
            text="В Telegram отправьте этому боту код:",
            text_color=MUTED,
            font=ctk.CTkFont(family="Consolas", size=12),
        ).grid(row=2, column=0, padx=20, pady=(0, 2))

        code_row = ctk.CTkFrame(self, fg_color="transparent")
        code_row.grid(row=3, column=0, pady=4)

        self.code_label = ctk.CTkLabel(
            code_row,
            text=self._code,
            font=ctk.CTkFont(family="Consolas", size=40, weight="bold"),
            text_color=CYAN,
        )
        self.code_label.grid(row=0, column=0)

        self.copy_button = ctk.CTkButton(
            code_row,
            text="КОПИРОВАТЬ",
            command=self._copy_code,
            width=130,
            fg_color="transparent",
            hover_color="#141a2c",
            border_width=2,
            border_color=CYAN,
            text_color=CYAN,
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
        )
        self.copy_button.grid(row=0, column=1, padx=(18, 0))

        self.status_label = ctk.CTkLabel(
            self, text="Устанавливаю связь с Telegram...",
            font=ctk.CTkFont(family="Consolas", size=12), text_color=MUTED,
        )
        self.status_label.grid(row=4, column=0, padx=20, pady=(4, 2))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=5, column=0, pady=(10, 16))
        buttons.grid_columnconfigure(0, weight=1)
        buttons.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            buttons,
            text="ПОВТОРИТЬ",
            command=self._restart,
            width=130,
            fg_color="transparent",
            hover_color="#141a2c",
            border_width=2,
            border_color=CYAN,
            text_color=CYAN,
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
        ).grid(row=0, column=0, padx=(0, 10))

        ctk.CTkButton(
            buttons,
            text="ОТМЕНА",
            command=self._cancel,
            width=130,
            fg_color="transparent",
            hover_color="#1b2236",
            border_width=2,
            border_color=MUTED,
            text_color=MUTED,
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
        ).grid(row=0, column=1, padx=(10, 0))

    # ---------- логика ----------

    def _copy_code(self) -> None:
        """Копирует код в буфер обмена и подсвечивает подтверждение."""
        self.clipboard_clear()
        self.clipboard_append(self._code)
        self.copy_button.configure(text="СКОПИРОВАНО", fg_color=GREEN, text_color=ON_NEON)
        self.after(
            1500,
            lambda: self.copy_button.configure(
                text="КОПИРОВАТЬ",
                fg_color="transparent",
                text_color=CYAN,
                border_color=CYAN,
            ),
        )

    def _start_pairing(self) -> None:
        """Запускает новое ожидание кода с новым сгенерированным кодом."""
        self._code = self._pairer.generate_code()
        self.code_label.configure(text=self._code)
        self.copy_button.configure(
            text="КОПИРОВАТЬ", fg_color="transparent", text_color=CYAN, border_color=CYAN
        )
        self._result = None
        self._error = None
        self._bot_username = None
        self._bot_info_shown = False
        self._stop_event = threading.Event()
        self._deadline = time.monotonic() + PAIR_DEADLINE_SECONDS
        self.bot_label.configure(text="Определяю бота...")
        self.status_label.configure(
            text="Устанавливаю связь с Telegram...", text_color=MUTED
        )
        thread = threading.Thread(
            target=self._pair_worker, args=(self._stop_event,), daemon=True
        )
        thread.start()
        self._poll()

    def _restart(self) -> None:
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        self._stop_event.set()
        self._start_pairing()

    def _pair_worker(self, stop_event: threading.Event) -> None:
        username, error = self._pairer.probe()
        if stop_event.is_set():
            return
        self._bot_username = username
        if error:
            self._error = (
                f"Нет доступа к Telegram API: {error}. Проверьте интернет."
            )
            return
        try:
            result = self._pairer.wait_for_code(
                self._code,
                deadline_seconds=PAIR_DEADLINE_SECONDS,
                stop_event=stop_event,
            )
            if not stop_event.is_set():
                self._result = result
        except Exception as exc:
            if not stop_event.is_set():
                self._error = str(exc)

    def _poll(self) -> None:
        if not self._bot_info_shown and self._bot_username is not None:
            self._bot_info_shown = True
            self.bot_label.configure(text=f"@{self._bot_username}")

        if self._error is not None:
            self.status_label.configure(text=self._error, text_color=RED)
            return
        if self._result is not None:
            self.status_label.configure(
                text=f"Подключено! Chat ID: {self._result}", text_color=GREEN
            )
            self._on_success(self._result)
            self._poll_job = self.after(1500, self.destroy)
            return

        remaining = max(0, int(self._deadline - time.monotonic()))
        pairer = self._pairer
        if pairer.reached_api:
            if self._bot_username is None and pairer.last_error:
                text = f"Ошибка связи: {pairer.last_error}"
                color = RED
            else:
                text = f"Связь установлена. Ожидаю код... Осталось {remaining} с"
                color = MUTED
        elif pairer.attempts > 1:
            text = (
                f"Нет доступа к Telegram API (попытка {pairer.attempts}): "
                f"{pairer.last_error or 'сеть недоступна'}."
            )
            color = RED
        else:
            text = "Устанавливаю связь с Telegram..."
            color = MUTED
        self.status_label.configure(text=text, text_color=color)
        self._poll_job = self.after(500, self._poll)

    def _cancel(self) -> None:
        self._stop_event.set()
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
        self.grab_release()
        self.destroy()


__all__ = ["TelegramConnectDialog"]
