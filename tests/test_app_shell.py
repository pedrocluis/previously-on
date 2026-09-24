"""First run, tray, start at sign-in and the one-copy guard (M5 step 3).
The tray and the window themselves need a desktop; what they are built on
is tested here."""

import json
import threading

from previously_on.app.api import Api
from previously_on.app.autostart import BACKGROUND_FLAG, Autostart, _DesktopFile, _Registry
from previously_on.app.config import AppConfig
from previously_on.app.instance import InstanceServer, signal_running
from previously_on.app.tray import icon_image, status_line
from previously_on.games import list_profiles

from .test_app import playthrough

LAUNCHER = ["/opt/Previously On/PreviouslyOn", BACKGROUND_FLAG]


# --- start at sign-in ------------------------------------------------------------


def test_desktop_file_round_trip(tmp_path):
    a = Autostart(_DesktopFile(tmp_path), LAUNCHER)
    assert a.supported and not a.enabled()
    a.set(True)
    text = (tmp_path / "previously-on.desktop").read_text()
    assert "Exec='/opt/Previously On/PreviouslyOn' --background\n" in text and "Terminal=false" in text
    assert a.enabled() and a.to_dict() == {"supported": True, "enabled": True}
    a.set(False)
    assert not a.enabled()
    a.set(False)  # already off: no error


def test_refresh_rewrites_an_entry_for_another_copy(tmp_path):
    store = _DesktopFile(tmp_path)
    Autostart(store, ["/old/PreviouslyOn", BACKGROUND_FLAG]).set(True)
    a = Autostart(store, LAUNCHER)
    assert a.refresh() and store.get() == store.render(LAUNCHER)
    assert not a.refresh()  # already this copy
    a.set(False)
    assert not a.refresh()  # off stays off


def test_no_launcher_means_unsupported(tmp_path):
    a = Autostart(_DesktopFile(tmp_path), None)
    assert not a.supported and a.to_dict() == {"supported": False, "enabled": False}
    assert not a.refresh()


class FakeWinreg:
    HKEY_CURRENT_USER, KEY_SET_VALUE, REG_SZ = object(), 2, 1

    def __init__(self):
        self.values: dict[str, str] = {}

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, hive, path, reserved=0, access=0):
        return self._Key()

    CreateKey = OpenKey

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


def test_registry_value_is_a_quoted_command_line():
    reg = FakeWinreg()
    a = Autostart(_Registry(reg), [r"C:\Games\Previously On\PreviouslyOn.exe", BACKGROUND_FLAG])
    a.set(True)
    assert reg.values == {"PreviouslyOn": r'"C:\Games\Previously On\PreviouslyOn.exe" --background'}
    assert a.enabled() and not a.refresh()
    a.set(False)
    a.set(False)
    assert reg.values == {} and not a.enabled()


# --- one copy at a time ---------------------------------------------------------------


def test_a_second_copy_shows_the_first_ones_window(tmp_path):
    assert not signal_running(tmp_path)  # nobody there
    shown = threading.Event()
    server = InstanceServer(tmp_path, shown.set)
    try:
        assert signal_running(tmp_path)
        assert shown.wait(2)
    finally:
        server.close()
    assert not (tmp_path / "instance.port").exists()
    assert not signal_running(tmp_path)


def test_a_stale_port_that_is_not_us_is_ignored(tmp_path):
    import socket

    other = socket.socket()
    other.bind(("127.0.0.1", 0))
    other.listen(1)
    (tmp_path / "instance.port").write_text(str(other.getsockname()[1]))

    def greet_wrong():
        conn, _ = other.accept()
        conn.sendall(b"HTTP/1.1 400\r\n")
        conn.close()

    threading.Thread(target=greet_wrong, daemon=True).start()
    try:
        assert not signal_running(tmp_path)
    finally:
        other.close()
    (tmp_path / "instance.port").write_text("not a port")
    assert not signal_running(tmp_path)


# --- tray -------------------------------------------------------------------------------


def test_tray_icon_draws_every_state():
    for state in ("idle", "waiting", "capturing", "summarizing", "error"):
        img = icon_image(state)
        assert img.size == (64, 64) and img.mode == "RGBA"
    # The capture dot is the only difference between these two.
    assert icon_image("capturing").tobytes() != icon_image("waiting").tobytes()
    assert icon_image("idle").tobytes() != icon_image("waiting").tobytes()


def test_tray_status_line():
    assert status_line({"state": "waiting", "running": True}, "a game") == "Waiting for a game"
    assert status_line({"state": "capturing", "events": 1}, "x") == "Capturing · 1 event"
    assert status_line({"state": "capturing", "events": 12}, "x") == "Capturing · 12 events"
    assert status_line({"state": "idle", "running": False}, "x") == "Not watching"
    assert status_line({"state": "error", "message": "boom"}, "x") == "Stopped: boom"


# --- first run ------------------------------------------------------------------------------


def test_first_run_until_any_game_has_a_session(tmp_path, eldenring, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PREVIOUSLY_ON_MODEL", raising=False)
    auto = Autostart(_DesktopFile(tmp_path / "autostart"), LAUNCHER)
    api = Api(list_profiles(), tmp_path, None, AppConfig(), tmp_path / "config.json", autostart=auto)
    api.tray = True
    home = api.home()
    json.dumps(home)
    f = home["first_run"]
    assert f["games"] == [p.display_name for p in list_profiles()]
    assert f["has_key"] is False and f["tray"] is True
    assert f["autostart"] == {"supported": True, "enabled": False}

    # The checkbox on the welcome screen goes through save_settings.
    out = api.save_settings({"start_at_login": True})
    assert out["start_at_login"] == {"supported": True, "enabled": True} and auto.enabled()
    assert api.save_settings({"openai_api_key": "sk-abcdefghijklmnop"})["has_openai_key"]
    assert api.home()["first_run"]["has_key"] is True

    # One session of any game ends the welcome; other games show their own empty page.
    playthrough(tmp_path, eldenring)
    assert "first_run" not in api.home()
    api.select_game("sekiro")
    home = api.home()
    assert home["empty"] and "first_run" not in home


def test_start_at_login_unavailable_is_an_error_not_a_crash(tmp_path):
    api = Api(list_profiles(), tmp_path, None, AppConfig(), tmp_path / "config.json")
    assert api.get_settings()["start_at_login"] == {"supported": False, "enabled": False}
    assert "not available" in api.save_settings({"start_at_login": True})["error"]
    unsupported = Autostart(_DesktopFile(tmp_path), None)
    api = Api(list_profiles(), tmp_path, None, AppConfig(), tmp_path / "config.json", autostart=unsupported)
    assert "not available" in api.save_settings({"start_at_login": True})["error"]
    assert "error" not in api.save_settings({"start_at_login": None, "monitor": 2})
