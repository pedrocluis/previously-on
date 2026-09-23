"""``previously-on check``: does this install have everything it needs?

Written for the Windows bundle first — PyInstaller drops data files and DLLs
it cannot see an import for, and the failure only shows on the player's
machine. Each check exercises the real thing (loads the OCR models and
reads a rendered line, opens the capture backend, loads the webview's
platform layer) rather than testing that a file exists. CI runs it on the
frozen build; a player can run it and paste the output into an issue.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from typing import Callable

from . import __version__


@dataclass(slots=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _ui_files() -> str:
    from .app import ui_path

    index = ui_path()
    missing = [
        name
        for name in ("index.html", "app.js", "app.css", "fonts/mona-sans-latin-wdth-normal.woff2")
        if not (index.parent / name).is_file()
    ]
    if missing:
        raise FileNotFoundError(f"missing under {index.parent}: {', '.join(missing)}")
    return str(index.parent)


def _ocr() -> str:
    """Load the ONNX models and read a line rendered here, so a missing
    model, config or runtime DLL fails now and not mid-session."""
    import cv2
    import numpy as np

    from .ocr import Ocr

    image = np.full((120, 640, 3), 24, np.uint8)
    cv2.putText(image, "YOU DIED", (60, 85), cv2.FONT_HERSHEY_DUPLEX, 2.4, (40, 40, 200), 4, cv2.LINE_AA)
    lines = Ocr(threads=1).read(image)
    text = " ".join(line.text for line in lines)
    if "YOUDIED" not in text.upper().replace(" ", ""):
        raise RuntimeError(f"read {text!r} instead of 'YOU DIED'")
    return f"read {text!r}"


def _profiles() -> str:
    from .games import list_profiles

    return ", ".join(p.id for p in list_profiles())


def _dxcam_module() -> str:
    """Importable at all: a bundle that lost dxcam or its compiled parts
    fails here, whatever the machine's display."""
    import dxcam
    from dxcam.processor import cv2_processor  # noqa: F401  the default colour conversion

    return "importable"


def _dxcam() -> str:
    import dxcam

    outputs = [line.strip() for line in str(dxcam.output_info()).splitlines() if line.strip()]
    if not outputs:
        raise RuntimeError("no display outputs")
    return "; ".join(outputs)


def _mss() -> str:
    import mss

    with mss.mss() as sct:
        return f"{len(sct.monitors) - 1} monitor(s)"


def _webview2_version() -> str:
    """The Evergreen runtime registers itself under EdgeUpdate; pywebview
    needs it on Windows (preinstalled on 11 and current 10)."""
    import winreg

    guid = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{guid}"),
    ]
    for hive, key in keys:
        try:
            with winreg.OpenKey(hive, key) as handle:
                version, _ = winreg.QueryValueEx(handle, "pv")
        except OSError:
            continue
        if version and version != "0.0.0.0":
            return str(version)
    raise RuntimeError("the Microsoft Edge WebView2 Runtime is not installed")


def _webview_platform() -> str:
    """Import the GUI layer pywebview will start with: WinForms over
    pythonnet on Windows (the part a bundle most easily loses), GTK here."""
    import webview  # noqa: F401

    if sys.platform == "win32":
        import webview.platforms.winforms  # noqa: F401  loads the .NET runtime and the WebView2 assemblies
    else:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401
    return "winforms + webview2" if sys.platform == "win32" else "gtk"


def _run(name: str, fn: Callable[[], str], required: bool = True) -> Check:
    try:
        return Check(name, True, fn(), required)
    except Exception as exc:  # the point is to report, not to stop at the first failure
        return Check(name, False, f"{type(exc).__name__}: {exc}", required)


def run_checks() -> list[Check]:
    checks = [
        _run("ui files", _ui_files),
        _run("game profiles", _profiles),
        _run("ocr", _ocr),
        _run("window", _webview_platform),
    ]
    if sys.platform == "win32":
        checks.append(_run("webview2 runtime", _webview2_version))
        checks.append(_run("dxcam", _dxcam_module))
        # No output to duplicate (a VM, a remote session) is not fatal: the
        # app falls back to GDI, which sees borderless and windowed games.
        checks.append(_run("capture (dxcam)", _dxcam, required=False))
    # GDI: the fallback on Windows when dxcam cannot open an output.
    checks.append(_run("capture (mss)", _mss, required=False))
    return checks


def report(checks: list[Check]) -> str:
    frozen = " (bundle)" if getattr(sys, "frozen", False) else ""
    from .session import default_data_dir

    lines = [
        f"previously-on {__version__}{frozen} · Python {platform.python_version()} · {platform.platform()}",
        f"  data: {default_data_dir()}  (sessions, recaps, app.log)",
    ]
    for c in checks:
        mark = "ok  " if c.ok else ("FAIL" if c.required else "warn")
        lines.append(f"  {mark} {c.name}: {c.detail}")
    return "\n".join(lines)


def failed(checks: list[Check]) -> bool:
    return any(not c.ok and c.required for c in checks)
