"""Frame sources.

Everything downstream consumes ``Frame`` objects, so the detector can run on
a live monitor, a recorded video, or a folder of screenshots interchangeably.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Protocol

import numpy as np


@dataclass(slots=True)
class Frame:
    index: int
    ts: datetime  # wall-clock (live) or synthetic (replay)
    t_rel: float  # seconds since the source started
    image: np.ndarray  # BGR, HxWx3


class FrameSource(Protocol):
    name: str

    def frames(self) -> Iterator[Frame]: ...

    def close(self) -> None: ...


def open_screen(fps: float = 2.0, monitor: int = 1) -> FrameSource:
    """Best live source for this platform.

    Windows: DXGI desktop duplication (sees exclusive-fullscreen games),
    falling back to GDI via mss. Elsewhere: mss.
    """
    import sys

    if sys.platform == "win32":
        try:
            from .dxcam_source import DxcamSource

            return DxcamSource(fps=fps, monitor=monitor)
        except Exception as exc:  # dxcam missing or no output: fall back
            print(f"dxcam unavailable ({exc}); falling back to mss", file=sys.stderr)
    from .mss_source import MssSource

    return MssSource(fps=fps, monitor=monitor)


def open_source(
    kind: str,
    path: str | None = None,
    fps: float = 2.0,
    monitor: int = 1,
    seek: float = 0.0,
    duration: float | None = None,
) -> FrameSource:
    if kind == "screen":
        return open_screen(fps=fps, monitor=monitor)
    if kind == "mss":
        from .mss_source import MssSource

        return MssSource(fps=fps, monitor=monitor)
    if kind == "dxcam":
        from .dxcam_source import DxcamSource

        return DxcamSource(fps=fps, monitor=monitor)
    if kind == "video":
        if not path:
            raise ValueError("--path is required for --source video")
        from . import ffmpeg_source

        if ffmpeg_source.available():
            return ffmpeg_source.FfmpegVideoSource(path, fps=fps, seek=seek, duration=duration)
        if seek or duration is not None:
            raise ValueError("--start/--duration need ffmpeg on PATH")
        from .video_source import VideoSource

        return VideoSource(path, fps=fps)
    if kind == "images":
        if not path:
            raise ValueError("--path is required for --source images")
        from .image_source import ImageDirSource

        return ImageDirSource(path, fps=fps)
    raise ValueError(f"unknown source kind: {kind!r}")
