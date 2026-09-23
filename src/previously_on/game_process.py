"""Detect whether the game is running, via psutil."""

from __future__ import annotations

import time
from collections.abc import Sequence

import psutil

from .games import GameProfile


def is_running(profile: GameProfile) -> bool:
    wanted = {n.lower() for n in profile.process_names}
    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower()
        if name in wanted:
            return True
    return False


def running_profile(profiles: Sequence[GameProfile]) -> GameProfile | None:
    """The first of ``profiles`` whose process is running, in one pass over
    the process table; None if none is."""
    names = {(proc.info.get("name") or "").lower() for proc in psutil.process_iter(["name"])}
    for profile in profiles:
        if any(n.lower() in names for n in profile.process_names):
            return profile
    return None


def wait_until(profile: GameProfile, running: bool, poll: float = 2.0) -> None:
    """Block until the game's running state equals ``running``."""
    while is_running(profile) != running:
        time.sleep(poll)


def lower_priority() -> None:
    """Let the game win CPU contention: below-normal class on Windows, nice 10 elsewhere."""
    import sys

    proc = psutil.Process()
    try:
        if sys.platform == "win32":
            proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            proc.nice(10)
    except Exception as exc:  # not fatal
        print(f"could not lower process priority: {exc}", file=sys.stderr)
