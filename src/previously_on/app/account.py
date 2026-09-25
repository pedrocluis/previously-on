"""Signing the app in to a previouslyon.gg account, the way a TV app does.

``begin_link`` asks the API for a code and opens ``previouslyon.gg/link``
in the browser; the player confirms there; a background poll receives the
device token. The token lives in the OS credential store (Windows
Credential Manager through ``keyring``), never in ``config.json``; if
there is no credential store the app says so rather than write it
anywhere else.

This and ``sync.py`` are the only modules besides ``recap/provider.py``
that make network requests, and only once the player signs in. The
website's /privacy page says what they send.
"""

from __future__ import annotations

import json
import os
import platform
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from typing import Protocol

from .. import __version__

API_ENV = "PREVIOUSLY_ON_API"
DEFAULT_API = "https://api.previouslyon.gg"
KEYRING_SERVICE = "previously-on"
TOKEN_KEY = "device-token"
ACCOUNT_KEY = "account"
TIMEOUT = 20


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The API never redirects; following one would carry the device token
    (``Authorization``) to wherever it points."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def api_base() -> str:
    return os.environ.get(API_ENV, DEFAULT_API).rstrip("/")


class AccountError(Exception):
    """Shown to the player as is."""


class SignedOut(AccountError):
    """The token was revoked (from /account) or never existed."""


class TokenStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...


class KeyringStore:
    """The OS credential store. Imported lazily: most runs never sign in."""

    def _keyring(self):
        import keyring
        from keyring.backends import fail

        if isinstance(keyring.get_keyring(), fail.Keyring):
            raise AccountError("this system has no credential store to keep the sign-in in")
        return keyring

    def get(self, key: str) -> str | None:
        try:
            return self._keyring().get_password(KEYRING_SERVICE, key)
        except AccountError:
            return None

    def set(self, key: str, value: str) -> None:
        self._keyring().set_password(KEYRING_SERVICE, key, value)

    def delete(self, key: str) -> None:
        from keyring.errors import PasswordDeleteError

        try:
            self._keyring().delete_password(KEYRING_SERVICE, key)
        except (PasswordDeleteError, AccountError):
            pass


def request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    json_body: dict | None = None,
    data: bytes | None = None,
    base: str | None = None,
) -> tuple[int, bytes]:
    """One call to the API: (status, body). A 4xx comes back as a status; a
    network failure raises ``AccountError``."""
    headers = {"User-Agent": f"previously-on/{__version__}"}
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif data is not None:
        headers["Content-Type"] = "application/octet-stream"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request((base or api_base()) + path, data=data, method=method, headers=headers)
    try:
        with _opener.open(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            raise AccountError(f"previouslyon.gg answered {e.code}; try again later") from None
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AccountError(f"can't reach previouslyon.gg ({getattr(e, 'reason', e)})") from None


def device_name() -> str:
    return (platform.node() or "Desktop app")[:64]


class Account:
    """Sign-in state, and the sign-in in progress. Thread-safe enough for a
    page polling ``status`` every two seconds."""

    def __init__(
        self,
        store: TokenStore | None = None,
        *,
        open_browser: Callable[[str], object] = webbrowser.open,
        on_signed_in: Callable[[], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._store = store or KeyringStore()
        self._open_browser = open_browser
        self.on_signed_in = on_signed_in
        self._sleep = sleep
        self._link: dict = {"state": "idle"}
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        # The page polls every two seconds; the credential store is read once.
        self._cached: tuple[str | None, str | None] | None = None

    # --- state ---------------------------------------------------------------

    def _load(self) -> tuple[str | None, str | None]:
        if self._cached is None:
            try:
                token = self._store.get(TOKEN_KEY)
                self._cached = (token, self._store.get(ACCOUNT_KEY) if token else None)
            except Exception:  # noqa: BLE001 - a broken credential store means signed out, not a crash
                self._cached = (None, None)
        return self._cached

    def token(self) -> str | None:
        return self._load()[0]

    def status(self) -> dict:
        token, account = self._load()
        return {"signed_in": bool(token), "account": account, "link": dict(self._link)}

    def forget(self) -> None:
        """Drop the token here (it was revoked, or the player signed out)."""
        self._cached = (None, None)
        self._store.delete(TOKEN_KEY)
        self._store.delete(ACCOUNT_KEY)

    def sign_out(self) -> None:
        token = self.token()
        if token:
            try:
                request("DELETE", "/v1/device", token=token)
            except AccountError:
                pass  # offline: the token still goes from this PC; /account can remove the device
        self.forget()
        self._link = {"state": "idle"}

    # --- linking -------------------------------------------------------------

    def begin_link(self) -> dict:
        """Ask for a code, open the confirm page, and poll in the background."""
        if self._thread is not None and self._thread.is_alive():
            return dict(self._link)
        # Fails early, before a code is shown, if there is nowhere to keep the token.
        if isinstance(self._store, KeyringStore):
            self._store._keyring()
        status, body = request("POST", "/v1/device/code", json_body={"device_name": device_name()})
        if status != 200:
            raise AccountError(f"sign-in could not start ({status})")
        code = json.loads(body)
        if not str(code.get("verification_uri_complete", "")).startswith(("https://", "http://")):
            raise AccountError("sign-in could not start (bad link from the server)")
        self._link = {
            "state": "waiting",
            "user_code": code["user_code"],
            "url": code["verification_uri_complete"],
            "expires_at": time.time() + code["expires_in"],
        }
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._poll, args=(code["device_code"], code["interval"], code["expires_in"]), name="sign-in",
            daemon=True,
        )
        self._thread.start()
        self._open_browser(code["verification_uri_complete"])
        return dict(self._link)

    def cancel_link(self) -> None:
        self._cancel.set()
        self._link = {"state": "idle"}

    def _poll(self, device_code: str, interval: float, expires_in: float) -> None:
        deadline = time.monotonic() + expires_in
        while not self._cancel.is_set() and time.monotonic() < deadline:
            self._sleep(interval)
            if self._cancel.is_set():
                return
            try:
                status, body = request("POST", "/v1/device/token", json_body={"device_code": device_code})
            except AccountError:
                continue  # a network blip; keep polling until the code expires
            reply = json.loads(body or b"{}")
            error = reply.get("error")
            if status == 200 and "token" in reply:
                try:
                    self._store.set(TOKEN_KEY, reply["token"])
                    self._store.set(ACCOUNT_KEY, reply.get("account") or "")
                    self._cached = (reply["token"], reply.get("account") or "")
                except Exception as e:  # noqa: BLE001 - the credential store's own errors
                    self._link = {"state": "failed", "message": f"couldn't save the sign-in: {e}"}
                    return
                self._link = {"state": "done", "account": reply.get("account")}
                if self.on_signed_in is not None:
                    self.on_signed_in()
                return
            if error == "slow_down":
                interval += 5
            elif error == "access_denied":
                self._link = {"state": "failed", "message": "Sign-in was cancelled in the browser."}
                return
            elif error != "authorization_pending":
                break
        if not self._cancel.is_set():
            self._link = {"state": "failed", "message": "The code expired. Start again."}
