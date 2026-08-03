"""Базовый класс всех каналов уведомлений.

Новый канал (Discord, Push, ...) реализуется как наследник
``BaseNotifier`` и регистрируется в фабрике ``build_notifiers``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class BaseNotifier(ABC):
    """Интерфейс канала уведомлений о найденном матче."""

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """Включён ли канал (по настройкам пользователя)."""

    @abstractmethod
    def notify(self, message: str, image_path: Optional[str] = None) -> Optional[int]:
        """Отправляет уведомление о найденном матче.

        ``image_path`` — необязательный скриншот кнопки приёма; каналы,
        не умеющие картинки (звук), игнорируют его.

        Возвращает идентификатор отправленного сообщения (message_id)
        для последующего обновления, или None, если канал не поддерживает
        идентификаторы либо сообщение не отправилось.
        """

    def notify_test(self, message: str) -> None:
        """Отправляет тестовое уведомление (по умолчанию — обычное).

        Каналы, для которых «тест» отличается от «матча» (например,
        Telegram без кнопки приёма), переопределяют этот метод.
        """
        self.notify(message)


__all__ = ["BaseNotifier"]
