"""Cloud sync: each session's ``.jsonl`` and ``.recap.json``, for the games
the player turned on, to and from their previouslyon.gg account. Nothing
else is ever sent: no frame, no key, no setting.

Logs are append-only and named by stamp, and a log is uploaded only once
its ``session_end`` is written, so there is nothing to merge. A pass over
one game (``reconcile``) compares SHA-256s with the account's list:
anything missing or changed there is uploaded whole; any session the
account has and this PC doesn't is downloaded (a second PC, a
reinstall). A file here is never overwritten by the account's copy.

One daemon thread works through a queue of games. The capture loop queues
the game when a session ends and again when its recap is written; opening
the app, signing in and "Sync now" queue every game that syncs. A pass
that is interrupted is simply redone next time. A pass that fails because
the server can't be reached is retried by itself, backing off from 30
seconds to 30 minutes; one the server refused (the account is full, say)
waits for the player.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path

from ..recap.store import RECAP_SUFFIX
from ..session import sessions_dir
from .account import Account, AccountError, request

OPEN_GRACE = 600.0  # a log with no session_end, untouched this long, was left by a crash
STAMP = re.compile(r"\d{8}-\d{6}")  # a session's file name; anything else from the server is ignored
RETRY_DELAYS = (30.0, 120.0, 600.0, 1800.0)  # seconds, after the 1st, 2nd, 3rd, later failures


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_open(log: Path, now: float | None = None) -> bool:
    """Still being written: no ``session_end`` yet and touched recently."""
    with log.open("rb") as fh:
        fh.seek(max(0, log.stat().st_size - 4096))
        tail = fh.read().decode("utf-8", "replace").strip().splitlines()
    if tail and '"session_end"' in tail[-1]:
        return False
    return (now or time.time()) - log.stat().st_mtime < OPEN_GRACE


def stamp_time(stamp: str) -> datetime | None:
    try:
        return datetime.strptime(stamp, "%Y%m%d-%H%M%S")
    except ValueError:
        return None


class SyncWorker:
    def __init__(
        self,
        account: Account,
        data_dir: Path | None,
        enabled: Callable[[], Iterable[str]],
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
    ) -> None:
        self._account = account
        self._retry_delays = retry_delays
        self._failures: dict[str, int] = {}
        self._retries: dict[str, threading.Timer] = {}
        self._data_dir = data_dir
        self._enabled = enabled
        self._queue: queue.Queue[str] = queue.Queue()
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._status: dict = {"state": "idle", "message": "", "last": None}
        self._thread: threading.Thread | None = None

    # --- the queue -------------------------------------------------------------

    def enqueue(self, game: str) -> None:
        """Sync ``game`` soon, if it syncs and the app is signed in."""
        if game not in set(self._enabled()) or not self._account.token():
            return
        with self._lock:
            if game in self._pending:
                return
            self._pending.add(game)
        self._queue.put(game)
        self._ensure_thread()

    def enqueue_all(self) -> None:
        for game in self._enabled():
            self.enqueue(game)

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="sync", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                game = self._queue.get(timeout=30)
            except queue.Empty:
                return  # restarted by the next enqueue
            with self._lock:
                self._pending.discard(game)
            self.reconcile(game)

    def status(self) -> dict:
        return dict(self._status)

    def _set(self, state: str, message: str) -> None:
        self._status = {"state": state, "message": message,
                        "last": datetime.now().isoformat(timespec="seconds") if state != "syncing" else
                        self._status.get("last")}

    # --- one pass ------------------------------------------------------------------

    def reconcile(self, game: str) -> dict:
        """Bring this PC and the account level for one game. Returns counts."""
        token = self._account.token()
        if not token:
            self._set("signed_out", "Not signed in.")
            return {}
        self._set("syncing", "Syncing…")
        try:
            counts = self._reconcile(game, token)
        except _Revoked:
            self._account.forget()
            self._set("signed_out", "Signed out: this PC was removed from the account.")
            return {}
        except _Refused as e:
            self._set("error", str(e))
            return {}
        except AccountError as e:  # unreachable or a server error: try again by itself
            delay = self._retry(game)
            self._set("error", f"{e}. Trying again in {_minutes(delay)}.")
            return {}
        except OSError as e:
            self._set("error", f"couldn't read or write a session file: {e}")
            return {}
        self._failures.pop(game, None)
        parts = []
        if counts["up"]:
            parts.append(f"{counts['up']} uploaded")
        if counts["down"]:
            parts.append(f"{counts['down']} downloaded")
        if counts["skipped"]:
            parts.append(f"{counts['skipped']} too old for the free plan")
        self._set("done", ", ".join(parts) or "Up to date.")
        return counts

    def _retry(self, game: str) -> float:
        n = self._failures.get(game, 0)
        self._failures[game] = n + 1
        delay = self._retry_delays[min(n, len(self._retry_delays) - 1)]
        old = self._retries.pop(game, None)
        if old is not None:
            old.cancel()
        timer = threading.Timer(delay, self.enqueue, args=(game,))
        timer.daemon = True
        timer.start()
        self._retries[game] = timer
        return delay

    def _call(self, method: str, path: str, token: str, **kw) -> tuple[int, bytes]:
        status, body = request(method, path, token=token, **kw)
        if status == 401:
            raise _Revoked
        if status == 413:
            detail = _json(body).get("detail") or {}
            size = detail.get("max_bytes", 0) // (1024 * 1024) if isinstance(detail, dict) else 0
            raise _Refused(f"Your account is full ({size} MB). Delete a game from your account page to make room.")
        return status, body

    def _reconcile(self, game: str, token: str) -> dict:
        status, body = self._call("GET", f"/v1/sync/{game}", token)
        if status != 200:
            raise _Refused(f"sync failed ({status})")
        manifest = json.loads(body)
        # Stamps become file names here, so only well-formed ones are used.
        remote = {s["stamp"]: s for s in manifest.get("sessions", []) if STAMP.fullmatch(str(s.get("stamp", "")))}
        days = manifest.get("retention_days")
        cutoff = datetime.now() - timedelta(days=days) if days else None
        directory = sessions_dir(game, self._data_dir)
        counts = {"up": 0, "down": 0, "skipped": 0}

        logs = sorted(directory.glob("*.jsonl")) if directory.is_dir() else []
        for log in logs:
            stamp = log.stem
            if is_open(log):
                continue
            started = stamp_time(stamp)
            if cutoff is not None and started is not None and started < cutoff:
                if stamp not in remote:
                    counts["skipped"] += 1
                continue
            there = remote.get(stamp, {})
            if there.get("log_sha256") != sha256(log):
                status, body = self._call("PUT", f"/v1/sync/{game}/{log.name}", token, data=log.read_bytes())
                if status == 403:  # outside the plan's window after all
                    counts["skipped"] += 1
                    continue
                if status != 200:
                    raise _Refused(f"upload of {log.name} failed ({status}): {_detail(body)}")
                counts["up"] += 1
            recap = log.with_name(stamp + RECAP_SUFFIX)
            if recap.is_file() and there.get("recap_sha256") != sha256(recap):
                status, body = self._call("PUT", f"/v1/sync/{game}/{recap.name}", token, data=recap.read_bytes())
                if status != 200:
                    raise _Refused(f"upload of {recap.name} failed ({status}): {_detail(body)}")
                counts["up"] += 1

        for stamp, there in remote.items():
            log = directory / f"{stamp}.jsonl"
            recap = directory / f"{stamp}{RECAP_SUFFIX}"
            if not log.exists():
                counts["down"] += self._download(game, log, token)
            if there.get("recap_sha256") and not recap.exists():
                counts["down"] += self._download(game, recap, token)
        return counts

    def _download(self, game: str, dest: Path, token: str) -> int:
        status, body = self._call("GET", f"/v1/sync/{game}/{dest.name}", token)
        if status == 404:
            return 0
        if status != 200:
            raise _Refused(f"download of {dest.name} failed ({status})")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(body)
        os.replace(tmp, dest)
        return 1


class _Revoked(Exception):
    pass


class _Refused(AccountError):
    """The server answered and said no; trying again won't change that."""


def _json(body: bytes) -> dict:
    try:
        out = json.loads(body)
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


def _detail(body: bytes) -> str:
    detail = _json(body).get("detail")
    if detail is None:
        return ""
    return detail if isinstance(detail, str) else json.dumps(detail)


def _minutes(seconds: float) -> str:
    return f"{round(seconds)} s" if seconds < 60 else f"{round(seconds / 60)} min"
