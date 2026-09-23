# PyInstaller spec for the Windows bundle (M5 step 1).
#
#   uv sync --group bundle
#   uv run pyinstaller --noconfirm packaging/previously-on.spec
#   dist/PreviouslyOn/previously-on-cli.exe check
#
# One folder, two executables sharing it: PreviouslyOn.exe (the window, no
# console — what a player starts) and previously-on-cli.exe (the command line,
# for `check` and `snapshot`). One-folder, not one-file: a one-file build
# unpacks ~150 MB of OCR runtime to %TEMP% on every start, and antivirus
# scanners flag self-extracting executables far more often.
#
# PyInstaller only bundles what an import statement reaches. What it cannot
# see is listed here; `previously-on check` on the built folder is the test
# that nothing was left behind (CI runs it on every build).

import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = SPECPATH + "/.."

datas = [
    # The window's page, stylesheet, script and font (importlib.resources).
    (ROOT + "/src/previously_on/app/ui", "previously_on/app/ui"),
]
# RapidOCR loads config.yaml and the three ONNX models by path from its package.
datas += collect_data_files("rapidocr_onnxruntime")
binaries = collect_dynamic_libs("onnxruntime")

hiddenimports = [
    # Profiles are imported by name from games/__init__; keep every one.
    *collect_submodules("previously_on"),
    # Both providers are imported lazily inside functions.
    "openai",
    "anthropic",
]
if sys.platform == "win32":
    # dxcam's DXGI bindings are imported inside the capture source; the
    # WinForms/WebView2 platform is picked by pywebview at runtime.
    hiddenimports += collect_submodules("dxcam")
    hiddenimports += ["webview.platforms.winforms", "webview.platforms.edgechromium", "clr"]

a = Analysis(
    [ROOT + "/packaging/app_entry.py", ROOT + "/packaging/cli_entry.py"],
    pathex=[ROOT + "/src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "matplotlib", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

# Analysis puts the scripts in order; each EXE runs its own.
app_script, cli_script = a.scripts[-2], a.scripts[-1]
bootstrap = [s for s in a.scripts if s not in (app_script, cli_script)]

app_exe = EXE(
    pyz,
    bootstrap + [app_script],
    exclude_binaries=True,
    name="PreviouslyOn",
    console=False,
    upx=False,
)
cli_exe = EXE(
    pyz,
    bootstrap + [cli_script],
    exclude_binaries=True,
    name="previously-on-cli",
    console=True,
    upx=False,
)
coll = COLLECT(
    app_exe,
    cli_exe,
    a.binaries,
    a.datas,
    upx=False,
    name="PreviouslyOn",
)
