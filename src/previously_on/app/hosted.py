"""Recaps without a key: the ``RecapProvider`` that asks previouslyon.gg.

The player's own key always wins. Without one, a signed-in app sends the
same user prompt the key path would (the compacted transcript and the
playthrough state before the session) to ``/v1/recap``; the server adds
its own copy of the system prompt, runs the model and returns the
``SessionRecap``. Verifying and writing the record stay here, in
``summarize_session``, exactly as with a key. The server keeps a count of
recaps per account (the plan's allowance), never the text.

It calls through ``account.request``, so it opens no connection of its own.
"""

from __future__ import annotations

import json

from ..recap.provider import RecapError, make_provider
from ..recap.schema import SessionRecap, Usage
from .account import Account, AccountError, request

TIMEOUT = 180  # a long session's recap takes a minute or more


class HostedProvider:
    def __init__(self, account: Account) -> None:
        self._account = account
        self.model = "previouslyon.gg"  # the server's model, once it answers

    @property
    def has_credentials(self) -> bool:
        return bool(self._account.token())

    def generate(self, system: str, user: str) -> tuple[SessionRecap, Usage]:
        token = self._account.token()
        if not token:
            raise RecapError("not signed in to previouslyon.gg")
        try:
            status, body = request("POST", "/v1/recap", token=token, json_body={"user": user}, timeout=TIMEOUT)
        except AccountError as exc:
            raise RecapError(str(exc)) from exc
        try:
            reply = json.loads(body or b"{}")
        except ValueError:
            reply = {}
        if status == 200:
            try:
                recap = SessionRecap.model_validate(reply["recap"])
                usage = Usage.model_validate(reply.get("usage") or {})
            except (KeyError, ValueError) as exc:
                raise RecapError("previouslyon.gg sent a recap this version can't read; update the app") from exc
            self.model = str(reply.get("model") or self.model)
            return recap, usage
        if status == 401:
            self._account.forget()
            raise RecapError("signed out of previouslyon.gg; sign in again under Settings → Account")
        detail = reply.get("detail") if isinstance(reply, dict) else None
        if status == 402 and isinstance(detail, dict) and detail.get("error") == "hosted_quota":
            raise RecapError(quota_message(detail))
        message = detail if isinstance(detail, str) else f"previouslyon.gg answered {status}"
        raise RecapError(message)


def quota_message(q: dict) -> str:
    if q.get("plan") == "free":
        return (f"the {q.get('limit')} free recaps from previouslyon.gg are used; "
                "add your own API key in Settings, or go Premium")
    return f"this year's {q.get('limit')} recaps from previouslyon.gg are used; add your own API key in Settings"


def pick_provider(account: Account | None):
    """The player's key if there is one, else their account, else the key
    path (which says there are no credentials)."""
    try:
        own = make_provider()
    except RecapError:  # misconfigured credentials: the account can still write it
        own = None
    if own is not None and own.has_credentials:
        return own
    if account is not None and account.token():
        return HostedProvider(account)
    if own is None:
        raise RecapError("no usable API credentials and not signed in")
    return own


def quota(account: Account) -> dict | None:
    """What the account has left, for Settings; ``None`` when offline."""
    token = account.token()
    if not token:
        return None
    try:
        status, body = request("GET", "/v1/recap/quota", token=token)
    except AccountError:
        return None
    return json.loads(body) if status == 200 else None
