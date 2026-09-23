"""Recap records live beside the session log: ``<stamp>.recap.json`` next to
``<stamp>.jsonl``. The playthrough state is not a separate file — the newest
record's state is the current state, and each record carries the state as it
stood after its session, so re-running an old session re-chains cleanly.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..games import GameProfile
from ..session import default_data_dir, read_session
from ..stats import compute
from . import compact as compact_mod
from .prompt import SYSTEM, build_user
from .provider import RecapProvider
from .schema import PlaythroughState, RecapRecord
from .verify import verify

RECAP_SUFFIX = ".recap.json"


def session_id(session_path: Path) -> str:
    return session_path.name.removesuffix(".jsonl")


def recap_path(session_path: Path) -> Path:
    return session_path.with_name(session_id(session_path) + RECAP_SUFFIX)


def write_record(path: Path, record: RecapRecord) -> None:
    path.write_text(record.model_dump_json(indent=1), encoding="utf-8")


def read_record(path: Path) -> RecapRecord:
    return RecapRecord.model_validate_json(path.read_text(encoding="utf-8"))


def sessions_dir(game: str, data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "sessions" / game


def list_records(game: str, data_dir: Path | None = None) -> list[Path]:
    """Recap records for a game, oldest first (stamps sort chronologically)."""
    directory = sessions_dir(game, data_dir)
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"*{RECAP_SUFFIX}"))


def latest_record(game: str, data_dir: Path | None = None) -> tuple[Path, RecapRecord] | None:
    paths = list_records(game, data_dir)
    if not paths:
        return None
    return paths[-1], read_record(paths[-1])


def previous_state(session_path: Path) -> PlaythroughState:
    """State after the newest session that precedes this one, or empty."""
    me = session_id(session_path)
    older = [p for p in session_path.parent.glob(f"*{RECAP_SUFFIX}") if p.name.removesuffix(RECAP_SUFFIX) < me]
    if not older:
        return PlaythroughState()
    return read_record(max(older)).recap.state


def summarize_session(session_path: Path, profile: GameProfile, provider: RecapProvider) -> RecapRecord:
    """The one recap pass: read, compact, ask, verify, write. Returns the record."""
    meta, events = read_session(session_path)
    stats = compute(events, duration=meta.duration)
    sid = session_id(session_path)
    previous = previous_state(session_path)
    transcript = compact_mod.compact(meta, events, stats)
    user = build_user(profile.display_name, getattr(profile, "recap_notes", ""), sid, previous, transcript)
    recap, usage = provider.generate(SYSTEM, user)
    recap, dropped = verify(recap, events, previous, sid)
    record = RecapRecord(
        session=sid,
        game=meta.game,
        generated_at=datetime.now(),
        model=provider.model,
        usage=usage,
        recap=recap,
        dropped=dropped,
    )
    write_record(recap_path(session_path), record)
    return record


def summarize_after_run(session_path: Path, profile: GameProfile) -> tuple[RecapRecord | None, str]:
    """The end-of-session pass for live capture: never raises, because the
    session log is already safe on disk and nothing here may lose it.
    Returns the record (or ``None``) and a line saying what happened."""
    from .provider import RecapError, make_provider

    try:
        provider = make_provider()
        if not provider.has_credentials:
            return None, "no API credentials (OPENAI_API_KEY); skipping the recap — run `summarize` later"
        record = summarize_session(session_path, profile, provider)
    except RecapError as exc:
        return None, f"recap failed: {exc}"
    except Exception as exc:  # noqa: BLE001 - the log matters more than the recap
        return None, f"recap failed unexpectedly: {type(exc).__name__}: {exc}"
    message = f"recap written with {provider.model}"
    if record.dropped:
        message += f" ({len(record.dropped)} unverifiable details left out)"
    return record, message
