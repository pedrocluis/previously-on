"""One session as a zip to attach to a GitHub issue: the event log, the recap
record beside it, and a README saying what the player is looking at.

Text only, and nothing the log does not already hold: no frame, no
screenshot, no API key, no path from the player's disk. There is no
telemetry, so this is how a "that's wrong" reaches the classifier.
"""

from __future__ import annotations

import platform
import sys
import zipfile
from pathlib import Path

from . import __version__
from .recap.store import recap_path, session_id, sessions_dir
from .session import read_session

ISSUE_URL = "https://github.com/pedrocluis/previously-on/issues/new?template=wrong-event.yml"


def filename(game: str, stamp: str) -> str:
    return f"previously-on-{game}-{stamp}.zip"


def find_session(game: str, stamp: str, data_dir: Path | None = None) -> Path:
    log = sessions_dir(game, data_dir) / f"{stamp}.jsonl"
    if not log.is_file():
        raise FileNotFoundError(f"no session {stamp} for {game}")
    return log


def readme(log: Path) -> str:
    meta, events = read_session(log)
    has_recap = recap_path(log).is_file()
    frozen = "Windows bundle" if getattr(sys, "frozen", False) else "from source"
    return "\n".join(
        [
            "Previously On — one exported session",
            "",
            f"game:      {meta.game}",
            f"session:   {session_id(log)}",
            f"events:    {len(events)}",
            f"recap:     {'yes' if has_recap else 'no'}",
            f"version:   {__version__} ({frozen})",
            f"platform:  {platform.system()} {platform.release()}, Python {platform.python_version()}",
            "",
            "Files:",
            f"  {log.name}  the event log: every line the screen showed that became an event,",
            "      with its time, type, the text as read and the raw OCR lines.",
            *(
                [f"  {recap_path(log).name}  the recap written from that log (the text the model returned)."]
                if has_recap
                else []
            ),
            "",
            "Nothing else: no frame, no screenshot, no API key, no settings.",
            "",
            "In the issue, say which event is wrong (its # on the session page or its time)",
            "and what the screen actually showed, or what is missing and roughly when.",
            f"New issue: {ISSUE_URL}",
            "",
        ]
    )


def write(log: Path, dest: Path) -> Path:
    """Zip ``log`` and its recap into ``dest`` (``.zip`` added if missing)."""
    if dest.suffix.lower() != ".zip":
        dest = dest.with_name(dest.name + ".zip")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", readme(log))
        z.write(log, log.name)
        recap = recap_path(log)
        if recap.is_file():
            z.write(recap, recap.name)
    return dest
