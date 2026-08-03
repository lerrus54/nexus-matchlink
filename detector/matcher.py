"""Поиск кнопки принятия матча на экране без OpenCV.

Алгоритм: нормализованная кросс-корреляция (NCC) — тот же метод, что
использует OpenCV в ``cv2.matchTemplate`` с флагом ``TM_CCOEFF_NORMED``.
Реализация на numpy + PIL, поэтому не требует тяжёлую библиотеку
``opencv-python`` (основной источник размера собранного .exe).

Кнопка в игре рендерится в разном пиксельном размере в зависимости от
разрешения экрана, поэтому шаблон автоматически подбирается по масштабу:

1. Грубый перебор масштабов (``SCALE_MIN``..``SCALE_MAX``) на кадре,
   уменьшенном в ``COARSE_DOWNSCALE`` раз, — находится приблизительный
   масштаб и позиция кнопки.
2. Уточнение масштаба и позиции в половинном разрешении вокруг
   найденной точки.
3. Решение о "найдено" по порогу ``confidence`` (NCC в [-1, 1]).

Благодаря авто-масштабированию один и тот же скриншот кнопки работает
на любом разрешении игры.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

import numpy as np
from PIL import Image

from detector.screen import Region, capture, capture_window, window_origin

logger = logging.getLogger(__name__)

# Во сколько раз уменьшается кадр для грубого этапа поиска.
COARSE_DOWNSCALE = 8
# Во сколько раз уменьшается область для этапа уточнения.
REFINE_DOWNSCALE = 2
# Половина стороны области уточнения (в пикселях уменьшенного кадра).
# Меньше 24: ошибка грубого этапа (8px) и масштаба накрываются, а
# область уточнения в разы меньше — этап быстрее.
REFINE_MARGIN = 18

# Авто-подбор масштаба шаблона под разрешение экрана.
SCALE_MIN = 0.5
SCALE_MAX = 2.5
# Грубый шаг 0.2: худшая ошибка масштаба 0.1, её накрывает
# уточняющий радиус 0.12. Так грубый этап вдвое быстрее.
SCALE_COARSE_STEP = 0.2
# Точность масштаба 0.02 даёт погрешность центра кнопки < 4px —
# достаточно для клика в центр.
SCALE_FINE_STEP = 0.04
SCALE_FINE_RADIUS = 0.12

# Минимальная дисперсия, ниже которой область считается "плоской"
# и NCC для неё не вычисляется (защита от деления на ноль).
_EPS_VAR = 1e-6


def _scale_steps(start: float, stop: float, step: float) -> list[float]:
    """Равномерная сетка масштабов: start, start+step, ..., <= stop."""
    count = int(round((stop - start) / step)) + 1
    return [round(start + i * step, 6) for i in range(count)]


def _to_gray(image: Image.Image) -> np.ndarray:
    """Превращает PIL-изображение в grayscale-массив uint8."""
    return np.asarray(image.convert("L"), dtype=np.uint8)


def _resize_gray(image: Image.Image, new_width: int, new_height: int) -> np.ndarray:
    """Уменьшает grayscale-изображение билинейной интерполяцией."""
    if new_width < 1 or new_height < 1:
        return np.empty((0, 0), dtype=np.uint8)
    resized = image.convert("L").resize((new_width, new_height), Image.BILINEAR)
    return np.asarray(resized, dtype=np.uint8)


def _ncc_map(screen: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Карта NCC для всех позиций скользящего окна.

    ``screen`` и ``template`` — float32 массивы (единый тип исключает
    лишние копии и ускоряет matmul). Возвращает массив (h-th+1, w-tw+1)
    со значениями в диапазоне [-1, 1]; пустой массив, если шаблон больше
    кадра.
    """
    sh, sw = screen.shape
    th, tw = template.shape
    if sh < th or sw < tw:
        return np.empty((0, 0), dtype=np.float32)

    count = th * tw
    windows = np.lib.stride_tricks.sliding_window_view(screen, (th, tw))
    # Непрерывная копия (N, count) для быстрого матричного умножения.
    w2 = np.ascontiguousarray(windows).reshape(-1, count)
    t = template.reshape(-1)

    cross = w2 @ t
    window_sum = w2.sum(axis=1)
    # einsum вместо (w2 * w2) не материализует промежуточный массив.
    window_sq = np.einsum("ij,ij->i", w2, w2)

    template_sum = t.sum()
    template_sq = float(t @ t)

    template_mean = template_sum / count
    template_var = template_sq / count - template_mean * template_mean

    window_mean = window_sum / count
    window_var = window_sq / count - window_mean * window_mean

    covariance = cross / count - window_mean * template_mean
    denominator = np.sqrt(window_var * template_var)

    with np.errstate(divide="ignore", invalid="ignore"):
        ncc = np.where(denominator > _EPS_VAR, covariance / denominator, 0.0)

    return ncc.reshape((sh - th + 1, sw - tw + 1))


