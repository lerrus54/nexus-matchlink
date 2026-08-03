"""Симуляция клика мышью и активация окна игры (Windows).

Используется для удалённого приёма матча: игрок нажимает кнопку
«ПРИНЯТЬ МАТЧ» в Telegram, а приложение разворачивает окно игры (даже
если оно свёрнуто или за другим окном), выводит его на передний план и
делает реальный клик в центр кнопки принятия матча на экране.

Клик выполняется через ``SendInput`` (MOVEF + нажатие/отпускание левой
кнопки) — такой клик считается «настоящим» на уровне ОС и корректно
обрабатывается игровыми движками, в отличие от PostMessage.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import time
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000

SW_MINIMIZE = 6
SW_RESTORE = 9
SW_SHOWNOACTIVATE = 4

VK_MENU = 0x12  # Alt
KEYEVENTF_KEYUP = 0x0002

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Окно игры ищется по фрагменту заголовка или по имени процесса.
DEFAULT_WINDOW_HINTS: tuple[str, ...] = ("dota 2",)
DEFAULT_EXE_HINTS: tuple[str, ...] = ("dota2.exe",)


class ClickError(RuntimeError):
    """Ошибка клика: окно не найдено, событие не отправлено и т.п."""


# ---------- структуры для SendInput (как в pyautogui, проверено) ----------


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    )


class _INPUT_UNION(ctypes.Union):
    _fields_ = (
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    )


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = (
        ("type", ctypes.c_ulong),
        ("union", _INPUT_UNION),
    )


def _declare_signatures() -> None:
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_wchar_p,
        ctypes.POINTER(wt.DWORD),
    ]
    user32.GetWindowThreadProcessId.argtypes = [
        wt.HWND,
        ctypes.POINTER(wt.DWORD),
    ]
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SendInput.argtypes = [
        ctypes.c_uint,
        ctypes.POINTER(INPUT),
        ctypes.c_int,
    ]
    user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_size_t]


_declare_signatures()


# ---------- поиск и активация окна игры ----------


def _window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _process_name(hwnd: int) -> str:
    """Имя исполняемого файла процесса окна (например, dota2.exe)."""
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wt.DWORD(512)
        buf = ctypes.create_unicode_buffer(512)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name.lower()
    except Exception:
        pass
    finally:
        kernel32.CloseHandle(handle)
    return ""


def find_game_window(
    window_hints: Optional[Sequence[str]] = None,
    exe_hints: Optional[Sequence[str]] = None,
) -> Optional[int]:
    """Ищет верхнеуровневое видимое окно игры.

    Если заданы ``exe_hints`` (dota2.exe/cs2.exe), окно ищется СТРОГО по
    имени процесса — это надёжный признак игры. Поиск по заголовку
    используется только когда exe_hints нет, иначе окно с похожим
    заголовком (например, вкладка браузера «Dota 2 гайд») может быть
    принято за игру. Возвращает hwnd или None.
    """
    window_hints = tuple(h.lower() for h in (window_hints or DEFAULT_WINDOW_HINTS))
    exe_hints = tuple(e.lower() for e in (exe_hints or DEFAULT_EXE_HINTS))
    exe_hits: list[int] = []
    title_hits: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def callback(hwnd: int, _) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if exe_hints:
            if _process_name(hwnd) in exe_hints:
                exe_hits.append(hwnd)
            return True
        title = _window_title(hwnd)
        if any(hint in title.lower() for hint in window_hints):
            title_hits.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    if exe_hints:
        return exe_hits[0] if exe_hits else None
    return title_hits[0] if title_hits else None


def _press_alt() -> None:
    """Имитирует нажатие Alt — снимает «блокировку переднего плана» Windows."""
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)


def focus_window(hwnd: int) -> None:
    """Разворачивает окно (если свёрнуто) и выводит на передний план.

    Windows запрещает фоновым процессам перехватывать фокус, поэтому
    пробуются несколько приёмов по очереди: AttachThreadInput +
    BringWindowToTop, сворачивание/разворачивание и имитация Alt.
    """
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.3)

    if user32.GetForegroundWindow() == hwnd:
        return

    foreground = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(foreground, None)
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)

    attached = False
    if fg_thread and fg_thread != target_thread:
        attached = bool(user32.AttachThreadInput(fg_thread, target_thread, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(fg_thread, target_thread, False)

    if user32.GetForegroundWindow() != hwnd:
        # Сворачивание/разворачивание обычно снимает запрет Windows
        # на перехват фокуса фоновым процессом.
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)

    if user32.GetForegroundWindow() != hwnd:
        # Имитация Alt — ещё один способ снять блокировку фокуса.
        _press_alt()
        user32.SetForegroundWindow(hwnd)

    if user32.GetForegroundWindow() != hwnd:
        logger.warning("Не удалось вывести окно игры на передний план")


def bring_game_to_front(
    window_hints: Optional[Sequence[str]] = None,
    exe_hints: Optional[Sequence[str]] = None,
) -> int:
    """Находит окно игры, разворачивает его и выводит на передний план.

    Возвращает hwnd. Поднимает ``ClickError``, если окно не найдено.
    Используется перед поиском кнопки на экране: после вывода окна из
    свёрнутого состояния кнопка снова видна на видимом экране.
    """
    hwnd = find_game_window(window_hints, exe_hints)
    if hwnd is None:
        raise ClickError("Окно игры не найдено. Убедитесь, что игра запущена.")
    focus_window(hwnd)
    return hwnd


def is_window_minimized(hwnd: int) -> bool:
    """Свёрнуто ли окно (иконизировано)."""
    return bool(user32.IsIconic(hwnd))


def restore_window_no_activate(hwnd: int) -> bool:
    """Разворачивает свёрнутое окно без перехвата фокуса.

    Нужно для захвата окна игры: свёрнутая DirectX-игра не рендерит
    кадры, поэтому до PrintWindow её надо показать. Возвращает True,
    если окно было свёрнуто и развёрнуто.
    """
    if not user32.IsIconic(hwnd):
        return False
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    time.sleep(0.3)
    return True


# ---------- клик мышью ----------


def _mouse_input(flags: int, dx: int = 0, dy: int = 0) -> INPUT:
    return INPUT(
        type=INPUT_MOUSE,
        mi=MOUSEINPUT(
            dx=dx,
            dy=dy,
            mouseData=0,
            dwFlags=flags,
            time=0,
            dwExtraInfo=0,
        ),
    )


def click_at(x: int, y: int) -> None:
    """Делает реальный клик левой кнопкой мыши в абсолютных координатах экрана."""
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    if screen_w <= 1 or screen_h <= 1:
        raise ClickError("Не удалось определить размер экрана")

    x = max(0, min(int(x), screen_w - 1))
    y = max(0, min(int(y), screen_h - 1))
    # SendInput использует абсолютные координаты 0..65535.
    norm_x = int(x * 65535 / (screen_w - 1))
    norm_y = int(y * 65535 / (screen_h - 1))

    user32.SetCursorPos(x, y)
    time.sleep(0.05)

    move = _mouse_input(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, norm_x, norm_y)
    down = _mouse_input(MOUSEEVENTF_LEFTDOWN)
    up = _mouse_input(MOUSEEVENTF_LEFTUP)
    events = (INPUT * 3)(move, down, up)
    events_ptr = ctypes.cast(events, ctypes.POINTER(INPUT))

    sent = user32.SendInput(3, events_ptr, ctypes.sizeof(INPUT))
    if sent != 3:
        raise ClickError(f"SendInput отправил {sent}/3 событий мыши")
    logger.info("Клик выполнен в (%s, %s)", x, y)


def click_accept_button(
    x: int,
    y: int,
    window_hints: Optional[Sequence[str]] = None,
    exe_hints: Optional[Sequence[str]] = None,
    focus_delay: float = 0.6,
) -> None:
    """Активирует окно игры и кликает в точку (x, y) кнопки принятия."""
    bring_game_to_front(window_hints, exe_hints)
    time.sleep(focus_delay)
    click_at(x, y)


__all__ = [
    "ClickError",
    "bring_game_to_front",
    "click_accept_button",
    "click_at",
    "find_game_window",
    "focus_window",
    "is_window_minimized",
    "restore_window_no_activate",
]
