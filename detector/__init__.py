"""Детектирование кнопки принятия матча на экране."""

from detector.matcher import ButtonDetector
from detector.screen import capture, save_debug_screenshot, save_screenshot

__all__ = ["ButtonDetector", "capture", "save_debug_screenshot", "save_screenshot"]
