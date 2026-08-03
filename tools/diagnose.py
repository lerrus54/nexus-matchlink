"""Диагностика поиска окна/кнопки для CS2 (запускать при открытой игре).

Проверяет по цепочке:
  1. Находится ли окно игры (EnumWindows по процессу).
  2. Свёрнуто ли оно.
  3. Что даёт захват PrintWindow: свёрнутое -> после restore_no_activate
     -> после focus_window. Для каждого кадра считается NCC с шаблоном
     accept_cs2.png (порог confidence).
  4. То же для полного экрана.

Кадры сохраняются в logs/diagnose/ для визуального контроля.
"""

import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

from core.clicker import find_game_window, focus_window, is_window_minimized, restore_window_no_activate
from detector.matcher import ButtonDetector
from detector.screen import capture, capture_window, window_origin

OUT = Path("logs/diagnose")
OUT.mkdir(parents=True, exist_ok=True)

TEMPLATES = {
    "accept_cs2.png": ButtonDetector("images/accept_cs2.png", confidence=0.8),
    "accept.png": ButtonDetector("images/accept.png", confidence=0.8),
}


def gray_stats(img):
    a = np.asarray(img.convert("L"), dtype=np.float32)
    return float(a.mean()), float(a.std())


def save(img, name):
    path = OUT / f"{name}.png"
    img.save(path)
    return path


def ncc_all(img):
    g = np.asarray(img.convert("L"), dtype=np.uint8)
    out = []
    for label, det in TEMPLATES.items():
        try:
            region = det._locate_in(g)
            out.append(f"{label}={region if region is not None else 'no'}")
        except Exception as exc:
            out.append(f"{label}=err:{exc}")
    return ", ".join(out)


def report(label, img):
    if img is None:
        print(f"[{label}] capture=None (не удалось снять окно)")
        return
    mean, std = gray_stats(img)
    path = save(img, label.replace(" ", "_"))
    print(f"[{label}] {img.size} mean={mean:.1f} std={std:.1f} -> {ncc_all(img)}  | {path}")


def main() -> int:
    det = TEMPLATES["accept_cs2.png"]
    print("Текущая конфигурация: confidence =", det.confidence, "| шаблон:", det.image_path)
    print("Шаблон CS2:", det._template.shape, "| шаблон Dota:", TEMPLATES["accept.png"]._template.shape)
    print("Жду запущенное окно CS2...")

    hwnd = None
    deadline = time.time() + 30
    while hwnd is None and time.time() < deadline:
        hwnd = find_game_window(None, ("cs2.exe",))
        if hwnd is None:
            time.sleep(1)
    if hwnd is None:
        print("Окно cs2.exe НЕ НАЙДЕНО за 30 сек. Игра запущена? Или процесс другой (cs2 / csgo)?")
        return 1

    import ctypes.wintypes as wt
    title = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetWindowTextW(hwnd, title, 256)
    print(f"Окно найдено: hwnd={hwnd} title={title.value!r} minimized={is_window_minimized(hwnd)}")

    report("1_window_now", capture_window(hwnd))

    if is_window_minimized(hwnd):
        print("Окно свёрнуто -> restore_window_no_activate")
        restore_window_no_activate(hwnd)
        time.sleep(0.6)
        report("2_after_restore_no_activate", capture_window(hwnd))

    print("-> focus_window (активация)")
    focus_window(hwnd)
    time.sleep(0.6)
    report("3_after_focus", capture_window(hwnd))

    print("Полный экран:")
    screen = capture()
    if screen is not None:
        report("4_fullscreen", screen)

    print("Замер NCC в цикле 10 сек (после активации):")
    t0 = time.time()
    while time.time() - t0 < 10:
        img = capture_window(hwnd)
        if img is not None:
            g = np.asarray(img.convert("L"), dtype=np.uint8)
            mean, std = gray_stats(img)
            region = det._locate_in(g)
            print(f"  mean={mean:.1f} std={std:.1f} ncc_det={region is not None}")
        time.sleep(1)

    print("Кадры сохранены в", OUT.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
