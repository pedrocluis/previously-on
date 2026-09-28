"""Recaps without a key: the app asks previouslyon.gg (tests/fake_api.py)."""

from datetime import datetime

import pytest

from previously_on.app.account import API_ENV, TOKEN_KEY, Account
from previously_on.games import get_profile
from previously_on.app.hosted import HostedProvider, pick_provider, quota
from previously_on.recap.provider import FakeProvider, RecapError
from previously_on.recap.schema import PlaythroughState, SessionRecap
from previously_on.recap.store import read_record, recap_path, summarize_after_run

from .fake_api import TOKEN, FakeApi, MemoryStore
from .test_account_sync import GAME, write

RECAP = SessionRecap(summary="s", short_recap="sh", full_recap="f", state=PlaythroughState(location="Limgrave"))


@pytest.fixture
def fake(monkeypatch):
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "PREVIOUSLY_ON_MODEL"):
        monkeypatch.delenv(var, raising=False)
    api = FakeApi()
    monkeypatch.setenv(API_ENV, api.url)
    yield api
    api.close()


def account(signed_in: bool = True) -> Account:
    store = MemoryStore()
    if signed_in:
        store.set(TOKEN_KEY, TOKEN)
    return Account(store, open_browser=lambda url: None, sleep=lambda s: None)


def test_writes_the_recap_through_the_account_and_records_the_model(fake, tmp_path):
    fake.recap = RECAP.model_dump()
    log = write(tmp_path, datetime(2026, 9, 20, 20, 0))
    acct = account()
    record, message = summarize_after_run(log, get_profile(GAME), make=lambda: pick_provider(acct))
    assert record is not None, message
    assert record.model == "gpt-5.4-mini"
    kept = read_record(recap_path(log))
    assert kept.recap.summary == "s"
    # Verified here, as with a key: the fake log never reached Limgrave.
    assert kept.recap.state.location is None and kept.dropped == ["location 'Limgrave': not in the log"]
    # The user prompt only: the transcript, never a system prompt or a key.
    assert len(fake.recap_prompts) == 1 and "Transcript of this session" in fake.recap_prompts[0]


def test_a_used_up_allowance_says_so(fake):
    with pytest.raises(RecapError, match="3 free recaps"):
        HostedProvider(account()).generate("system", "user")


def test_a_revoked_device_signs_the_app_out(fake):
    fake.revoked = True
    acct = account()
    with pytest.raises(RecapError, match="signed out"):
        HostedProvider(acct).generate("system", "user")
    assert acct.token() is None


def test_the_players_key_wins(fake, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert not isinstance(pick_provider(account()), HostedProvider)


def test_without_key_or_account_nothing_is_sent(fake, tmp_path):
    assert not pick_provider(account(signed_in=False)).has_credentials
    assert isinstance(pick_provider(account()), HostedProvider)
    assert fake.calls == []


def test_quota_for_settings(fake):
    assert quota(account()) == {"plan": "free", "used": 1, "limit": 3}
    assert quota(account(signed_in=False)) is None


def test_the_default_factory_is_unchanged(tmp_path):
    """The CLI and tests still pass a provider or use the key path."""
    log = write(tmp_path, datetime(2026, 9, 20, 20, 0))
    record, _ = summarize_after_run(log, get_profile(GAME), make=lambda: FakeProvider(RECAP))
    assert record is not None and record.model == "fake"
