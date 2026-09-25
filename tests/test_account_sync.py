import os
import time
from datetime import datetime, timedelta

import pytest

from previously_on.app.account import API_ENV, TOKEN_KEY, Account
from previously_on.app.api import Api
from previously_on.app.config import AppConfig
from previously_on.app.sync import SyncWorker, is_open
from previously_on.events import Event, EventType
from previously_on.games import get_profile
from previously_on.session import SessionLog, sessions_dir

from .fake_api import TOKEN, FakeApi, MemoryStore

GAME = "eldenring"


@pytest.fixture
def fake(monkeypatch):
    api = FakeApi()
    monkeypatch.setenv(API_ENV, api.url)
    yield api
    api.close()


def signed_in() -> Account:
    store = MemoryStore()
    store.set(TOKEN_KEY, TOKEN)
    return Account(store, open_browser=lambda url: None, sleep=lambda s: None)


def write(tmp_path, started: datetime, closed: bool = True):
    log = SessionLog.open(GAME, "live", data_dir=tmp_path, started=started.replace(microsecond=0))
    log.append(Event(ts=started, t_rel=5, type=EventType.DEATH, text="YOU DIED", conf=0.9, region="r"))
    if closed:
        log.close(played=60)
    else:
        log._fh.close()
    return log.path


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


# --- sign-in ------------------------------------------------------------------


def test_link_stores_the_token_and_syncs(fake):
    opened, signed = [], []
    store = MemoryStore()
    account = Account(store, open_browser=opened.append, on_signed_in=lambda: signed.append(1), sleep=lambda s: None)
    link = account.begin_link()
    assert link["state"] == "waiting" and link["user_code"] == "BCDF-GHJK"
    assert opened == ["https://previouslyon.gg/link?code=BCDF-GHJK"]
    wait_for(lambda: account.status()["link"]["state"] == "done")
    assert store.values[TOKEN_KEY] == TOKEN
    assert account.status() == {"signed_in": True, "account": "player@example.com",
                                "link": {"state": "done", "account": "player@example.com"}}
    assert signed == [1]
    assert fake.device_name  # the PC's name, shown on /account


def test_link_denied_in_the_browser(fake):
    fake.deny = True
    account = Account(MemoryStore(), open_browser=lambda url: None, sleep=lambda s: None)
    account.begin_link()
    wait_for(lambda: account.status()["link"]["state"] == "failed")
    assert not account.status()["signed_in"]


def test_sign_out_revokes_and_forgets(fake):
    account = signed_in()
    account.sign_out()
    assert fake.revoked and ("DELETE", "/v1/device") in fake.calls
    assert account.token() is None


def test_sign_out_offline_still_forgets(monkeypatch):
    monkeypatch.setenv(API_ENV, "http://127.0.0.1:9")  # nothing listens
    account = signed_in()
    account.sign_out()
    assert account.token() is None


# --- sync ------------------------------------------------------------------------


def test_reconcile_uploads_downloads_and_skips(fake, tmp_path):
    now = datetime.now()
    closed = write(tmp_path, now - timedelta(days=1))
    recap = closed.with_name(closed.stem + ".recap.json")
    recap.write_text('{"recap": 1}')
    still_open = write(tmp_path, now, closed=False)
    too_old = write(tmp_path, now - timedelta(days=40))
    fake.files[(GAME, "20260101-120000.jsonl")] = b'{"kind": "session_start"}\n'
    fake.files[(GAME, "20260101-120000.recap.json")] = b"{}"

    worker = SyncWorker(signed_in(), tmp_path, lambda: [GAME])
    assert worker.reconcile(GAME) == {"up": 2, "down": 2, "skipped": 1}
    assert fake.files[(GAME, closed.name)] == closed.read_bytes()
    assert fake.files[(GAME, recap.name)] == recap.read_bytes()
    assert (GAME, still_open.name) not in fake.files and (GAME, too_old.name) not in fake.files
    d = sessions_dir(GAME, tmp_path)
    assert (d / "20260101-120000.jsonl").read_bytes() == b'{"kind": "session_start"}\n'
    assert not list(d.glob("*.part"))
    assert worker.status()["message"] == "2 uploaded, 2 downloaded, 1 too old for the free plan"

    # Level now: a second pass sends nothing.
    puts = sum(1 for m, _ in fake.calls if m == "PUT")
    assert worker.reconcile(GAME) == {"up": 0, "down": 0, "skipped": 1}
    assert sum(1 for m, _ in fake.calls if m == "PUT") == puts


