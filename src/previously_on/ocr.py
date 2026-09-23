"""OCR wrapper around RapidOCR (bundled ONNX models, no system deps)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class OcrLine:
    text: str
    conf: float
    # Bounding box as fractions of the crop it was read from (0..1).
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 1.0
    y1: float = 1.0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def width(self) -> float:
        return self.x1 - self.x0


def preprocess(crop: np.ndarray, min_height: int = 64) -> np.ndarray:
    """Upscale small crops; the recognizer is tuned for text ~32px tall."""
    h = crop.shape[0]
    if h < min_height:
        scale = min_height / h
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return crop


# RapidOCR's defaults are tuned for photos: the detector upscales every
# image until its short side is 736 px (a 1638x202 banner crop becomes
# ~5970x736), and an angle classifier runs on every box. HUD crops are
# already legible and never rotated, so cap the long side and skip the
# classifier: ~4x faster per call on the same crops, identical output.
DET_MAX_SIDE = 960


class Ocr:
    def __init__(self, threads: int = -1, det_max_side: int = DET_MAX_SIDE) -> None:
        """``threads``: CPU threads per ONNX session; -1 = all cores. Use 1-2
        when a game must keep the rest of the machine. ``det_max_side`` is
        for offline surveys that OCR a whole frame (small subtitles vanish at
        960); live capture keeps the default."""
        from rapidocr_onnxruntime import RapidOCR

        self._engine = RapidOCR(
            intra_op_num_threads=threads,
            inter_op_num_threads=1 if threads > 0 else -1,
            use_cls=False,
            det_limit_side_len=det_max_side,
            det_limit_type="max",
        )

    def read(self, crop: np.ndarray) -> list[OcrLine]:
        if crop.size == 0:
            return []
        image = preprocess(crop)
        h, w = image.shape[:2]
        result, _ = self._engine(image)
        if not result:
            return []
        lines: list[OcrLine] = []
        for box, text, conf in result:
            text = text.strip()
            if not text:
                continue
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            lines.append(
                OcrLine(
                    text=text,
                    conf=float(conf),
                    x0=min(xs) / w,
                    y0=min(ys) / h,
                    x1=max(xs) / w,
                    y1=max(ys) / h,
                )
            )
        return lines


@lru_cache(maxsize=2)
def get_ocr(threads: int = -1) -> Ocr:
    """Process-wide engine; model load is slow so tests without OCR never pay it."""
    return Ocr(threads=threads)
