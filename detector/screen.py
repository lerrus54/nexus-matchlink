"""Создание и сохранение скриншотов экрана и окна игры."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import pyautogui
from PIL import Image

logger = logging.getLogger(__name__)

# (x, y, width, height)
Region = Tuple[int, int, int, int]

# ---------- захват содержимого отдельного окна (PrintWindow) ----------

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = (
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    )


class _BITMAPINFO(ctypes.Structure):
    _fields_ = (("bmiHeader", _BITMAPINFOHEADER),)


user32.GetDC.restype = ctypes.c_void_p
user32.GetDC.argtypes = [wt.HWND]
user32.ReleaseDC.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [wt.HWND, ctypes.c_void_p]
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.PrintWindow.argtypes = [wt.HWND, ctypes.c_void_p, ctypes.c_uint]
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.DeleteObject.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.restype = ctypes.c_int
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.GetDIBits.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.c_void_p,
    ctypes.POINTER(_BITMAPINFO),
    ctypes.c_uint,
]


def capture_window(hwnd: int) -> Optional[Image.Image]:
    """Захватывает окно через PrintWindow (размер = всё окно).

    В отличие от ``capture``, снимает содержимое самого окна, а не то,
    что на экране в этом месте — поэтому работает, даже когда окно игры
    лежит под другими окнами. Пиксели изображения имеют те же
    координаты, что и позиция окна на экране (см. ``window_origin``).
    Возвращает PIL-изображение или None.
    """
    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width = max(1, rect.right - rect.left)
    height = max(1, rect.bottom - rect.top)
    if width <= 4 or height <= 4:
        return None

    hdc = user32.GetDC(hwnd)
    if not hdc:
        return None
    try:
        mem_dc = gdi32.CreateCompatibleDC(hdc)
        bitmap = gdi32.CreateCompatibleBitmap(hdc, width, height)
        if not mem_dc or not bitmap:
            return None
        old = None
        try:
            old = gdi32.SelectObject(mem_dc, bitmap)
            user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)

            bmi = _BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height  # top-down
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = BI_RGB

            buffer = ctypes.create_string_buffer(width * height * 4)
            lines = gdi32.GetDIBits(
                mem_dc, bitmap, 0, height, buffer, ctypes.byref(bmi), DIB_RGB_COLORS
            )
            if lines != height:
                return None
            image = Image.frombuffer(
                "RGB", (width, height), buffer.raw, "raw", "BGRX", 0, 1
            )
            return image.copy()
        finally:
            if old:
                gdi32.SelectObject(mem_dc, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(mem_dc)
    finally:
        user32.ReleaseDC(hwnd, hdc)


def window_origin(hwnd: int) -> Tuple[int, int]:
    """Верхний левый угол окна на экране (для перевода координат захвата)."""
    rect = wt.RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return rect.left, rect.top
    return 0, 0


def client_to_screen(hwnd: int, x: int, y: int) -> Tuple[int, int]:
    """Переводит координаты клиентской области окна в координаты экрана."""
    point = wt.POINT(int(x), int(y))
    if user32.ClientToScreen(hwnd, ctypes.byref(point)):
        return point.x, point.y
    return int(x), int(y)


def capture(region: Optional[Region] = None):
    """Делает скриншот всего экрана или указанной области."""
    return pyautogui.screenshot(region=region)


def save_screenshot(directory: Path, prefix: str = "screen") -> Path:
    """Сохраняет текущий экран в PNG-файл и возвращает путь к нему."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
    capture().save(path)
    logger.debug("Скриншот сохранён: %s", path)
    return path


def save_debug_screenshot(directory: Path) -> Path:
    """Сохраняет скриншот для диагностики проблем с поиском кнопки."""
    return save_screenshot(directory, prefix="debug")


__all__ = [
    "Region",
    "capture",
    "capture_window",
    "client_to_screen",
    "window_origin",
    "save_debug_screenshot",
    "save_screenshot",
]
