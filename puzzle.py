"""Guarded adapter for vsmutok/PuzzleCaptchaSolver (MIT, see third_party).

Only image analysis is usable before a real Warpath challenge is calibrated.
No network calls, challenge refreshes, or repeated guesses.
"""
from dataclasses import dataclass
import json
from pathlib import Path

import cv2
import numpy as np

from third_party.puzzle_captcha_solver.main import PuzzleCaptchaSolver


@dataclass(frozen=True)
class Match:
    x: int
    y: int
    score: float
    margin: float


def match_piece(piece, background, minimum_score=.20, minimum_margin=.08, exclude=None):
    if piece is None or background is None or piece.ndim != 3 or background.ndim != 3:
        raise ValueError('Нужны цветные изображения фрагмента и фона')
    if piece.shape[2] == 4 and np.any(piece[:, :, 3] == 0):
        # Ignore the faint transparent glow, which otherwise enlarges the template.
        points = cv2.findNonZero((piece[:, :, 3] > 100).astype(np.uint8))
        if points is None:
            raise ValueError('Фрагмент прозрачен')
        x, y, width, height = cv2.boundingRect(points)
        piece = piece[y:y+height, x:x+width, :3]
    else:
        piece = piece[:, :, :3]
    height, width = piece.shape[:2]
    if min(height, width) < 12 or height > background.shape[0] or width > background.shape[1]:
        raise ValueError('Некорректные размеры фрагмента')
    solver = PuzzleCaptchaSolver('', '', '')
    # Reuse upstream edge extraction; matching adds confidence and ambiguity checks.
    needle = solver.apply_edge_detection(piece)
    haystack = solver.apply_edge_detection(background[:, :, :3])
    if np.count_nonzero(needle) < 30 or np.std(haystack) < 1:
        raise ValueError('Недостаточно границ для распознавания пазла')
    if exclude is not None:
        left, top, right, bottom = exclude
        haystack[max(0, top):bottom, max(0, left):right] = 0
    scores = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
    _, best, _, point = cv2.minMaxLoc(scores)
    x, y = point
    competing = scores.copy()
    competing[max(0, y-height//2):y+height//2+1,
              max(0, x-width//2):x+width//2+1] = -1
    second = float(competing.max())
    margin = float(best - second)
    if not np.isfinite(best) or best < minimum_score or margin < minimum_margin:
        raise ValueError(f'Неуверенное совпадение пазла: {best:.2f}, отрыв {margin:.2f}')
    return Match(x, y, float(best), margin)


def analyze_frame(frame, profile):
    if frame is None or frame.shape[:2] != (1080, 1920):
        raise ValueError('Нужен снимок 1920 × 1080')
    def rectangle(name):
        value = profile.get(name)
        if (not isinstance(value, list) or len(value) != 4
                or any(type(n) is not int for n in value)):
            raise ValueError('Не настроена область: ' + name)
        x, y, right, bottom = value
        if not (0 <= x < right <= 1920 and 0 <= y < bottom <= 1080):
            raise ValueError('Область вне снимка: ' + name)
        return x, y, right, bottom
    bx, by, br, bb = rectangle('background')
    px, py, pr, pb = rectangle('piece')
    start, end = profile.get('slider_start'), profile.get('slider_end')
    for point in (start, end):
        if (not isinstance(point, list) or len(point) != 2
                or any(type(n) is not int for n in point)
                or not 0 <= point[0] < 1920 or not 0 <= point[1] < 1080):
            raise ValueError('Не настроены концы ползунка')
    if end[0] <= start[0] or abs(end[1] - start[1]) > 3:
        raise ValueError('Нужен горизонтальный ползунок слева направо')
    piece = frame[py:pb, px:pr]
    background = frame[by:bb, bx:br]
    exclude = None
    if bx <= px < pr <= br and by <= py < pb <= bb:
        exclude = (px-bx-2, py-by-2, pr-bx+2, pb-by+2)
    result = match_piece(piece, background, exclude=exclude)
    image_span = (br-bx) - (pr-px)
    image_delta = result.x - max(0, px-bx)
    if image_span <= 0 or not 3 <= image_delta <= image_span:
        raise ValueError('Сдвиг пазла выходит за допустимую область')
    target = round(start[0] + image_delta / image_span * (end[0] - start[0]))
    if not start[0] < target <= end[0]:
        raise ValueError('Конечная точка вне дорожки ползунка')
    return result, (start[0], start[1], target, start[1])


def load_profile(path):
    path = Path(path)
    if not path.exists():
        raise ValueError('Профиль пазла ещё не настроен по настоящему окну Warpath')
    profile = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(profile, dict) or profile.get('version') != 1:
        raise ValueError('Неизвестный формат профиля пазла')
    return profile
