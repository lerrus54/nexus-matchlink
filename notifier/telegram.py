"""Отправка уведомлений в Telegram, автоподключение и приём матча по кнопке."""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from config import TelegramSettings
from notifier.base import BaseNotifier

logger = logging.getLogger(__name__)


class TelegramApi:
    """Низкоуровневый клиент Telegram Bot API (getMe, getUpdates)."""

    BASE_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str) -> None:
        self._token = token

    def _call(self, method: str, http_timeout: int = 15, **params: Any) -> Any:
        url = self.BASE_URL.format(token=self._token, method=method)
        response = requests.get(url, params=params, timeout=http_timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API: {data.get('description')}")
        return data.get("result")

    def get_me(self) -> dict[str, Any]:
        """Возвращает информацию о боте."""
        return self._call("getMe")

    def get_updates(self, offset: Optional[int] = None, timeout: int = 0) -> list:
        """Возвращает новые входящие сообщения боту.

        ``timeout`` — long-polling в секундах (Telegram держит запрос),
        HTTP-таймаут всегда больше, чтобы ответ успел вернуться.
        """
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", http_timeout=timeout + 10, **params)

    def answer_callback_query(self, query_id: str, text: str = "") -> Any:
        """Отвечает на нажатие inline-кнопки (убирает «часики» у кнопки)."""
        return self._call(
            "answerCallbackQuery",
            callback_query_id=query_id,
            text=text,
        )


class TelegramPairer:
    """Автоматически определяет chat_id пользователя по уникальному коду.

    Схема: приложение показывает код, пользователь отправляет этот код
    боту в Telegram, а ``wait_for_code`` находит его в getUpdates и
    возвращает id чата. Никакого ручного ввода Telegram ID.
    """

    POLL_TIMEOUT = 5
    DEFAULT_DEADLINE = 60

    def __init__(self, token: str) -> None:
        self._api = TelegramApi(token)
        self.attempts = 0
        self.reached_api = False
        self.last_error: Optional[str] = None

    @staticmethod
    def generate_code(length: int = 6) -> str:
        """Генерирует уникальный цифровой код для пары приложение-чат."""
        return "".join(random.choices("0123456789", k=length))

    def bot_username(self) -> Optional[str]:
        """Возвращает @username бота (или None, если не удалось)."""
        try:
            me = self._api.get_me()
            return me.get("username")
        except Exception as exc:
            logger.debug("Не удалось получить данные бота: %s", exc)
            return None

    def probe(self) -> tuple[Optional[str], Optional[str]]:
        """Проверяет доступ к боту: (username, ошибка). Ошибка None = ОК."""
        try:
            me = self._api.get_me()
            return me.get("username"), None
        except Exception as exc:
            return None, str(exc)

    def wait_for_code(
        self,
        code: str,
        deadline_seconds: int = DEFAULT_DEADLINE,
        stop_event: Optional[threading.Event] = None,
    ) -> Optional[int]:
        """Ждёт сообщение с кодом и возвращает chat_id или None по таймауту.

        Если за всё время не удалось достучаться до Telegram API,
        поднимает RuntimeError с последней ошибкой (иначе пользователь
        видит бесполезное «время вышло»). ``stop_event`` позволяет
        прервать ожидание (закрытие окна / повтор).
        """
        offset: Optional[int] = None
        deadline = time.monotonic() + deadline_seconds
        self.attempts = 0
        self.reached_api = False
        self.last_error = None
        while time.monotonic() < deadline and not (stop_event and stop_event.is_set()):
            self.attempts += 1
            try:
                updates = self._api.get_updates(
                    offset=offset, timeout=self.POLL_TIMEOUT
                )
            except Exception as exc:
                self.last_error = str(exc)
                if "409" in str(exc):
                    self.last_error += (
                        " (конфликт: бота одновременно слушает другое "
                        "устройство/окно)"
                    )
                logger.warning("Ошибка getUpdates (%s попытка): %s",
                               self.attempts, self.last_error)
                time.sleep(1)
                continue
            self.reached_api = True
            self.last_error = None
            for update in updates:
                offset = update.get("update_id", 0) + 1
                message = update.get("message") or update.get("edited_message") or {}
                text = "".join(ch for ch in (message.get("text") or "") if ch.isdigit())
                chat = message.get("chat") or {}
                if code in text and chat.get("id"):
                    return chat["id"]
        if not self.reached_api and not (stop_event and stop_event.is_set()):
            raise RuntimeError(self.last_error or "Нет доступа к Telegram API")
        return None


class TelegramNotifier(BaseNotifier):
    """Отправляет уведомления через Telegram Bot API.

    При найденном матче сообщение снабжается inline-кнопкой
    «ПРИНЯТЬ МАТЧ»: нажав её в телефоне, игрок принимает игру удалённо.
    """

    API_URL = "https://api.telegram.org/bot{token}/sendMessage"
    PHOTO_URL = "https://api.telegram.org/bot{token}/sendPhoto"
    REQUEST_TIMEOUT = 5

    ACCEPT_CALLBACK = "accept_match"
    ACCEPT_BUTTON_TEXT = "✅ ПРИНЯТЬ МАТЧ"
    _ACCEPT_MARKUP = json.dumps(
        {"inline_keyboard": [[{"text": ACCEPT_BUTTON_TEXT, "callback_data": ACCEPT_CALLBACK}]]}
    )

    def __init__(self, settings: TelegramSettings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    @property
    def accept_enabled(self) -> bool:
        return self._settings.accept_enabled

    def send(self, text: str, reply_markup: Optional[str] = None) -> bool:
        """Отправляет сообщение (reply_markup — JSON-строка клавиатуры)."""
        if not self._settings.enabled:
            logger.debug("Telegram-уведомления отключены в настройках")
            return False
        if not self._settings.bot_token or not self._settings.chat_id:
            logger.error("Не задан bot_token или chat_id в настройках")
            return False

        url = self.API_URL.format(token=self._settings.bot_token)
        payload: dict[str, Any] = {
            "chat_id": self._settings.chat_id,
            "text": text,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            response = requests.post(url, data=payload, timeout=self.REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            logger.error("Сетевая ошибка при отправке в Telegram: %s", exc)
            return False

        if response.status_code == 200:
            logger.info("Уведомление в Telegram отправлено")
            return True

        logger.error(
            "Telegram вернул статус %s: %s", response.status_code, response.text
        )
        return False

    def send_photo(
        self,
        chat_id: int,
        caption: str,
        image_path: str,
        reply_markup: Optional[str] = None,
    ) -> bool:
        """Отправляет скриншот с подписью (multipart-загрузка файла)."""
        try:
            with open(image_path, "rb") as file_handle:
                files = {
                    "photo": (Path(image_path).name, file_handle, "image/png")
                }
                payload: dict[str, Any] = {
                    "chat_id": chat_id,
                    "caption": caption,
                }
                if reply_markup:
                    payload["reply_markup"] = reply_markup
                url = self.PHOTO_URL.format(token=self._settings.bot_token)
                response = requests.post(url, data=payload, files=files, timeout=self.REQUEST_TIMEOUT)
        except OSError as exc:
            logger.error("Не удалось открыть скриншот %s: %s", image_path, exc)
            return False

        if response.status_code == 200:
            logger.info("Скриншот матча отправлен в Telegram")
            return True

        logger.error(
            "Telegram вернул статус %s при отправке фото: %s",
            response.status_code,
            response.text,
        )
        return False

    def notify(self, message: str, image_path: Optional[str] = None) -> None:
        """Матч найден: отправляем скриншот (если есть) и кнопку приёма."""
        markup = self._ACCEPT_MARKUP if self.accept_enabled else None
        if image_path:
            return self.send_photo(
                self._settings.chat_id, message, image_path, reply_markup=markup
            )
        return self.send(message, reply_markup=markup)

    def notify_test(self, message: str) -> None:
        """Тест: простое сообщение без кнопки приёма."""
        self.send(message)


class TelegramListener:
    """Фоновый поток, слушает inline-кнопки бота (приём матча с телефона).

    Использует тот же getUpdates long-poll, что и ``TelegramPairer``, но
    живёт всё время мониторинга. На нажатие кнопки отвечает вызовом
    ``on_accept`` в контексте GUI-потока (через ``self._schedule``).
    """

    CALLBACK_ACCEPT = TelegramNotifier.ACCEPT_CALLBACK
    POLL_TIMEOUT = 30

    def __init__(
        self,
        token: str,
        chat_id: int,
        on_accept: Callable[[], None],
    ) -> None:
        self._api = TelegramApi(token)
        self._chat_id = chat_id
        self._on_accept = on_accept
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        """Работает ли фоновый поток прослушивания."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Запускает прослушивание в фоновом потоке."""
        if self.is_running:
            logger.debug("Слушатель кнопок уже запущен")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="telegram-listener",
            daemon=True,
        )
        self._thread.start()
        logger.info("Слушатель кнопок Telegram запущен")

    def stop(self) -> None:
        """Запрашивает остановку прослушивания."""
        self._stop_event.set()

    def join(self, timeout: Optional[float] = None) -> None:
        """Ожидает завершения фонового потока."""
        if self._thread is not None:
            self._thread.join(timeout)

    # ---------- внутренняя логика ----------

    def _run(self) -> None:
        offset: Optional[int] = None
        while not self._stop_event.is_set():
            try:
                updates = self._api.get_updates(
                    offset=offset, timeout=self.POLL_TIMEOUT
                )
            except Exception as exc:
                if "409" in str(exc):
                    logger.warning(
                        "Конфликт getUpdates (409): бота слушает другое "
                        "устройство/окно. Продолжаю попытки."
                    )
                else:
                    logger.warning("Ошибка опроса кнопок: %s", exc)
                self._stop_event.wait(2)
                continue

            for update in updates:
                offset = int(update.get("update_id", 0)) + 1
                callback = update.get("callback_query") or {}
                if not callback:
                    continue
                self._handle_callback(callback)

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        query_id = callback.get("id")
        chat = (callback.get("message") or {}).get("chat") or {}
        data = callback.get("data")

        if chat.get("id") != self._chat_id:
            self._answer(
                query_id,
                "Этот аккаунт не подключён к приложению.",
            )
            return
        if data == self.CALLBACK_ACCEPT:
            # Сначала запускаем приём — answerCallbackQuery (HTTP-запрос)
            # не должен задерживать клик. Ответ кнопке идёт параллельно.
            self._emit(self._on_accept)
            self._answer(query_id, "🎮 Принимаю игру...")
        else:
            self._answer(query_id, "Неизвестная команда.")

    def _answer(self, query_id: Optional[str], text: str) -> None:
        if not query_id:
            return
        try:
            self._api.answer_callback_query(query_id, text=text)
        except Exception as exc:
            logger.warning("Не удалось ответить на кнопку: %s", exc)

    @staticmethod
    def _emit(callback: Optional[Callable[[], None]]) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            logger.error("Ошибка в обработчике кнопки: %s", exc)


__all__ = [
    "TelegramApi",
    "TelegramListener",
    "TelegramNotifier",
    "TelegramPairer",
]