def test_a_changed_recap_is_uploaded_again(fake, tmp_path):
    log = write(tmp_path, datetime.now() - timedelta(hours=2))
    recap = log.with_name(log.stem + ".recap.json")
    recap.write_text("{}")
    worker = SyncWorker(signed_in(), tmp_path, lambda: [GAME])
    worker.reconcile(GAME)
    recap.write_text('{"rewritten": true}')
    assert worker.reconcile(GAME)["up"] == 1
    assert fake.files[(GAME, recap.name)] == b'{"rewritten": true}'


def test_revoked_on_the_website_signs_out(fake, tmp_path):
    fake.revoked = True
    account = signed_in()
    worker = SyncWorker(account, tmp_path, lambda: [GAME])
    worker.reconcile(GAME)
    assert account.token() is None
    assert worker.status()["state"] == "signed_out"


def test_offline_is_an_error_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setenv(API_ENV, "http://127.0.0.1:9")
    worker = SyncWorker(signed_in(), tmp_path, lambda: [GAME])
    worker.reconcile(GAME)
    assert worker.status()["state"] == "error" and "previouslyon.gg" in worker.status()["message"]


def test_enqueue_only_syncs_turned_on_games(fake, tmp_path):
    write(tmp_path, datetime.now() - timedelta(hours=1))
    enabled: list[str] = []
    worker = SyncWorker(signed_in(), tmp_path, lambda: enabled)
    worker.enqueue(GAME)
    time.sleep(0.1)
    assert not fake.calls
    enabled.append(GAME)
    worker.enqueue(GAME)
    wait_for(lambda: worker.status()["state"] == "done")
    assert any(m == "PUT" for m, _ in fake.calls)


def test_a_crashed_log_is_open_only_for_a_while(tmp_path):
    log = write(tmp_path, datetime.now(), closed=False)
    assert is_open(log)
    old = time.time() - 3600
    os.utime(log, (old, old))
    assert not is_open(log)
    assert not is_open(write(tmp_path, datetime.now() - timedelta(minutes=5)))


# --- the window's side -------------------------------------------------------------


def test_settings_turn_a_game_on(fake, tmp_path):
    account = signed_in()
    worker = SyncWorker(account, tmp_path, lambda: [])
    cfg_path = tmp_path / "config.json"
    api = Api(get_profile(GAME), tmp_path, None, AppConfig(), cfg_path, account=account, sync=worker)
    s = api.set_sync_game(GAME, True)
    assert s["sync_games"] == [GAME] and s["signed_in"]
    assert AppConfig.load(cfg_path).sync_games == [GAME]
    assert api.set_sync_game(GAME, False)["sync_games"] == []
    assert "error" in api.set_sync_game("pong", True)


def test_open_url_allows_the_site(tmp_path, monkeypatch):
    import webbrowser

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    api = Api(get_profile(GAME), tmp_path, None, AppConfig())
    assert api.open_url("https://previouslyon.gg/account") == {"opened": True}
    assert "error" in api.open_url("https://previouslyon.gg.evil.test/")
    assert "error" in api.open_url("https://example.com/")
    assert api.account_status() == {"available": False}


def test_offline_retries_by_itself(fake, monkeypatch, tmp_path):
    write(tmp_path, datetime.now() - timedelta(hours=1))
    monkeypatch.setenv(API_ENV, "http://127.0.0.1:9")
    worker = SyncWorker(signed_in(), tmp_path, lambda: [GAME], retry_delays=(0.2,))
    worker.reconcile(GAME)
    assert worker.status()["state"] == "error" and "Trying again in 0 s" in worker.status()["message"]
    monkeypatch.setenv(API_ENV, fake.url)  # back online before the retry fires
    wait_for(lambda: worker.status()["state"] == "done")
    assert any(m == "PUT" for m, _ in fake.calls)


def test_a_full_account_is_said_and_not_retried(fake, tmp_path):
    fake.full = True
    write(tmp_path, datetime.now() - timedelta(hours=1))
    worker = SyncWorker(signed_in(), tmp_path, lambda: [GAME], retry_delays=(0.05,))
    worker.reconcile(GAME)
    assert worker.status()["message"].startswith("Your account is full (100 MB)")
    puts = sum(1 for m, _ in fake.calls if m == "PUT")
    time.sleep(0.3)
    assert sum(1 for m, _ in fake.calls if m == "PUT") == puts


def test_a_bad_stamp_from_the_server_is_never_a_path(fake, tmp_path):
    fake.extra_sessions = [{"stamp": "../../escape", "log_sha256": "x", "recap_sha256": None}]
    fake.files[(GAME, "escape.jsonl")] = b"x"  # what the download asks for
    worker = SyncWorker(signed_in(), tmp_path, lambda: [GAME])
    worker.reconcile(GAME)
    assert not list(tmp_path.rglob("escape*"))
    assert not (tmp_path.parent / "escape.jsonl").exists()
