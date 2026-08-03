"""Главная точка входа программы.

Собирает конфигурацию, создаёт детектор и уведомители,
запускает фоновый мониторинг (``MatchMonitor``) и ожидает остановки.
Консольный CLI и будущий GUI используют один и тот же монитор.
"""

from __future__ import annotations

import logging
import sys

from config import Config, load_config
from core.logging_utils import setup_logging
from core.monitor import MatchMonitor
from detector.matcher import ButtonDetector
from notifier import BaseNotifier, build_notifiers

logger = logging.getLogger(__name__)


def build_components(config: Config) -> tuple[ButtonDetector, list[BaseNotifier]]:
    """Создаёт детектор и список уведомителей по конфигурации."""
    detector = ButtonDetector(
        image_path=config.detector.image,
        confidence=config.detector.confidence,
        region=config.detector.search_region,
    )
    notifiers = build_notifiers(config)
    return detector, notifiers


def run() -> int:
    """Запускает мониторинг. Возвращает код выхода."""
    config: Config = load_config()
    setup_logging(config.log_path)

    detector, notifiers = build_components(config)
    monitor = MatchMonitor(
        detector=detector,
        notifiers=notifiers,
        check_interval=config.check_interval,
        game_name=config.game_name,
    )

    logger.info(
        "Мониторинг запущен. Игра: %s, интервал: %s сек, confidence: %s",
        config.game_name,
        config.check_interval,
        config.detector.confidence,
    )

    try:
        monitor.start()
        monitor.wait()
    except KeyboardInterrupt:
        logger.info("Мониторинг остановлен пользователем.")
    finally:
        monitor.stop()
        monitor.join(timeout=2)

    return 0


if __name__ == "__main__":
    sys.exit(run())
