"""Replay a recording through the system ``ffmpeg`` binary.

Preferred over OpenCV for video: it decodes whatever the system ffmpeg
supports (AV1 recordings from OBS, for one, which OpenCV's bundled build
cannot), and its ``fps`` filter does the down-sampling with correct
timestamps before frames ever reach Python.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

import numpy as np

from . import Frame


def available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def probe(path: Path) -> tuple[int, int, float]:
    """(width, height, duration_seconds) of the first video stream."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    info = json.loads(out)
    stream = info["streams"][0]
    return int(stream["width"]), int(stream["height"]), float(info["format"].get("duration", 0.0))


def _read_exact(stream, n: int) -> bytes | None:
    """Read exactly ``n`` bytes; ``None`` at EOF (a trailing partial frame is dropped)."""
    chunks = bytearray()
    while len(chunks) < n:
        chunk = stream.read(n - len(chunks))
        if not chunk:
            return None
        chunks += chunk
    return bytes(chunks)


class FfmpegVideoSource:
    name = "video"

    def __init__(
        self,
        path: str | Path,
        fps: float = 2.0,
        start: datetime | None = None,
        seek: float = 0.0,
        duration: float | None = None,
    ) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self.width, self.height, self.duration = probe(self.path)
        self.fps = fps
        self.seek = seek
        self.limit = duration
        self._start = start or datetime.now()
        self._proc: subprocess.Popen[bytes] | None = None

    def frames(self) -> Iterator[Frame]:
        cmd = ["ffmpeg", "-v", "error", "-nostdin"]
        if self.seek:
            cmd += ["-ss", f"{self.seek:.3f}"]
        cmd += ["-i", str(self.path)]
        if self.limit is not None:
            cmd += ["-t", f"{self.limit:.3f}"]
        cmd += ["-an", "-vf", f"fps={self.fps}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        stdout = self._proc.stdout
        assert stdout is not None
        frame_bytes = self.width * self.height * 3
        index = 0
        while True:
            buf = _read_exact(stdout, frame_bytes)
            if buf is None:
                break
            image = np.frombuffer(buf, np.uint8).reshape(self.height, self.width, 3)
            t = self.seek + index / self.fps
            yield Frame(index=index, ts=self._start + timedelta(seconds=t), t_rel=t, image=image)
            index += 1
        self.close()

    def close(self) -> None:
        if self._proc is not None:
            if self._proc.poll() is None:
                self._proc.kill()
            self._proc.wait()
            self._proc = None
