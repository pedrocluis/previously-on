"""The website's server runs ``stats`` and ``card`` on synced logs without
the capture stack. Importing them must not pull in OpenCV, numpy or the
window."""

import subprocess
import sys

BLOCKED = ("cv2", "numpy", "webview", "rapidocr_onnxruntime", "mss", "dxcam")

SCRIPT = f"""
import sys
for name in {BLOCKED!r}:
    sys.modules[name] = None  # any import of it raises ImportError
import previously_on.card, previously_on.recap.schema, previously_on.session, previously_on.stats
"""


def test_stats_and_card_import_without_capture_stack():
    result = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
