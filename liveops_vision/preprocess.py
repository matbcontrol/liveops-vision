"""Подготовка картинок перед моделью: OpenCV, без сети.

- дубли: почти одинаковые скриншоты (один экран, снятый дважды) ищутся по
  разностному хэшу и не отправляются в модель повторно;
- размер: картинка уменьшается до заданной длинной стороны, потому что цена
  картинки в токенах растёт с числом пикселей, а не с объёмом информации;
- видео: из геймплейной записи берутся только кадры, где экран заметно сменился;
- сравнение двух версий экрана: области, которые изменились.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


def load(path: str | Path) -> np.ndarray:
    """BGR-картинка; imdecode вместо imread, чтобы работали пути с кириллицей."""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"не читается как картинка: {path}")
    return img


def dhash(img: np.ndarray, size: int = 16) -> int:
    """Разностный хэш: устойчив к сжатию и небольшому изменению размера."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


@dataclass
class Signature:
    """Форма экрана (разностный хэш) и его цвета (миниатюра 16×16).

    Одного хэша мало: всплывающие окна разных событий одной игры часто сделаны
    по одному шаблону и отличаются только картинкой и цветом.
    """

    shape: int
    thumb: np.ndarray


def signature(img: np.ndarray) -> Signature:
    return Signature(dhash(img), cv2.resize(img, (16, 16), interpolation=cv2.INTER_AREA).astype(np.int16))


def similar(a: Signature, b: Signature, max_shape: int = 10, max_color: float = 12.0) -> bool:
    return hamming(a.shape, b.shape) <= max_shape and float(np.abs(a.thumb - b.thumb).mean()) <= max_color


def dedupe(signatures: dict[str, Signature]) -> dict[str, str]:
    """Для каждого id возвращает id первого почти такого же снимка (сам себя, если он первый)."""
    keep: list[tuple[str, Signature]] = []
    owner: dict[str, str] = {}
    for key, sig in signatures.items():
        match = next((k for k, ks in keep if similar(sig, ks)), None)
        if match is None:
            keep.append((key, sig))
            owner[key] = key
        else:
            owner[key] = match
    return owner


def fit(img: np.ndarray, max_side: int | None) -> np.ndarray:
    """Уменьшает так, чтобы длинная сторона была не больше max_side. Не увеличивает."""
    if not max_side:
        return img
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale >= 1:
        return img
    return cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)


def encode(img: np.ndarray, fmt: str = ".png") -> bytes:
    ok, buf = cv2.imencode(fmt, img)
    if not ok:
        raise ValueError("не удалось закодировать картинку")
    return buf.tobytes()


def estimate_image_tokens(width: int, height: int, patch: int = 28) -> int:
    """Грубая оценка: около одного токена на квадрат 28×28 пикселей. Точную цифру даёт usage ответа."""
    return max(1, round(width * height / (patch * patch)))


@dataclass
class Keyframe:
    index: int
    seconds: float
    image: np.ndarray


def keyframes(video_path: str | Path, every_s: float = 0.5, max_frames: int = 200) -> list[Keyframe]:
    """Кадры, где экран заметно сменился по форме или по цвету по сравнению с последним взятым."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"видео не открывается: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(fps * every_s))
    out: list[Keyframe] = []
    last: Signature | None = None
    index = 0
    while len(out) < max_frames:
        ok = cap.grab()
        if not ok:
            break
        if index % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                sig = signature(frame)
                if last is None or not similar(sig, last):
                    out.append(Keyframe(index, index / fps, frame))
                    last = sig
        index += 1
    cap.release()
    return out


def changed_regions(before: np.ndarray, after: np.ndarray, min_area_ratio: float = 0.002) -> list[tuple[int, int, int, int]]:
    """Прямоугольники (x, y, w, h) на картинке after, где она отличается от before.

    Картинки приводятся к одному размеру; мелкий шум и сжатие убирает размытие и порог.
    """
    h, w = after.shape[:2]
    b = cv2.resize(before, (w, h), interpolation=cv2.INTER_AREA)
    diff = cv2.absdiff(cv2.GaussianBlur(b, (5, 5), 0), cv2.GaussianBlur(after, (5, 5), 0))
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)
    mask = cv2.dilate(mask, np.ones((9, 9), np.uint8), iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = min_area_ratio * w * h
    boxes = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) >= min_area]
    return sorted(boxes, key=lambda r: r[2] * r[3], reverse=True)