class ButtonDetector:
    """Ищет эталонное изображение (кнопку Accept) на экране."""

    def __init__(
        self,
        image_path: Union[str, Path],
        confidence: float = 0.80,
        region: Optional[Region] = None,
    ) -> None:
        self.image_path = Path(image_path)
        self.confidence = confidence
        self.region = region
        self._template = self._load_template(self.image_path)

    @staticmethod
    def _load_template(image_path: Path) -> np.ndarray:
        """Загружает и кэширует эталон как grayscale-массив."""
        with Image.open(image_path) as img:
            return _to_gray(img.convert("RGB"))

    def locate(self) -> Optional[Region]:
        """Возвращает координаты найденной кнопки или None, если её нет."""
        try:
            screen = capture(region=self.region)
        except Exception:
            logger.exception("Не удалось захватить экран")
            return None
        if screen is None:
            return None
        return self._locate_in(_to_gray(screen))

    def locate_for(
        self,
        window_hints: Optional[tuple[str, ...]] = None,
        exe_hints: Optional[tuple[str, ...]] = None,
        restore_minimized: bool = True,
    ) -> Optional[Region]:
        """Ищет кнопку в окне игры, при неудаче — на всём экране.

        Захват через PrintWindow берёт содержимое самого окна игры,
        поэтому кнопка находится, даже если игра лежит под другими
        окнами. Если ``restore_minimized`` (при удалённом приёме), свёрнутое
        окно предварительно разворачивается без перехвата фокуса.
        Свёрнутая игра не рендерит кадры (особенно Source 2 / CS2) —
        PrintWindow вернёт чёрный кадр, и кнопка не найдётся, поэтому
        свёрнутое окно разворачивается в любом случае, даже при фоновом
        сканировании: разворачивание происходит один раз (после этого
        окно уже не свёрнуто), без перехвата фокуса.

        Возвращает регион в координатах ЭКРАНА (как и ``locate``).
        """
        # Ленивый импорт: core.clicker тянет core.monitor -> detector,
        # поэтому импорт на уровне модуля даёт циклическую зависимость.
        from core.clicker import find_game_window, is_window_minimized, restore_window_no_activate

        hwnd = find_game_window(window_hints, exe_hints)
        if hwnd is not None:
            if restore_minimized or is_window_minimized(hwnd):
                restore_window_no_activate(hwnd)
            try:
                window_image = capture_window(hwnd)
            except Exception:
                logger.exception("Не удалось захватить окно игры")
                window_image = None
            if window_image is not None:
                region = self._locate_in(_to_gray(window_image))
                if region is not None:
                    x, y, width, height = region
                    ox, oy = window_origin(hwnd)
                    cx, cy = ox + x + width // 2, oy + y + height // 2
                    return int(cx - width // 2), int(cy - height // 2), int(width), int(height)
        return self.locate()

    def is_visible(self) -> bool:
        """Проверяет, есть ли кнопка на экране в данный момент."""
        return self.locate() is not None

    # ---------- внутренняя логика поиска ----------

    def _locate_in(self, screen: np.ndarray) -> Optional[Region]:
        coarse = self._coarse_match(screen)
        if coarse is None:
            return None

        scale, fx, fy = coarse
        return self._refine(screen, fx, fy, scale)

    def _coarse_match(self, screen: np.ndarray) -> Optional[tuple[float, int, int]]:
        """Грубый этап: перебирает масштабы шаблона на уменьшенном кадре.

        Возвращает (масштаб, x, y) — приблизительный масштаб кнопки и
        координаты верхнего левого угла в полном разрешении. None, если
        совпадения нет ни на одном масштабе.
        """
        sh, sw = screen.shape
        th, tw = self._template.shape

        cw = max(1, sw // COARSE_DOWNSCALE)
        ch = max(1, sh // COARSE_DOWNSCALE)

        # Единый float32 на весь грубый этап — без конверсий в _ncc_map.
        screen_f = _resize_gray(Image.fromarray(screen), cw, ch).astype(np.float32)

        best_ncc = -1.0
        best_scale = 1.0
        best_cx = best_cy = 0

        for s in _scale_steps(SCALE_MIN, SCALE_MAX, SCALE_COARSE_STEP):
            stw = max(1, round(tw * s / COARSE_DOWNSCALE))
            sth = max(1, round(th * s / COARSE_DOWNSCALE))
            if stw > cw or sth > ch:
                continue
            template_c = _resize_gray(
                Image.fromarray(self._template), stw, sth
            ).astype(np.float32)
            map_c = _ncc_map(screen_f, template_c)
            if map_c.size == 0:
                continue

            best_idx = int(np.argmax(map_c))
            value = float(map_c.flat[best_idx])
            if value > best_ncc:
                best_ncc = value
                best_scale = s
                best_cy, best_cx = np.unravel_index(best_idx, map_c.shape)

        if best_ncc < self.confidence:
            return None

        scale_x = sw / cw
        scale_y = sh / ch
        fx = int(round(best_cx * scale_x))
        fy = int(round(best_cy * scale_y))
        return best_scale, fx, fy

    def _refine(
        self, screen: np.ndarray, fx: int, fy: int, base_scale: float
    ) -> Optional[Region]:
        """Точный этап: уточняет масштаб и позицию в половинном разрешении.

        Возвращает регион (x, y, w, h) в полном разрешении, где w/h —
        размеры найденной кнопки с учётом масштаба (для точного клика в
        центр). None, если совпадения нет.
        """
        th, tw = self._template.shape
        scale = REFINE_DOWNSCALE

        half_tw = max(1, round(tw * base_scale / scale))
        half_th = max(1, round(th * base_scale / scale))
        if half_tw < 2 or half_th < 2:
            return self._refine_full(screen, fx, fy, base_scale)

        left = max(0, fx // scale - REFINE_MARGIN)
        top = max(0, fy // scale - REFINE_MARGIN)

        full_w = (REFINE_MARGIN * 2 + half_tw) * scale
        full_h = (REFINE_MARGIN * 2 + half_th) * scale
        area = screen[top * scale : top * scale + full_h, left * scale : left * scale + full_w]
        if area.shape[0] < 1 or area.shape[1] < 1:
            return None

        area_c = _resize_gray(
            Image.fromarray(area), area.shape[1] // scale, area.shape[0] // scale
        ).astype(np.float32)

        best_ncc = -1.0
        best_s = base_scale
        best_rx = best_ry = 0

        for s in _scale_steps(
            base_scale - SCALE_FINE_RADIUS, base_scale + SCALE_FINE_RADIUS, SCALE_FINE_STEP
        ):
            if s < SCALE_MIN or s > SCALE_MAX:
                continue
            stw = max(1, round(tw * s / scale))
            sth = max(1, round(th * s / scale))
            if stw > area_c.shape[1] or sth > area_c.shape[0]:
                continue
            template_c = _resize_gray(
                Image.fromarray(self._template), stw, sth
            ).astype(np.float32)

            map_f = _ncc_map(area_c, template_c)
            if map_f.size == 0:
                continue

            best_idx = int(np.argmax(map_f))
            value = float(map_f.flat[best_idx])
            if value > best_ncc:
                best_ncc = value
                best_s = s
                best_ry, best_rx = np.unravel_index(best_idx, map_f.shape)

        if best_ncc < self.confidence:
            return None

        x = (left + best_rx) * scale
        y = (top + best_ry) * scale
        return x, y, round(tw * best_s), round(th * best_s)

    def _refine_full(
        self, screen: np.ndarray, fx: int, fy: int, base_scale: float
    ) -> Optional[Region]:
        """Запасной путь: уточнение в полном разрешении для мелких шаблонов."""
        th, tw = self._template.shape
        sh, sw = screen.shape

        stw = max(1, round(tw * base_scale))
        sth = max(1, round(th * base_scale))

        margin_x = max(stw // 2, 24)
        margin_y = max(sth // 2, 24)
        left = max(0, fx - margin_x)
        top = max(0, fy - margin_y)
        area_w = min(sw - left, margin_x * 2 + stw)
        area_h = min(sh - top, margin_y * 2 + sth)

        if area_w < stw or area_h < sth:
            return None

        area = screen[top : top + area_h, left : left + area_w].astype(np.float32)

        best_ncc = -1.0
        best_s = base_scale
        best_rx = best_ry = 0

        for s in _scale_steps(
            base_scale - SCALE_FINE_RADIUS, base_scale + SCALE_FINE_RADIUS, SCALE_FINE_STEP
        ):
            if s < SCALE_MIN or s > SCALE_MAX:
                continue
            stw2 = max(1, round(tw * s))
            sth2 = max(1, round(th * s))
            if stw2 > area.shape[1] or sth2 > area.shape[0]:
                continue
            template_c = _resize_gray(
                Image.fromarray(self._template), stw2, sth2
            ).astype(np.float32)

            map_f = _ncc_map(area, template_c)
            if map_f.size == 0:
                continue

            best_idx = int(np.argmax(map_f))
            value = float(map_f.flat[best_idx])
            if value > best_ncc:
                best_ncc = value
                best_s = s
                best_ry, best_rx = np.unravel_index(best_idx, map_f.shape)

        if best_ncc < self.confidence:
            return None

        return left + best_rx, top + best_ry, round(tw * best_s), round(th * best_s)


__all__ = ["ButtonDetector"]
