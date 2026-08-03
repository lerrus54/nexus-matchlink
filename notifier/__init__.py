"""Уведомления пользователя: Telegram, звук и другие каналы.

Фабрика ``build_notifiers`` собирает включённые каналы из конфигурации.
Чтобы добавить новый канал, реализуйте ``BaseNotifier`` и добавьте его
в фабрику.
"""

from __future__ import annotations

from config import Config

from notifier.base import BaseNotifier
from notifier.sound import SoundNotifier
from notifier.telegram import (
    TelegramApi,
    TelegramListener,
    TelegramNotifier,
    TelegramPairer,
)

__all__ = [
    "BaseNotifier",
    "SoundNotifier",
    "TelegramApi",
    "TelegramListener",
    "TelegramNotifier",
    "TelegramPairer",
    "build_notifiers",
]


def build_notifiers(config: Config) -> list[BaseNotifier]:
    """Создаёт включённые каналы уведомлений согласно конфигурации."""
    notifiers: list[BaseNotifier] = []
    if config.telegram.enabled:
        notifiers.append(TelegramNotifier(config.telegram))
    if config.sound.enabled:
        notifiers.append(SoundNotifier(config.sound))
    return notifiers
