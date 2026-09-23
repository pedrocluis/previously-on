"""The add-game scaffold produces a profile that imports, satisfies GameProfile and rejects junk."""

from __future__ import annotations

import ast
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from previously_on.games import GameProfile
from previously_on.ocr import OcrLine

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / ".claude/skills/add-game/scripts/scaffold.py"
BLACK = np.zeros((1080, 1920, 3), dtype=np.uint8)

pytestmark = pytest.mark.skipif(not SCAFFOLD.exists(), reason="the add-game scaffold is not in this checkout")


def run_scaffold(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCAFFOLD), "demo_game", "--name", "Demo Game", "--process", "demo.exe", "--root", str(root), *extra],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def tree(tmp_path):
    """A skeleton of the repo: the real games/__init__.py, empty tests/."""
    games = tmp_path / "src/previously_on/games"
    games.mkdir(parents=True)
    shutil.copy(ROOT / "src/previously_on/games/__init__.py", games / "__init__.py")
    (tmp_path / "tests").mkdir()
    return tmp_path


def load_profile(tree: Path):
    """Import the generated module as if it were previously_on.games.demo_game."""
    import previously_on.games as games_pkg

    spec = importlib.util.spec_from_file_location(
        "previously_on.games.demo_game", tree / "src/previously_on/games/demo_game.py", submodule_search_locations=None
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = games_pkg.__name__
    spec.loader.exec_module(module)
    return module.DemoGameProfile()


def test_scaffold_writes_a_working_profile(tree):
    result = run_scaffold(tree)
    assert result.returncode == 0, result.stderr
    assert (tree / "tests/fixtures/demo_game/README.md").exists()
    assert (tree / "tests/fixtures/demo_game/labels.yaml").read_text().startswith("#")
    assert (tree / "tests/test_classify_demo_game.py").exists()

    init_src = (tree / "src/previously_on/games/__init__.py").read_text()
    ast.parse(init_src)
    assert "from .demo_game import DemoGameProfile" in init_src and "DemoGameProfile()" in init_src

    profile = load_profile(tree)
    assert isinstance(profile, GameProfile)
    assert profile.id == "demo_game" and profile.process_names == ("demo.exe",)
    names = {r.name for r in profile.regions}
    assert names == {"center_banner", "subtitle", "boss_bar", "item_popup"}
    assert set(profile.MIN_CONF) == names and set(profile.quiet_after_event) == names

    junk = [
        [OcrLine("1%", 0.3)],
        [OcrLine("Settings", 0.99, x0=0.0, y0=0.0, x1=0.1, y1=0.05)],
        [OcrLine("HP 412 / 600", 0.99, x0=0.3, y0=0.2, x1=0.7, y1=0.8)],
        [OcrLine("Ashina Castle", 0.99, x0=0.3, y0=0.2, x1=0.7, y1=0.8)],  # a real-looking name: still nothing until measured
    ]
    for region in profile.regions:
        for lines in junk:
            assert profile.classify(region, lines, BLACK) == [], (region.name, lines)
        assert profile.classify(region, [], BLACK) == []


def test_scaffold_honours_region_subset_and_refuses_overwrite(tree):
    result = run_scaffold(tree, "--regions", "center_banner,subtitle")
    assert result.returncode == 0, result.stderr
    profile = load_profile(tree)
    assert [r.name for r in profile.regions] == ["center_banner", "subtitle"]
    src = (tree / "src/previously_on/games/demo_game.py").read_text()
    assert "has_boss_hp_bar" not in src and "import cv2" not in src

    again = run_scaffold(tree)
    assert again.returncode == 1 and "refusing to overwrite" in again.stderr


def test_scaffold_rejects_bad_ids(tree):
    result = subprocess.run(
        [sys.executable, str(SCAFFOLD), "Dark-Souls", "--name", "x", "--process", "x.exe", "--root", str(tree)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
